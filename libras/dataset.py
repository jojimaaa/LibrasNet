"""RF-06 — persistência do dataset de gestos (CSV: rótulo + 42 floats).

O formato é deliberadamente trivial: uma linha por amostra, legível a olho
nu e versionável. O dataset é o próprio "modelo" do k-NN — não há etapa de
treino offline (decisão arquitetural 3, Seção 3.5).
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from .features import FEATURE_SIZE

HEADER = ["label"] + [f"f{i}" for i in range(FEATURE_SIZE)]


def load_dataset(path) -> "tuple[np.ndarray, list[str]]":
    """Lê o CSV de amostras (rótulo + 42 floats por linha)."""
    path = Path(path)
    X, y = [], []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # cabeçalho
        for row in reader:
            if not row:
                continue
            y.append(row[0])
            X.append([float(v) for v in row[1:]])
    if not X:
        raise ValueError(f"dataset vazio: {path}")
    X = np.asarray(X, dtype=np.float32)
    if X.shape[1] != FEATURE_SIZE:
        raise ValueError(
            f"dataset com {X.shape[1]} características por amostra; "
            f"esperado {FEATURE_SIZE} ({path})")
    return X, y


def append_samples(path, label: str, samples) -> None:
    """Anexa amostras ao CSV, criando-o (com cabeçalho) se preciso.

    Anexar em vez de reescrever mantém a coleta incremental: uma rajada de
    letra interrompida não perde o que já foi gravado.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(HEADER)
        for sample in samples:
            row = np.asarray(sample, dtype=np.float32).reshape(-1)
            writer.writerow([label] + [f"{v:.6f}" for v in row])


def save_dataset(path, X, y) -> None:
    """Reescreve o CSV inteiro a partir de (X, y)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for label, row in zip(y, X):
            writer.writerow([label] + [f"{v:.6f}" for v in row])
