"""RNF-02 — Desempenho em tempo real.

Metas do documento de requisitos: ≥ 10 quadros/s efetivos de pipeline e
latência de confirmação de letra ≤ 500 ms após o gesto estabilizar. A
verificação prevista é "medição pelo painel e pelo benchmark na Pi;
comparação com a máquina de referência" — aqui se verifica a medição em si e
as margens na máquina de teste. Os números da Pi saem da entrega de execução
no alvo.
"""
import time

from libras.benchmark import bench_pipeline, run_benchmark
from libras.classifier import KnnClassifier
from libras.config import Config
from libras.demo import make_demo_components, make_synthetic_dataset
from libras.features import normalize_landmarks
from libras.pipeline import PipelineState, TranslationPipeline
from libras.temporal import LetterConfirmer

FPS_MINIMO = 10.0
LATENCIA_MAXIMA_MS = 500.0


def test_pipeline_sustenta_a_meta_de_quadros_por_segundo():
    """FPS efetivo do pipeline completo, sem pausa entre quadros."""
    config = Config(target_fps=0)
    source, extractor, classifier = make_demo_components(config)
    pipeline = TranslationPipeline(source, extractor, classifier, config,
                                   state=PipelineState())
    frames = 120
    t0 = time.perf_counter()
    for _ in range(frames):
        pipeline.step()
    fps = frames / (time.perf_counter() - t0)

    assert fps >= FPS_MINIMO, f"{fps:.1f} fps < meta de {FPS_MINIMO} fps"
    assert pipeline.stats()["fps"] > 0  # o painel mede o mesmo laço


def test_latencia_de_confirmacao_dentro_da_meta():
    """Quadros gastos entre o gesto estabilizar e a letra sair, convertidos
    pela taxa de captura configurada."""
    config = Config()
    X, y, prototypes = make_synthetic_dataset()
    classifier = KnnClassifier(k=config.knn_k).fit(X, y)
    confirmer = LetterConfirmer(min_confidence=config.min_confidence,
                                window_size=config.window_size,
                                min_votes=config.min_votes,
                                release_frames=config.release_frames)

    vector = normalize_landmarks(prototypes["A"])
    frames = 0
    while frames < 100:
        frames += 1
        if confirmer.update(classifier.predict(vector)) == "A":
            break
    else:
        raise AssertionError("letra estável nunca foi confirmada")

    latencia_ms = frames / config.target_fps * 1000
    assert latencia_ms <= LATENCIA_MAXIMA_MS, (
        f"{frames} quadros a {config.target_fps} fps = {latencia_ms:.0f} ms")


def test_janela_temporal_cabe_no_orcamento_de_latencia():
    """Regressão de configuração: aumentar a janela de votação sem baixar a
    meta de FPS estouraria a latência de confirmação."""
    config = Config()
    pior_caso_ms = config.window_size / config.target_fps * 1000
    assert pior_caso_ms <= LATENCIA_MAXIMA_MS


def test_benchmark_mede_o_pipeline_e_as_condicoes_termicas():
    """O benchmark registra clock e temperatura antes e depois das cargas —
    é o que evidencia throttling na Pi."""
    carga = bench_pipeline(frames=30)
    assert carga["metrica"] == "FPS" and carga["valor"] > 0
    assert carga["latencia_por_estagio_ms"]

    resultado = run_benchmark(rapido=True)
    for lado in ("condicoes_iniciais", "condicoes_finais"):
        assert set(resultado[lado]) == {"clock_mhz", "temperatura_c"}
