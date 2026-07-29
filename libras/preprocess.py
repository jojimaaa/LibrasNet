"""Bloco B2 — pré-processamento: redimensiona e normaliza cada quadro.

Reduz a resolução (menos custo nos estágios seguintes) e converte BGR→RGB,
o formato de entrada esperado pelo MediaPipe Hands.
"""
from __future__ import annotations

import numpy as np


def resize_width(frame: np.ndarray, target_width: int) -> np.ndarray:
    """Redimensiona preservando a proporção.

    Usa OpenCV quando disponível; sem ele, cai em vizinho-mais-próximo puro
    numpy — suficiente para o modo demo e para os testes.
    """
    h, w = frame.shape[:2]
    if w == target_width:
        return frame
    target_height = max(1, round(h * target_width / w))
    try:
        import cv2
        return cv2.resize(frame, (target_width, target_height),
                          interpolation=cv2.INTER_AREA)
    except ImportError:
        ys = (np.arange(target_height) * h // target_height).clip(0, h - 1)
        xs = (np.arange(target_width) * w // target_width).clip(0, w - 1)
        return frame[ys][:, xs]


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    """Converte BGR→RGB devolvendo um array contíguo.

    Com OpenCV usa ``cvtColor`` (vetorizado em SIMD); sem ele, a inversão de
    canais por fatia produz um array de passo negativo, que precisa de uma
    cópia explícita — bem mais caro, mas só ocorre no modo demo/testes.
    """
    try:
        import cv2
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except ImportError:
        return np.ascontiguousarray(frame[..., ::-1])


def preprocess(frame: np.ndarray, target_width: int) -> np.ndarray:
    """Estágio completo: redimensiona e converte BGR→RGB (array contíguo)."""
    return bgr_to_rgb(resize_width(frame, target_width))
