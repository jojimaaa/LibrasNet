"""RF-02 — Captura por webcam (blocos B1 e B2).

Critério de aceitação do documento de requisitos: "O caminho completo
recepção → processamento → quadro exibível é percorrido; índice de câmera
inválido produz erro tratado, não travamento."

A webcam física é substituída pela fonte sintética (RNF-07); o
pré-processamento exercitado é o de produção.
"""
import importlib.util

import numpy as np
import pytest

from libras.capture import CameraError, CameraSource, SyntheticSource
from libras.preprocess import bgr_to_rgb, preprocess, resize_width

CV2_AVAILABLE = importlib.util.find_spec("cv2") is not None


# --------------------------------------------------------------- B1 captura
def test_fonte_gera_quadros_bgr_validos():
    source = SyntheticSource(width=640, height=480)
    frames = [source.read() for _ in range(5)]
    for frame in frames:
        assert frame is not None
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8
    assert not np.array_equal(frames[0], frames[1]), \
        "quadros devem variar no tempo"


def test_fonte_finita_encerra_com_none():
    source = SyntheticSource(max_frames=3)
    assert all(source.read() is not None for _ in range(3))
    assert source.read() is None


def test_fonte_sintetica_e_determinista():
    """Determinismo é o que torna o modo demo e os testes reprodutíveis."""
    a = [SyntheticSource(width=64, height=48).read() for _ in range(1)]
    b = [SyntheticSource(width=64, height=48).read() for _ in range(1)]
    assert np.array_equal(a[0], b[0])


@pytest.mark.skipif(CV2_AVAILABLE,
                    reason="cv2 instalado; o cenário é a ausência do OpenCV")
def test_camera_sem_opencv_falha_com_mensagem_clara():
    with pytest.raises(CameraError, match="OpenCV"):
        CameraSource(0)


@pytest.mark.skipif(not CV2_AVAILABLE, reason="requer OpenCV instalado")
def test_camera_com_indice_invalido_falha_com_mensagem_clara():
    """Índice inválido: erro tratado, não travamento."""
    with pytest.raises(CameraError, match="câmera"):
        CameraSource(9999)


def test_falha_transitoria_de_leitura_nao_encerra_a_fonte(monkeypatch):
    """RNF-06: timeout do driver sob CPU saturada não pode derrubar o
    sistema — só uma sequência longa de falhas encerra a fonte."""
    class FakeCap:
        def __init__(self, failures_before_ok):
            self.remaining = failures_before_ok
            self.reads = 0

        def read(self):
            self.reads += 1
            if self.remaining > 0:
                self.remaining -= 1
                return False, None
            return True, np.zeros((4, 4, 3), dtype=np.uint8)

    monkeypatch.setattr(CameraSource, "RETRY_DELAY_S", 0.0)
    source = CameraSource.__new__(CameraSource)   # sem abrir hardware

    source._cap = FakeCap(failures_before_ok=3)
    assert source.read() is not None
    assert source._cap.reads == 4                # 3 falhas + 1 sucesso

    limit = CameraSource.MAX_CONSECUTIVE_FAILURES
    source._cap = FakeCap(failures_before_ok=limit)
    assert source.read() is None                 # desiste, sem travar
    assert source._cap.reads == limit


# -------------------------------------------------------- B2 pré-processamento
def test_preprocessamento_redimensiona_preservando_proporcao():
    frame = SyntheticSource(width=640, height=480).read()
    small = resize_width(frame, 320)
    assert small.shape == (240, 320, 3)


def test_redimensionamento_na_largura_alvo_nao_copia():
    """Quadro já na largura de destino não paga uma cópia por quadro."""
    frame = SyntheticSource(width=320, height=240).read()
    assert resize_width(frame, 320) is frame


def test_preprocessamento_converte_bgr_para_rgb():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[..., 0] = 10    # canal B
    frame[..., 2] = 200   # canal R
    rgb = bgr_to_rgb(frame)
    assert rgb[0, 0, 0] == 200 and rgb[0, 0, 2] == 10


def test_quadro_processado_e_contiguo():
    """O MediaPipe exige um buffer contíguo na entrada."""
    frame = SyntheticSource(width=640, height=480).read()
    rgb = preprocess(frame, 320)
    assert rgb.shape == (240, 320, 3)
    assert rgb.dtype == np.uint8
    assert rgb.flags["C_CONTIGUOUS"]


def test_recepcao_e_processamento_de_varios_quadros(fast_config):
    """Caminho recepção → processamento → quadro exibível, quadro a quadro."""
    source = SyntheticSource(fast_config.frame_width,
                             fast_config.frame_height, max_frames=30)
    processed = 0
    exibivel = None
    while True:
        frame = source.read()
        if frame is None:
            break
        rgb = preprocess(frame, fast_config.process_width)
        assert rgb.shape[1] == fast_config.process_width
        exibivel = frame            # quadro BGR entregue para exibição
        processed += 1
    assert processed == 30
    assert exibivel.shape == (fast_config.frame_height,
                              fast_config.frame_width, 3)
    source.release()
