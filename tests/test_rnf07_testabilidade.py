"""RNF-07 — Testabilidade sem hardware (e integração B1 → B5).

Critério de verificação do documento de requisitos: "Suíte completa
executada em ambiente sem câmera." Aqui se verifica que (a) nenhuma
dependência de hardware é exigida no import do pacote e (b) o núcleo
completo do pipeline atravessa os cinco blocos com as fontes sintéticas.
"""
import ast
from pathlib import Path

import pytest

import libras
from libras.demo import make_demo_components
from libras.pipeline import STAGES, PipelineState, TranslationPipeline

PACKAGE_DIR = Path(libras.__file__).resolve().parent
HARDWARE_DEPS = {"cv2", "mediapipe", "pyttsx3"}


def module_level_imports(tree: ast.Module) -> set:
    """Nomes importados no nível do módulo (fora de funções/métodos)."""
    found = set()

    def visit(stmts):
        for node in stmts:
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                visit(node.orelse)
                visit(node.finalbody)
                for handler in node.handlers:
                    visit(handler.body)

    visit(tree.body)
    return found


def test_sem_dependencia_rigida_de_hardware_no_import():
    """cv2/mediapipe/pyttsx3 devem ser importados tardiamente (dentro de
    funções), para o sistema degradar graciosamente onde eles não existem."""
    for source_file in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        rigid = module_level_imports(tree) & HARDWARE_DEPS
        assert not rigid, (
            f"{source_file.name} importa {rigid} no nível do módulo")


def test_pipeline_completo_roda_sem_hardware(fast_config):
    """O núcleo inteiro (B1 → B5) funciona sem webcam/OpenCV/MediaPipe."""
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier,
                                   fast_config, state=PipelineState())
    for _ in range(20):
        assert pipeline.step()


def test_estado_do_pipeline_reflete_os_cinco_blocos(fast_config):
    source, extractor, classifier = make_demo_components(fast_config)
    state = PipelineState()
    pipeline = TranslationPipeline(source, extractor, classifier,
                                   fast_config, state=state)
    for _ in range(30):
        assert pipeline.step()

    snapshot = state.to_dict()
    assert snapshot["quadros_processados"] == 30       # B1 recepção
    assert snapshot["fps"] > 0
    assert set(snapshot["latencia_ms"]) == set(STAGES)  # B2, B3, B4
    for key in ("letra_atual", "confianca", "mao_presente",
                "palavra_parcial", "historico"):
        assert key in snapshot                        # B5
    frame = pipeline.latest_frame()                   # quadro exibível
    assert frame is not None
    assert frame.shape == (fast_config.frame_height,
                           fast_config.frame_width, 3)


def test_pipeline_termina_quando_a_fonte_esgota(fast_config):
    from libras.capture import SyntheticSource

    _, extractor, classifier = make_demo_components(fast_config)
    source = SyntheticSource(fast_config.frame_width,
                             fast_config.frame_height, max_frames=5)
    pipeline = TranslationPipeline(source, extractor, classifier,
                                   fast_config, state=PipelineState())
    assert sum(1 for _ in iter(pipeline.step, False)) == 5


def test_pipeline_exige_classificador_treinado(fast_config):
    from libras.capture import SyntheticSource
    from libras.classifier import KnnClassifier
    from libras.landmarks import NullExtractor

    with pytest.raises(ValueError, match="amostras"):
        TranslationPipeline(SyntheticSource(64, 48), NullExtractor(),
                            KnnClassifier(), fast_config)


def test_palavras_produzidas_somente_a_partir_de_gestos(fast_config):
    """RNF-01/RF-04 no pipeline real: entrada só de gestos, saída em texto."""
    source, extractor, classifier = make_demo_components(
        fast_config, text="OI MUNDO", loop=False)
    state = PipelineState()
    spoken = []
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=state, on_word=spoken.append)
    for _ in range(600):
        pipeline.step()
        if len(state.to_dict()["historico"]) >= 2:
            break

    assert state.to_dict()["historico"] == ["OI", "MUNDO"]
    assert spoken == ["OI", "MUNDO"]
