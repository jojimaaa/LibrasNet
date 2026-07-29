"""Bloco B4 — classificador de letras (k-NN sobre landmarks normalizados).

O k-NN ponderado por distância foi escolhido por ser leve o bastante para a
Raspberry Pi: a inferência é uma distância euclidiana sobre vetores de 42
floats, sem frameworks de aprendizado profundo, e o "treino" é instantâneo e
incremental com as amostras do próprio usuário (decisão arquitetural 3,
Seção 3.5). As amostras vêm de ``python -m libras.collect``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dataset import load_dataset, save_dataset
from .features import FEATURE_SIZE, normalize_landmarks


class NotFittedError(RuntimeError):
    """Classificador usado antes de receber amostras."""


@dataclass
class Prediction:
    label: str
    confidence: float


class KnnClassifier:
    """k-NN com votação ponderada pelo inverso da distância.

    A confiança combina duas evidências: a concordância dos k vizinhos e a
    **margem entre classes** — a razão d2/(d1+d2), onde d1 é a distância à
    amostra mais próxima da classe vencedora e d2 à mais próxima de qualquer
    outra classe. Um gesto-lixo fica equidistante de tudo (razão ≈ 0,5,
    confiança zerada); um gesto legítimo, mesmo deslocado da distribuição de
    treino (webcam ≠ fotos do dataset), continua bem mais perto da classe
    certa (razão alta). A razão é invariante a deslocamentos uniformes, ao
    contrário de limiares de distância absoluta.
    """

    # Rampa da margem → fator de confiança: 0 até MARGIN_LO (lixo fica em
    # ~0,50), 1 a partir de MARGIN_HI. Calibrada no dataset real com jitter
    # sintético de webcam (σ=0,03–0,06): lixo aceito 0/100, quadros
    # legítimos confirmados 72–90%.
    MARGIN_LO = 0.52
    MARGIN_HI = 0.62

    def __init__(self, k: int = 5):
        self.k = k
        self._X: "np.ndarray | None" = None
        self._y: "list[str]" = []
        self._labels: "np.ndarray | None" = None

    # ------------------------------------------------------------- treino
    def fit(self, X, y) -> "KnnClassifier":
        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2 or X.shape[1] != FEATURE_SIZE:
            raise ValueError(
                f"X deve ter shape (n, {FEATURE_SIZE}); recebeu {X.shape}")
        if len(y) != len(X):
            raise ValueError("X e y têm tamanhos diferentes")
        self._X = X
        self._y = [str(label) for label in y]
        self._labels = np.array(self._y)
        return self

    @property
    def classes(self) -> "list[str]":
        return sorted(set(self._y))

    @property
    def n_samples(self) -> int:
        return 0 if self._X is None else len(self._X)

    # ---------------------------------------------------------- inferência
    def predict(self, features) -> Prediction:
        """Prediz a letra para um vetor de 42 características normalizadas.

        A confiança é a fração (ponderada) dos k vizinhos que vota na classe
        vencedora, atenuada pela margem entre classes — ela alimenta o
        limiar de confirmação da lógica temporal (B5).
        """
        if self._X is None or len(self._X) == 0:
            raise NotFittedError(
                "Nenhuma amostra carregada; colete dados com "
                "'python -m libras.collect'.")
        f = np.asarray(features, dtype=np.float32).reshape(-1)
        distances = np.linalg.norm(self._X - f, axis=1)
        k = min(self.k, len(distances))
        neighbors = np.argpartition(distances, k - 1)[:k]
        weights = 1.0 / (distances[neighbors] + 1e-6)
        votes: "dict[str, float]" = {}
        for idx, weight in zip(neighbors, weights):
            label = self._y[idx]
            votes[label] = votes.get(label, 0.0) + float(weight)
        best = max(votes, key=votes.get)
        confidence = min(1.0, max(0.0, votes[best] / float(weights.sum())))
        # Rejeição open-set por margem entre classes (ver docstring da
        # classe). Com uma única classe no dataset não há margem a medir.
        winner_mask = self._labels == best
        if not winner_mask.all():
            d1 = float(distances[winner_mask].min())
            d2 = float(distances[~winner_mask].min())
            ratio = d2 / (d1 + d2 + 1e-9)
            factor = ((ratio - self.MARGIN_LO)
                      / (self.MARGIN_HI - self.MARGIN_LO))
            confidence *= min(1.0, max(0.0, factor))
        return Prediction(label=best, confidence=confidence)

    def predict_landmarks(self, landmarks) -> Prediction:
        """Atalho: normaliza os landmarks brutos e prediz."""
        return self.predict(normalize_landmarks(landmarks))

    # -------------------------------------------------------- persistência
    def save(self, path) -> None:
        if self._X is None:
            raise NotFittedError("nada para salvar")
        save_dataset(path, self._X, self._y)

    @classmethod
    def load(cls, path, k: int = 5) -> "KnnClassifier":
        X, y = load_dataset(path)
        return cls(k=k).fit(X, y)
