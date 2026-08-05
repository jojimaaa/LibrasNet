"""Bloco B1 — captura de vídeo (webcam USB via OpenCV/V4L2).

O contrato ``FrameSource`` desacopla o pipeline do hardware: em produção a
fonte é a webcam (``CameraSource``); em desenvolvimento e nos testes usa-se
uma fonte sintética (``SyntheticSource``), que dispensa câmera e OpenCV
(RNF-07).
"""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

import numpy as np

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """Falha ao abrir ou operar a webcam."""


class FrameSource(ABC):
    """Fonte de quadros BGR (contrato do estágio de captura)."""

    @abstractmethod
    def read(self) -> "np.ndarray | None":
        """Retorna o próximo quadro BGR (H, W, 3) uint8, ou None ao terminar."""

    def release(self) -> None:
        """Libera recursos do dispositivo (padrão: nada a fazer)."""


class CameraSource(FrameSource):
    """Webcam real via OpenCV (driver V4L2 no Linux; DirectShow no Windows)."""

    # Leituras falhas transitórias (timeout do V4L2, quadro corrompido sob
    # CPU saturada) não significam fim da fonte; em um dispositivo de uso
    # contínuo, só desistimos após uma sequência longa de falhas (RNF-06).
    MAX_CONSECUTIVE_FAILURES = 30
    RETRY_DELAY_S = 0.05

    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        try:
            import cv2
        except ImportError as exc:
            raise CameraError(
                "OpenCV (cv2) não está instalado; instale o extra "
                "'hardware' (uv sync --extra hardware)."
            ) from exc
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            self._cap.release()
            raise CameraError(
                f"Não foi possível abrir a câmera de índice {index}.")
        # MJPG antes da resolução: em webcam USB o formato bruto (YUYV) satura
        # o barramento e o driver responde baixando a taxa de quadros. Quando a
        # câmera não suporta MJPG o set falha silenciosamente e segue em YUYV.
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        # Fila de 1 quadro: sem isso o driver acumula quadros e read() devolve
        # imagem velha, somando latência ao pipeline sob CPU saturada.
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        actual = (int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                  int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.resolution = actual
        if actual != (width, height):
            # Nem todo driver aceita a resolução pedida. Avisar importa: uma
            # câmera presa em 1920x1080 encarece captura e redimensionamento
            # sem que nada denuncie a causa.
            log.warning("câmera abriu em %dx%d (pedido: %dx%d)",
                        actual[0], actual[1], width, height)

    def read(self):
        failures = 0
        while True:
            ok, frame = self._cap.read()
            if ok:
                return frame
            failures += 1
            if failures >= self.MAX_CONSECUTIVE_FAILURES:
                return None
            time.sleep(self.RETRY_DELAY_S)

    def release(self):
        self._cap.release()


class ThreadedFrameSource(FrameSource):
    """Envolve uma fonte, lendo-a numa thread própria: entrega o quadro mais
    recente e descarta os atrasados.

    Sem isso, ``cap.read()`` bloqueia dentro do laço do pipeline esperando o
    V4L2, e o tempo de captura soma ao de inferência. Pior: quando o pipeline
    é mais lento que a câmera, a fila do driver acumula e o quadro processado
    já está velho — a tradução responde a um gesto que passou. Drenando a
    fonte numa thread, o pipeline sempre pega o quadro atual e a latência
    volta a ser de um quadro.

    ``dropped`` conta os quadros capturados que o pipeline nunca viu: é a
    medida direta da distância entre a taxa da câmera e a do pipeline.
    """

    def __init__(self, source: FrameSource, stale_timeout_s: float = 2.0):
        self.source = source
        self.stale_timeout_s = stale_timeout_s
        self.dropped = 0
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self._delivered = 0
        self._ended = False
        self._new_frame = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="captura")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            frame = self.source.read()
            with self._lock:
                if frame is None:
                    self._ended = True
                    self._new_frame.set()
                    return
                if self._seq > self._delivered:
                    # o quadro anterior não chegou a ser processado
                    self.dropped += 1
                self._frame = frame
                self._seq += 1
            self._new_frame.set()

    def read(self):
        while True:
            with self._lock:
                if self._seq > self._delivered:
                    self._delivered = self._seq
                    return self._frame
                if self._ended:
                    return None
                self._new_frame.clear()
            if not self._new_frame.wait(self.stale_timeout_s):
                log.warning("nenhum quadro novo em %.1fs; repetindo o último",
                            self.stale_timeout_s)
                with self._lock:
                    return self._frame

    def release(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self.stale_timeout_s + 1)
        self.source.release()


class SyntheticSource(FrameSource):
    """Fonte sintética para o modo demonstração e para os testes.

    Gera quadros BGR determinísticos com um gradiente animado, permitindo
    exercitar o pipeline completo sem webcam nem OpenCV instalados.
    """

    def __init__(self, width: int = 640, height: int = 480,
                 max_frames: "int | None" = None):
        self.width = width
        self.height = height
        self.max_frames = max_frames
        self._i = 0
        gx, gy = np.meshgrid(
            np.linspace(0, 255, width, dtype=np.float32),
            np.linspace(0, 255, height, dtype=np.float32),
        )
        self._gx, self._gy = gx, gy

    def read(self):
        if self.max_frames is not None and self._i >= self.max_frames:
            return None
        phase = (self._i * 7) % 256
        frame = np.empty((self.height, self.width, 3), dtype=np.uint8)
        frame[..., 0] = ((self._gx + phase) % 256).astype(np.uint8)
        frame[..., 1] = ((self._gy + phase) % 256).astype(np.uint8)
        frame[..., 2] = np.uint8(phase)
        self._i += 1
        return frame
