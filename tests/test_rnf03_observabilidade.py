"""RNF-03 — Observabilidade do processador.

Verificação do documento de requisitos: painel em tempo real e cargas
padronizadas com testes. Aqui se verifica a amostragem periódica (o painel
recebe dados novos sem pedir), o benchmark comparável entre máquinas e o
relatório que a entrega de avaliação vai usar.
"""
import json
import time

import pytest

from libras.benchmark import REFERENCE, format_report, run_benchmark
from libras.monitor import PerformanceMonitor


@pytest.fixture(scope="module")
def benchmark_results():
    return run_benchmark(rapido=True)


def test_monitor_amostra_em_segundo_plano():
    monitor = PerformanceMonitor(interval=0.05)
    first = monitor.latest()  # amostra síncrona inicial
    monitor.start()
    try:
        deadline = time.time() + 3.0
        current = first
        while (time.time() < deadline
               and current["timestamp"] == first["timestamp"]):
            time.sleep(0.05)
            current = monitor.latest()
        assert current["timestamp"] > first["timestamp"], \
            "a thread de monitoramento não produziu novas amostras"
    finally:
        monitor.stop()


def test_monitor_para_a_thread_ao_ser_encerrado():
    monitor = PerformanceMonitor(interval=0.05)
    monitor.start()
    monitor.stop()
    assert not monitor._thread.is_alive()


def test_falha_de_amostragem_nao_mata_a_thread(monkeypatch):
    """Uma exceção na coleta é registrada e a amostragem continua (RNF-06)."""
    monitor = PerformanceMonitor(interval=0.02)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) <= 2:
            raise OSError("contador sumiu")
        return {"timestamp": time.time()}

    monkeypatch.setattr(monitor, "sample", flaky)
    monitor.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and len(calls) < 4:
        time.sleep(0.02)
    monitor.stop()
    assert len(calls) >= 4, "a thread parou na primeira falha"


def test_benchmark_produz_resultado_comparavel(benchmark_results):
    assert benchmark_results["pontuacao"] > 0
    names = [c["nome"] for c in benchmark_results["cargas"]]
    assert names == list(REFERENCE)
    for load in benchmark_results["cargas"]:
        assert load["melhor_s"] > 0
        assert load["valor"] > 0
    json.dumps(benchmark_results)  # exportável p/ comparação entre máquinas


def test_benchmark_identifica_a_maquina_medida(benchmark_results):
    """Um resultado sem a máquina que o produziu não serve para comparar."""
    machine = benchmark_results["maquina"]
    assert machine["arquitetura"]
    assert machine["nucleos_logicos"] >= 1


def test_relatorio_do_benchmark_cobre_cpi_e_clock(benchmark_results):
    report = format_report(benchmark_results)
    assert "CPI" in report
    assert "Clock" in report
    assert "Temperatura" in report
    assert "PONTUAÇÃO" in report


def test_relatorio_reporta_cpi_indisponivel_sem_perf(benchmark_results):
    """Sem `perf` (Windows), o relatório diz que a métrica falta — e não
    inventa um número."""
    sem_perf = dict(benchmark_results, perf_hardware=None)
    report = format_report(sem_perf)
    assert "indisponíveis nesta plataforma" in report
