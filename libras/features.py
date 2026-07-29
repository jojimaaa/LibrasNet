"""Normalização geométrica dos landmarks — a entrada do classificador.

Trabalhar sobre 21 coordenadas normalizadas (em vez da imagem completa)
reduz a dimensionalidade e torna o reconhecimento pouco sensível a fundo,
posição e distância da câmera (decisão arquitetural 2, Seção 3.5).
"""
from __future__ import annotations

import numpy as np

FEATURE_SIZE = 42  # 21 pontos × (x, y)


def normalize_landmarks(landmarks) -> np.ndarray:
    """Reduz a mão a uma pose canônica antes da classificação.

    Quatro invariâncias, nesta ordem:

    1. **posição** — o punho (ponto 0) vai para a origem;
    2. **rotação** — a mão gira até o vetor punho → base do dedo médio
       (ponto 9) apontar para o eixo +y: inclinar a mão não muda o sinal;
    3. **espelhamento** — se a base do polegar (ponto 2) ficar à esquerda
       da base do mínimo (ponto 17), a mão é espelhada: mão esquerda,
       direita ou câmera espelhada produzem o mesmo vetor;
    4. **escala** — divisão pela maior distância ao punho: a distância da
       câmera não muda o sinal.

    Nas letras estáticas do alfabeto o que distingue os sinais é a
    configuração dos dedos, então as invariâncias acima removem variação
    espúria sem colapsar classes.
    """
    pts = np.asarray(landmarks, dtype=np.float32)[:, :2].copy()
    pts -= pts[0]

    reference = pts[9]  # base do dedo médio
    norm = float(np.hypot(reference[0], reference[1]))
    if norm > 1e-9:
        alpha = np.arctan2(reference[1], reference[0])
        phi = np.pi / 2 - alpha
        c, s = np.cos(phi), np.sin(phi)
        rotation = np.array([[c, -s], [s, c]], dtype=np.float32)
        pts = pts @ rotation.T

    if pts[2, 0] < pts[17, 0]:  # juntas que não se cruzam anatomicamente
        pts[:, 0] = -pts[:, 0]

    scale = float(np.max(np.linalg.norm(pts, axis=1)))
    if scale > 1e-9:
        pts /= scale
    return pts.reshape(-1)
