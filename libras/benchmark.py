"""Benchmark de desempenho do processador (RNF-02 e RNF-03).

Executa cargas de trabalho padronizadas e reporta métricas que permitem
comparar o mesmo projeto em hardwares diferentes (ex.: notebook × Raspberry
Pi), incluindo CPI/IPC medidos com ``perf`` quando disponível — a equação de
desempenho da Seção 4 da documentação (HENNESSY; PATTERSON, 2017).

As quatro cargas isolam eixos distintos do processador (ALU escalar, ponto
flutuante vetorizado, banda de memória e o pipeline real do projeto), porque
uma pontuação única não diria *onde* a Pi perde para a máquina de referência.

Uso:
    python -m libras.benchmark [--rapido] [--json saida.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time

import numpy as np

from .config import Config
from .demo import make_demo_components
from .monitor import (
    machine_info,
    read_clock_mhz,
    read_cpi_via_perf,
    read_temperature_c,
)
from .pipeline import PipelineState, TranslationPipeline

REFERENCE = {"inteiro_python": 23.0,     # MOPS
             "flutuante_matmul": 127.0,  # GFLOPS
             "memoria_copia": 30.0,      # GB/s
             "pipeline_traducao": 95.0}  # FPS


def _best_time(fn, repeats: int) -> float:
    """Menor tempo de parede entre ``repeats`` execuções (menos ruído)."""
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def bench_inteiro(n: int = 2_000_000, repeats: int = 3) -> dict:
    """Laço de ALU em Python puro — sensível ao clock e ao IPC de 1 núcleo."""
    def load():
        acc = 0
        for i in range(n):
            acc += i ^ (i >> 3)
        return acc

    best = _best_time(load, repeats)
    return {"nome": "inteiro_python",
            "descricao": f"{n:,} iterações de inteiros em Python puro "
                         "(1 núcleo)",
            "melhor_s": round(best, 6),
            "metrica": "MOPS", "valor": round(n / best / 1e6, 2)}


def bench_flutuante(n: int = 384, repeats: int = 5) -> dict:
    """Multiplicação de matrizes (numpy/BLAS) — ponto flutuante vetorizado."""
    rng = np.random.default_rng(1)
    a = rng.random((n, n))
    b = rng.random((n, n))
    best = _best_time(lambda: a @ b, repeats)
    gflops = 2 * n**3 / best / 1e9
    return {"nome": "flutuante_matmul",
            "descricao": f"multiplicação de matrizes {n}×{n} (numpy)",
            "melhor_s": round(best, 6),
            "metrica": "GFLOPS", "valor": round(gflops, 2)}


def bench_memoria(mb: int = 64, repeats: int = 5) -> dict:
    """Cópia de vetor grande — largura de banda de memória."""
    n = mb * 2**20 // 8
    src = np.zeros(n)
    dst = np.empty_like(src)

    def load():
        dst[:] = src

    best = _best_time(load, repeats)
    gbs = 2 * n * 8 / best / 1e9  # leitura + escrita
    return {"nome": "memoria_copia",
            "descricao": f"cópia de {mb} MiB (leitura + escrita)",
            "melhor_s": round(best, 6),
            "metrica": "GB/s", "valor": round(gbs, 2)}


def bench_pipeline(frames: int = 300) -> dict:
    """Pipeline de tradução completo em modo sintético, sem pausa entre
    quadros: FPS máximo alcançável e latência média por estágio.

    É a carga que mais importa: as outras três explicam o resultado desta.
    """
    config = Config()
    source, extractor, classifier = make_demo_components(config)
    pipeline = TranslationPipeline(source, extractor, classifier, config,
                                   state=PipelineState())
    t0 = time.perf_counter()
    for _ in range(frames):
        pipeline.step()
    total = time.perf_counter() - t0
    return {"nome": "pipeline_traducao",
            "descricao": f"{frames} quadros do pipeline completo "
                         "(modo sintético)",
            "melhor_s": round(total, 6),
            "metrica": "FPS", "valor": round(frames / total, 1),
            "latencia_por_estagio_ms": pipeline.stats()["latencia_ms"]}


def measure_cpi_under_load(duration: float = 1.0) -> "dict | None":
    """CPI/IPC via ``perf`` enquanto uma carga inteira ocupa a CPU.

    Medir sob carga torna o CPI representativo do processador executando
    trabalho real (em repouso ele reflete só o ruído do sistema). Retorna
    None quando o perf não está disponível (ex.: Windows).
    """
    stop = threading.Event()

    def busy():
        acc = i = 0
        while not stop.is_set():
            acc += i ^ (i >> 3)
            i += 1

    thread = threading.Thread(target=busy, daemon=True)
    thread.start()
    try:
        return read_cpi_via_perf(duration=duration)
    finally:
        stop.set()
        thread.join(timeout=1)


def run_benchmark(rapido: bool = False) -> dict:
    """Roda as cargas e devolve o resultado completo (exportável em JSON).

    Clock e temperatura são registrados antes E depois: na Pi, a diferença
    entre os dois é a evidência de *thermal throttling* sob carga.
    """
    results = {
        "maquina": machine_info(),
        "condicoes_iniciais": {"clock_mhz": read_clock_mhz(),
                               "temperatura_c": read_temperature_c()},
        "cargas": [
            bench_inteiro(n=100_000 if rapido else 2_000_000),
            bench_flutuante(n=96 if rapido else 384),
            bench_memoria(mb=8 if rapido else 64),
            bench_pipeline(frames=60 if rapido else 300),
        ],
        "perf_hardware": measure_cpi_under_load(0.3 if rapido else 1.0),
        "condicoes_finais": {"clock_mhz": read_clock_mhz(),
                             "temperatura_c": read_temperature_c()},
    }
    ratios = [c["valor"] / REFERENCE[c["nome"]] for c in results["cargas"]]
    results["pontuacao"] = round(
        1000 * math.prod(ratios) ** (1 / len(ratios)), 1)
    return results


def _fmt(value, unit: str) -> str:
    return "indisponível" if value is None else f"{value:.1f} {unit}"


def format_report(r: dict) -> str:
    lines = []
    add = lines.append
    m = r["maquina"]
    add("=" * 66)
    add("BENCHMARK — Tradutor embarcado de LIBRAS")
    add("=" * 66)
    add(f"Máquina:      {m.get('hostname')} ({m.get('sistema')}, "
        f"{m.get('arquitetura')})")
    add(f"Processador:  {m.get('processador')}")
    add(f"Núcleos:      {m.get('nucleos_fisicos')} físicos / "
        f"{m.get('nucleos_logicos')} lógicos")
    add(f"Python:       {m.get('python')}")
    ini, fim = r["condicoes_iniciais"], r["condicoes_finais"]
    add(f"Clock:        início {_fmt(ini['clock_mhz'], 'MHz')} | "
        f"fim {_fmt(fim['clock_mhz'], 'MHz')}")
    add(f"Temperatura:  início {_fmt(ini['temperatura_c'], '°C')} | "
        f"fim {_fmt(fim['temperatura_c'], '°C')}")
    add("-" * 66)
    add(f"{'carga':<20}{'métrica':<9}{'valor':>10}   descrição")
    for c in r["cargas"]:
        add(f"{c['nome']:<20}{c['metrica']:<9}{c['valor']:>10}   "
            f"{c['descricao']}")
        for stage, ms in c.get("latencia_por_estagio_ms", {}).items():
            add(f"{'':<20}{'ms':<9}{ms:>10}   └─ {stage}")
    add("-" * 66)
    perf = r.get("perf_hardware")
    if perf:
        add(f"CPI (ciclos/instrução): {perf['cpi']:.3f}   "
            f"IPC: {perf['ipc']:.3f}")
        add(f"  ciclos: {perf['ciclos']:.3e}   "
            f"instruções: {perf['instrucoes']:.3e}")
        add("  (medidos com `perf stat` de todo o sistema, sob carga de CPU)")
    else:
        add("CPI/IPC: indisponíveis nesta plataforma — requer `perf` (Linux).")
        add("  Na Raspberry Pi: sudo apt install linux-perf")
    add("-" * 66)
    add(f"PONTUAÇÃO COMPOSTA: {r['pontuacao']} pontos")
    add("  (média geométrica das cargas; 1000 = máquina de referência)")
    add("=" * 66)
    return "\n".join(lines)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m libras.benchmark",
        description="Benchmark de desempenho do processador (RNF-02)")
    parser.add_argument("--rapido", action="store_true",
                        help="versão reduzida das cargas (~5 s); compare "
                             "apenas execuções do mesmo modo entre si")
    parser.add_argument("--json", metavar="ARQUIVO",
                        help="salva o resultado em JSON para comparação")
    args = parser.parse_args(argv)

    results = run_benchmark(rapido=args.rapido)
    print(format_report(results))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"\nResultado salvo em {args.json} — compare arquivos gerados "
              "em máquinas diferentes para avaliar o hardware.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
