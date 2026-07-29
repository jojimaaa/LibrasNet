"""RF-03 — Reconhecimento de sinais (blocos B3 e B4).

Critério de aceitação do documento de requisitos: "Apresentado o alfabeto
inteiro quadro a quadro (com ruído), as letras são confirmadas na ordem
esperada."

Aqui se verifica a identificação de cada letra com confiança associada; a
confirmação ao longo do tempo é do RF-04.
"""
import numpy as np
import pytest

from libras.classifier import KnnClassifier, NotFittedError
from libras.demo import ALPHABET
from libras.features import FEATURE_SIZE, normalize_landmarks
from libras.landmarks import (
    NUM_LANDMARKS,
    HandDetection,
    NullExtractor,
    ScriptedExtractor,
)


# ------------------------------------------------- B3 extração de landmarks
def test_extrator_roteirizado_reproduz_a_sequencia():
    detection = HandDetection(
        landmarks=np.zeros((NUM_LANDMARKS, 2), dtype=np.float32))
    extractor = ScriptedExtractor([detection, None, detection])
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert [extractor.extract(frame) for _ in range(4)] == \
        [detection, None, detection, None]


def test_extrator_roteirizado_em_laco_nao_esgota():
    detection = HandDetection(
        landmarks=np.zeros((NUM_LANDMARKS, 2), dtype=np.float32))
    extractor = ScriptedExtractor([detection], loop=True)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    assert all(extractor.extract(frame) is detection for _ in range(10))


def test_extrator_nulo_degrada_sem_mao():
    """RNF-06: sem MediaPipe/modelo o sistema segue rodando, sem detectar."""
    extractor = NullExtractor()
    assert extractor.extract(np.zeros((4, 4, 3), dtype=np.uint8)) is None
    extractor.close()


def test_normalizacao_produz_vetor_de_42_caracteristicas():
    rng = np.random.default_rng(0)
    landmarks = rng.uniform(0.2, 0.8, (NUM_LANDMARKS, 2)).astype(np.float32)
    features = normalize_landmarks(landmarks)
    assert features.shape == (FEATURE_SIZE,)
    assert features.dtype == np.float32


# ------------------------------------------------------- B4 classificador
def test_alfabeto_inteiro_reconhecido(trained_classifier, synthetic_dataset):
    _, _, prototypes = synthetic_dataset
    rng = np.random.default_rng(123)
    recognized = []
    for letter in ALPHABET:
        noise = rng.normal(0, 0.01, (NUM_LANDMARKS, 2)).astype(np.float32)
        sample = prototypes[letter] + noise
        prediction = trained_classifier.predict(normalize_landmarks(sample))
        recognized.append(prediction.label)
    assert recognized == list(ALPHABET)


def test_invariancia_a_posicao_e_distancia_da_camera(trained_classifier,
                                                     synthetic_dataset):
    """O mesmo gesto, com a mão menor e deslocada no quadro, é a mesma letra."""
    _, _, prototypes = synthetic_dataset
    transformed = prototypes["A"] * 0.4 + np.float32([0.3, -0.2])
    prediction = trained_classifier.predict(normalize_landmarks(transformed))
    assert prediction.label == "A"


def test_invariancia_a_inclinacao_da_mao(trained_classifier,
                                        synthetic_dataset):
    """O mesmo gesto com a mão inclinada (rotação no plano) é a mesma letra."""
    _, _, prototypes = synthetic_dataset
    proto = prototypes["B"]
    theta = np.deg2rad(35.0)
    c, s = np.cos(theta), np.sin(theta)
    rotation = np.array([[c, -s], [s, c]], dtype=np.float32)
    rotated = (proto - proto[0]) @ rotation.T + proto[0]
    prediction = trained_classifier.predict(normalize_landmarks(rotated))
    assert prediction.label == "B"


def test_invariancia_a_mao_espelhada(trained_classifier, synthetic_dataset):
    """Mão esquerda (ou câmera espelhada) produz a mesma letra."""
    _, _, prototypes = synthetic_dataset
    mirrored = prototypes["C"].copy()
    mirrored[:, 0] = 1.0 - mirrored[:, 0]
    prediction = trained_classifier.predict(normalize_landmarks(mirrored))
    assert prediction.label == "C"


def test_confianca_alta_para_amostra_limpa(trained_classifier,
                                           synthetic_dataset):
    _, _, prototypes = synthetic_dataset
    prediction = trained_classifier.predict(
        normalize_landmarks(prototypes["M"]))
    assert prediction.label == "M"
    assert 0.9 <= prediction.confidence <= 1.0


def test_gesto_desconhecido_recebe_confianca_reduzida(trained_classifier):
    """Gesto longe de tudo que foi treinado não pode ter confiança alta
    (rejeição open-set), mesmo que os vizinhos concordem entre si."""
    rng = np.random.default_rng(99)
    unknown = rng.uniform(-3.0, 3.0, size=FEATURE_SIZE).astype(np.float32)
    prediction = trained_classifier.predict(unknown)
    assert prediction.confidence < 0.65   # abaixo do limiar de confirmação


def test_gesto_com_ruido_de_webcam_ainda_confirma(trained_classifier,
                                                  synthetic_dataset):
    """A rejeição open-set não pode silenciar gestos legítimos com o jitter
    típico dos landmarks ao vivo (regressão: sistema mudo)."""
    _, _, prototypes = synthetic_dataset
    rng = np.random.default_rng(7)
    confirmable = 0
    for letter, proto in prototypes.items():
        noise = rng.normal(0, 0.015, proto.shape).astype(np.float32)
        prediction = trained_classifier.predict(
            normalize_landmarks(proto + noise))
        if prediction.label == letter and prediction.confidence >= 0.65:
            confirmable += 1
    assert confirmable >= 24, f"só {confirmable}/26 letras confirmáveis"


def test_dataset_de_classe_unica_nao_quebra():
    """Coleta iniciada com uma única letra ainda funciona (sem margem entre
    classes para medir, a rejeição é ignorada)."""
    rng = np.random.default_rng(1)
    X = rng.normal(0, 0.1, (10, FEATURE_SIZE)).astype(np.float32)
    classifier = KnnClassifier(k=3).fit(X, ["A"] * 10)
    assert classifier.predict(X[0]).label == "A"


def test_classificador_sem_dataset_gera_erro_claro():
    with pytest.raises(NotFittedError):
        KnnClassifier().predict(np.zeros(FEATURE_SIZE, dtype=np.float32))


def test_classificador_rejeita_dimensao_errada():
    with pytest.raises(ValueError, match=str(FEATURE_SIZE)):
        KnnClassifier().fit(np.zeros((3, 10), dtype=np.float32), ["A"] * 3)


def test_classificador_rejeita_rotulos_desalinhados():
    X = np.zeros((3, FEATURE_SIZE), dtype=np.float32)
    with pytest.raises(ValueError):
        KnnClassifier().fit(X, ["A", "B"])


def test_predicao_direta_a_partir_dos_landmarks(trained_classifier,
                                                synthetic_dataset):
    """Atalho usado pelo pipeline: landmarks brutos → letra."""
    _, _, prototypes = synthetic_dataset
    prediction = trained_classifier.predict_landmarks(prototypes["Z"])
    assert prediction.label == "Z"
