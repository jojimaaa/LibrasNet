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
from libras.capture import SyntheticSource
from libras.classifier import KnnClassifier
from libras.config import Config
from libras.demo import make_demo_components, make_synthetic_dataset
from libras.features import normalize_landmarks
from libras.pipeline import PipelineState, TranslationPipeline, measure_fps
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


def test_calibragem_a_30_fps_reproduz_os_padroes():
    """As janelas em segundos e em quadros descrevem a mesma coisa: a 30 fps
    a conversão tem de ser a identidade."""
    padrao = Config()
    calibrada = padrao.tuned_for_fps(30.0)
    assert (calibrada.window_size, calibrada.min_votes,
            calibrada.release_frames, calibrada.word_pause_frames) == (
        padrao.window_size, padrao.min_votes,
        padrao.release_frames, padrao.word_pause_frames)


def test_calibragem_mantem_a_meta_de_latencia_em_plataforma_lenta():
    """É o caso da Raspberry Pi: a 6-10 fps, a janela padrão de 30 fps
    gastaria mais de 1 s por letra."""
    for fps in (4.0, 6.0, 8.0, 12.0, 20.0, 30.0):
        calibrada = Config().tuned_for_fps(fps)
        latencia = calibrada.confirmation_latency_ms(fps)
        assert latencia <= LATENCIA_MAXIMA_MS, f"{fps} fps: {latencia:.0f} ms"

    sem_calibrar = Config().confirmation_latency_ms(8.0)
    assert sem_calibrar > LATENCIA_MAXIMA_MS, \
        "o cenário que a calibragem corrige deixou de existir"


def test_calibragem_gera_configuracao_aceita_por_b5():
    """min_votes nunca pode passar de window_size — o LetterConfirmer rejeita,
    e a falha só apareceria na partida, na Pi."""
    for fps in (1.0, 2.5, 4.0, 7.5, 15.0, 30.0, 60.0):
        calibrada = Config().tuned_for_fps(fps)
        assert 0 < calibrada.min_votes <= calibrada.window_size
        assert calibrada.release_frames >= 1
        assert calibrada.word_pause_frames >= 2
        LetterConfirmer(min_confidence=calibrada.min_confidence,
                        window_size=calibrada.window_size,
                        min_votes=calibrada.min_votes,
                        release_frames=calibrada.release_frames)


def test_calibragem_ignora_medicao_invalida():
    padrao = Config()
    assert padrao.tuned_for_fps(0.0).window_size == padrao.window_size


def test_medicao_de_fps_alimenta_a_calibragem():
    config = Config(target_fps=0)
    source, extractor, classifier = make_demo_components(config)
    fps = measure_fps(source, extractor, classifier, config, frames=20)
    assert fps > 0
    assert config.tuned_for_fps(fps).window_size >= 3


def test_pipeline_publica_quadros_descartados_com_captura_em_thread(
        fast_config):
    """O painel precisa da distância entre a taxa da câmera e a do pipeline;
    sem captura em thread a chave não aparece."""
    from libras.capture import ThreadedFrameSource

    _, extractor, classifier = make_demo_components(fast_config)
    source = ThreadedFrameSource(
        SyntheticSource(fast_config.frame_width, fast_config.frame_height))
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=PipelineState())
    try:
        for _ in range(10):
            pipeline.step()
        assert "quadros_descartados" in pipeline.stats()
    finally:
        source.release()

    sem_thread = make_demo_components(fast_config)
    simples = TranslationPipeline(*sem_thread, fast_config,
                                  state=PipelineState())
    simples.step()
    assert "quadros_descartados" not in simples.stats()


def test_benchmark_mede_o_pipeline_e_as_condicoes_termicas():
    """O benchmark registra clock e temperatura antes e depois das cargas —
    é o que evidencia throttling na Pi."""
    carga = bench_pipeline(frames=30)
    assert carga["metrica"] == "FPS" and carga["valor"] > 0
    assert carga["latencia_por_estagio_ms"]

    resultado = run_benchmark(rapido=True)
    for lado in ("condicoes_iniciais", "condicoes_finais"):
        assert set(resultado[lado]) == {"clock_mhz", "temperatura_c"}
