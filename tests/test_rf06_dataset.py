"""RF-06 — Construção do dataset de gestos (modo de coleta).

Critério de aceitação do documento de requisitos: "Amostras
coletadas/importadas são persistidas no dataset e passam a ser reconhecidas
pelo classificador."

O laço de vídeo da coleta (OpenCV) é apenas a casca: o núcleo é
``CollectSession``, exercitado aqui sem câmera (RNF-07).
"""
import numpy as np
import pytest

from libras.collect import CollectSession
from libras.dataset import append_samples, load_dataset
from libras.features import FEATURE_SIZE, normalize_landmarks
from libras.landmarks import NUM_LANDMARKS


def make_landmarks(seed: int):
    rng = np.random.default_rng(seed)
    return rng.uniform(0.2, 0.8, (NUM_LANDMARKS, 2)).astype(np.float32)


# ------------------------------------------------------------ persistência
def test_amostras_persistidas_com_cabecalho(tmp_path):
    path = tmp_path / "dataset.csv"
    append_samples(path, "A", [np.zeros(FEATURE_SIZE, dtype=np.float32)])
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("label,f0,f1")
    assert len(lines) == 2
    assert lines[1].startswith("A,")


def test_amostras_anexadas_sem_repetir_cabecalho(tmp_path):
    path = tmp_path / "dataset.csv"
    sample = np.zeros(FEATURE_SIZE, dtype=np.float32)
    append_samples(path, "A", [sample, sample])
    append_samples(path, "B", [sample])
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4                       # cabeçalho + 3 amostras
    X, y = load_dataset(path)
    assert y == ["A", "A", "B"]
    assert X.shape == (3, FEATURE_SIZE)


def test_dataset_criado_em_diretorio_inexistente(tmp_path):
    path = tmp_path / "sub" / "dir" / "dataset.csv"
    append_samples(path, "A", [np.zeros(FEATURE_SIZE, dtype=np.float32)])
    assert path.exists()


def test_valores_preservados_na_ida_e_volta(tmp_path):
    path = tmp_path / "dataset.csv"
    features = normalize_landmarks(make_landmarks(3))
    append_samples(path, "Z", [features])
    X, y = load_dataset(path)
    assert y == ["Z"]
    assert np.allclose(X[0], features, atol=1e-6)


def test_dataset_vazio_gera_erro_claro(tmp_path):
    path = tmp_path / "dataset.csv"
    path.write_text("label,f0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="vazio"):
        load_dataset(path)


def test_dataset_com_numero_errado_de_caracteristicas_gera_erro(tmp_path):
    path = tmp_path / "dataset.csv"
    path.write_text("label,f0,f1\nA,0.1,0.2\n", encoding="utf-8")
    with pytest.raises(ValueError, match=str(FEATURE_SIZE)):
        load_dataset(path)


# --------------------------------------------------------- modo de coleta
def test_sem_rajada_ativa_nada_e_gravado(tmp_path):
    session = CollectSession(tmp_path / "dataset.csv", burst=5)
    assert session.feed(make_landmarks(1)) is False
    assert session.total == 0
    assert not (tmp_path / "dataset.csv").exists()


def test_rajada_grava_exatamente_o_numero_pedido(tmp_path):
    path = tmp_path / "dataset.csv"
    session = CollectSession(path, burst=3)
    assert session.start_burst("a") is True      # tecla minúscula vale
    assert session.label == "A"
    for _ in range(3):
        assert session.feed(make_landmarks(2)) is True
    assert session.recording is False
    assert session.feed(make_landmarks(2)) is False

    X, y = load_dataset(path)
    assert y == ["A"] * 3
    assert X.shape == (3, FEATURE_SIZE)
    assert session.total == 3
    assert session.counts["A"] == 3


def test_rajada_em_andamento_nao_e_substituida(tmp_path):
    session = CollectSession(tmp_path / "dataset.csv", burst=3)
    session.start_burst("A")
    session.feed(make_landmarks(1))
    assert session.start_burst("B") is False
    assert session.label == "A"


def test_rotulo_invalido_e_ignorado(tmp_path):
    session = CollectSession(tmp_path / "dataset.csv", burst=3)
    assert session.start_burst("1") is False
    assert session.start_burst("") is False
    assert session.recording is False


def test_fim_de_rajada_notificado_uma_vez(tmp_path):
    ended = []
    session = CollectSession(tmp_path / "dataset.csv", burst=2,
                             on_burst_end=ended.append)
    session.start_burst("C")
    session.feed(make_landmarks(1))
    assert ended == []
    session.feed(make_landmarks(2))
    assert ended == ["C"]


def test_sessao_retoma_a_contagem_de_um_dataset_existente(tmp_path):
    path = tmp_path / "dataset.csv"
    sample = np.zeros(FEATURE_SIZE, dtype=np.float32)
    append_samples(path, "A", [sample, sample])
    append_samples(path, "B", [sample])

    session = CollectSession(path, burst=2)
    assert session.total == 3
    assert session.letters == 2
    assert session.counts["A"] == 2


def test_teclas_do_teclado_mapeadas_para_letras():
    assert CollectSession.key_to_label(ord("a")) == "A"
    assert CollectSession.key_to_label(ord("Z")) == "Z"
    assert CollectSession.key_to_label(27) is None      # ESC
    assert CollectSession.key_to_label(255) is None     # nenhuma tecla


# ------------------------- critério de aceitação: coletar → reconhecer
def test_amostras_coletadas_sao_reconhecidas_pelo_classificador(tmp_path):
    """Coleta duas letras e verifica que o classificador treinado com o
    dataset resultante as reconhece."""
    from libras.classifier import KnnClassifier

    path = tmp_path / "dataset.csv"
    session = CollectSession(path, burst=8)
    prototypes = {"A": make_landmarks(11), "B": make_landmarks(22)}
    rng = np.random.default_rng(5)
    for letter, proto in prototypes.items():
        session.start_burst(letter)
        while session.recording:
            noise = rng.normal(0, 0.005, proto.shape).astype(np.float32)
            session.feed(proto + noise)

    classifier = KnnClassifier.load(path, k=3)
    assert classifier.n_samples == 16
    assert classifier.classes == ["A", "B"]
    for letter, proto in prototypes.items():
        assert classifier.predict_landmarks(proto).label == letter
