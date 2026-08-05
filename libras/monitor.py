"""Módulo transversal — instrumentação e monitoramento do processador.

Amostra contadores do sistema (psutil, ``/sys``, ``/proc`` e, quando
presentes, ``vcgencmd`` e ``perf``) e expõe um retrato consolidado para o
painel do frontend (RF-07, Seção 4.1 da documentação). CPI e taxa de clock
derivam da equação clássica de desempenho T_CPU = N_instruções × CPI ×
T_clock (HENNESSY; PATTERSON, 2017).

Toda leitura é opcional por construção: a métrica sem fonte na plataforma
volta ``None`` e o painel a mostra como indisponível, em vez de o sistema
falhar por ausência de sensor (RNF-06).
"""
from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import threading
import time

import psutil

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- estático
def machine_info() -> dict:
    """Identificação da máquina — permite comparar hardwares no painel."""
    return {
        "hostname": platform.node(),
        "sistema": f"{platform.system()} {platform.release()}",
        "arquitetura": platform.machine(),
        "processador": _cpu_model() or platform.processor() or "desconhecido",
        "nucleos_fisicos": psutil.cpu_count(logical=False),
        "nucleos_logicos": psutil.cpu_count(logical=True),
        "python": platform.python_version(),
    }


def _cpu_model() -> "str | None":
    """Nome do processador via /proc/cpuinfo (Linux/Raspberry Pi).

    Em ARM o campo ``model name`` costuma faltar, e ``platform.processor()``
    devolve string vazia — daí a busca também por ``Model`` e ``Hardware``,
    que é o que identifica a Pi.
    """
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    for key in ("Model", "model name", "Hardware"):
        match = re.search(rf"^{key}\s*:\s*(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


# --------------------------------------------------------------- sensores
def read_temperature_c() -> "float | None":
    """Temperatura do processador; None quando não há sensor acessível."""
    try:
        temps = psutil.sensors_temperatures()
        for entries in temps.values():
            if entries:
                return float(entries[0].current)
    except (AttributeError, OSError):
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp",
                  encoding="ascii") as fh:
            return int(fh.read().strip()) / 1000.0
    except (OSError, ValueError):
        pass
    out = _vcgencmd("measure_temp")
    if out:
        match = re.search(r"temp=([\d.]+)", out)
        if match:
            return float(match.group(1))
    return None


def read_clock_mhz() -> "float | None":
    """Frequência atual do processador em MHz; None quando indisponível."""
    try:
        freq = psutil.cpu_freq()
        if freq and freq.current:
            return float(freq.current)
    except Exception:
        pass
    out = _vcgencmd("measure_clock", "arm")
    if out:
        match = re.search(r"=(\d+)", out)
        if match:
            return int(match.group(1)) / 1e6
    return None


def _vcgencmd(*args) -> "str | None":
    """Consulta o firmware da Raspberry Pi (quando o binário existe)."""
    exe = shutil.which("vcgencmd")
    if not exe:
        return None
    try:
        return subprocess.run([exe, *args], capture_output=True, text=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def read_cpi_via_perf(duration: float = 0.2) -> "dict | None":
    """Mede ciclos e instruções de todo o sistema com ``perf stat`` (Linux).

    CPI = ciclos / instruções; IPC = 1 / CPI. Retorna None quando o perf não
    está disponível (ex.: Windows, ou kernel sem perf_event habilitado).
    """
    exe = shutil.which("perf")
    if not exe:
        return None
    cmd = [exe, "stat", "-a", "-x", ",", "-e", "cycles,instructions",
           "--", "sleep", str(duration)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=duration + 5)
    except (OSError, subprocess.SubprocessError):
        return None
    cycles = instructions = 0.0
    for line in proc.stderr.splitlines():
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            value = float(parts[0])
        except ValueError:
            continue
        if "instructions" in parts[2]:
            instructions += value
        elif "cycles" in parts[2]:
            cycles += value
    if not cycles or not instructions:
        return None
    return {"ciclos": cycles, "instrucoes": instructions,
            "cpi": cycles / instructions, "ipc": instructions / cycles}


# ----------------------------------------------------------------- monitor
class PerformanceMonitor:
    """Amostra periodicamente as métricas e guarda o último retrato."""

    def __init__(self, interval: float = 1.0, cpi_interval: float = 5.0):
        self.interval = interval
        self.cpi_interval = cpi_interval
        self._lock = threading.Lock()
        self._latest: dict = {}
        self._last_cpi: "dict | None" = None
        self._last_cpi_at = 0.0
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    def sample(self) -> dict:
        """Coleta uma amostra agora (também usada pela API do servidor).

        O CPI é medido em intervalo próprio, mais longo: cada medição custa
        uma janela de ``perf stat``, e o painel atualiza a cada segundo.
        """
        now = time.time()
        memory = psutil.virtual_memory()
        snapshot = {
            "timestamp": now,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_por_nucleo": psutil.cpu_percent(interval=None, percpu=True),
            "ram_percent": memory.percent,
            "ram_usada_mb": round(memory.used / 2**20, 1),
            "ram_total_mb": round(memory.total / 2**20, 1),
            "clock_mhz": read_clock_mhz(),
            "temperatura_c": read_temperature_c(),
        }
        with self._lock:
            cpi_due = now - self._last_cpi_at >= self.cpi_interval
            if cpi_due:
                self._last_cpi_at = now
        if cpi_due:
            measured = read_cpi_via_perf()
            with self._lock:
                self._last_cpi = measured
        with self._lock:
            last_cpi = self._last_cpi
            snapshot["cpi"] = last_cpi["cpi"] if last_cpi else None
            snapshot["ipc"] = last_cpi["ipc"] if last_cpi else None
            self._latest = snapshot
        return dict(snapshot)

    def latest(self) -> dict:
        """Último retrato coletado (amostra na hora se ainda não houver)."""
        with self._lock:
            if self._latest:
                return dict(self._latest)
        return self.sample()

    # ------------------------------------------------------ segundo plano
    def start(self) -> None:
        psutil.cpu_percent(interval=None)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="monitor")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sample()
            except Exception:
                log.exception("Falha ao amostrar métricas")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
