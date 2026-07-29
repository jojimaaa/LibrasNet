"""Componentes sintéticos que exercitam o pipeline sem webcam, OpenCV ou
MediaPipe (RNF-07 e base do modo demonstração, RF-08).

A ideia é "soletrar" um texto: para cada letra existe um protótipo de mão
(21 landmarks) e um extrator roteirizado reproduz esses protótipos com
ruído, como se a câmera estivesse vendo os gestos. Todos os demais estágios
— classificação, votação temporal e montagem de palavras — são exatamente os
mesmos do modo real.
"""
from __future__ import annotations

import numpy as np

from .capture import SyntheticSource
from .classifier import KnnClassifier
from .config import Config
from .features import normalize_landmarks
from .landmarks import NUM_LANDMARKS, HandDetection, ScriptedExtractor

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def make_synthetic_dataset(samples_per_letter: int = 8, noise: float = 0.01,
                           seed: int = 42):
    """Dataset sintético determinístico: um protótipo de mão por letra.

    Valida a mecânica do classificador e alimenta o modo demo; não substitui
    a coleta de amostras reais (``python -m libras.collect``).

    Retorna ``(X, y, prototipos)``, com X de shape (26·samples, 42) e
    ``prototipos`` mapeando letra → landmarks brutos (21, 2).
    """
    rng = np.random.default_rng(seed)
    X, y = [], []
    prototypes: "dict[str, np.ndarray]" = {}
    for letter in ALPHABET:
        proto = rng.uniform(0.2, 0.8,
                            size=(NUM_LANDMARKS, 2)).astype(np.float32)
        prototypes[letter] = proto
        for _ in range(samples_per_letter):
            noisy = rng.normal(0.0, noise, proto.shape).astype(np.float32)
            X.append(normalize_landmarks(proto + noisy))
            y.append(letter)
    return np.asarray(X, dtype=np.float32), y, prototypes


def spell_sequence(text: str, prototypes: dict, hold_frames: int = 12,
                   gap_frames: int = 8, word_pause_frames: int = 35,
                   noise: float = 0.004, seed: int = 7):
    """Sequência de detecções (uma por quadro) que soletra ``text``.

    Cada letra é mantida por ``hold_frames`` quadros; entre letras há
    ``gap_frames`` quadros sem mão; ao fim de cada palavra,
    ``word_pause_frames`` quadros sem mão disparam o fim de palavra.
    """
    rng = np.random.default_rng(seed)
    sequence: "list[HandDetection | None]" = []
    for word in text.upper().split():
        for letter in word:
            proto = prototypes.get(letter)
            if proto is None:
                continue
            for _ in range(hold_frames):
                pts = (proto
                       + rng.normal(0.0, noise, proto.shape)).astype(np.float32)
                sequence.append(HandDetection(landmarks=pts, score=0.99))
            sequence.extend([None] * gap_frames)
        sequence.extend([None] * word_pause_frames)
    return sequence


def make_demo_components(config: Config, text: str = "LIBRAS USP",
                         loop: bool = True):
    """Monta ``(fonte, extrator, classificador)`` do modo demonstração.

    Os tempos de gesto derivam da própria configuração temporal, garantindo
    que a soletração sintética atravessa os filtros de confirmação.
    """
    X, y, prototypes = make_synthetic_dataset()
    classifier = KnnClassifier(k=config.knn_k).fit(X, y)
    sequence = spell_sequence(
        text, prototypes,
        hold_frames=config.min_votes + 4,
        gap_frames=config.release_frames + 2,
        word_pause_frames=config.word_pause_frames + 5,
    )
    extractor = ScriptedExtractor(sequence, loop=loop)
    source = SyntheticSource(config.frame_width, config.frame_height)
    return source, extractor, classifier
