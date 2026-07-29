"""Bloco B1 — captura de vídeo (webcam USB via OpenCV/V4L2).

O contrato ``FrameSource`` desacopla o pipeline do hardware: em produção a
fonte é a webcam (``CameraSource``); em desenvolvimento e nos testes usa-se
uma fonte sintética (``SyntheticSource``), que dispensa câmera e OpenCV
(RNF-07).
"""
from __future__ import annotations

import logging
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
