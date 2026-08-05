"""RNF-01 — Acessibilidade: entrada só por sinais, saída dupla.

Verificação do documento de requisitos: "Teste que estimula o sistema só com
gestos e observa as duas saídas." Partindo apenas de gestos sintéticos, o
sistema produz o texto que a interface publica (B6/B7) E o áudio do motor de
voz (B8) — a saída dupla do RF-01 + RF-05, sem teclado nem toque.
"""
from libras.demo import make_demo_components
from libras.pipeline import PipelineState, TranslationPipeline
from libras.server import create_app
from libras.tts import NullEngine


def test_comunicacao_apenas_por_sinais_gera_texto_e_voz(fast_config):
    """Entrada: somente gestos. Saída: texto na tela e voz no TTS."""
    source, extractor, classifier = make_demo_components(
        fast_config, text="OI MUNDO", loop=False)
    engine = NullEngine()
    state = PipelineState()
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=state, on_word=engine.speak)
    for _ in range(400):
        pipeline.step()
        if len(state.to_dict()["historico"]) >= 2:
            break

    snapshot = state.to_dict()
    assert snapshot["historico"] == ["OI", "MUNDO"]  # saída em texto (tela)
    assert engine.spoken == ["OI", "MUNDO"]          # saída em voz (TTS)


def test_saida_visual_chega_a_interface_sem_interacao(fast_config):
    """O mesmo estímulo por gestos aparece na API que alimenta a tela: em
    nenhum ponto do caminho há entrada de teclado ou toque."""
    source, extractor, classifier = make_demo_components(
        fast_config, text="OI", loop=False)
    engine = NullEngine()
    state = PipelineState()
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=state, on_word=engine.speak)
    for _ in range(400):
        pipeline.step()
        if state.to_dict()["ultima_palavra"]:
            break

    app = create_app(state.to_dict, lambda: {"pipeline": pipeline.stats()})
    app.config["TESTING"] = True
    data = app.test_client().get("/api/state").get_json()

    assert data["ultima_palavra"] == "OI"
    assert data["historico"] == ["OI"]
    assert engine.spoken == ["OI"]
