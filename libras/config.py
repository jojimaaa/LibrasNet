"""Configuração central do tradutor, agrupada pelos blocos do diagrama.

Os valores padrão foram escolhidos para a plataforma-alvo (Raspberry Pi 4
com webcam USB), conforme as metas do RNF-02.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_ROOT / "data" / "dataset.csv"
# Modelo da API Tasks do MediaPipe (baixado por: python -m libras.get_model)
MODEL_PATH = PROJECT_ROOT / "data" / "hand_landmarker.task"


@dataclass
class Config:
    # B1 — captura de vídeo
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    target_fps: float = 30.0

    # B2 — pré-processamento
    process_width: int = 320

    # B3 — extração de landmarks
    # model_complexity do MediaPipe Hands: 0 = modelo "lite", 1 = completo.
    # O lite custa cerca de metade do tempo de inferência e é o padrão porque
    # o alvo é a Raspberry Pi (RNF-02). Em máquina de mesa, 1 dá landmarks um
    # pouco mais precisos — mas mude nos DOIS lados (coleta e execução),
    # senão o dataset é gerado com uma distribuição e consultado com outra.
    model_complexity: int = 0

    # B4 — classificador
    knn_k: int = 5

    # B5 — lógica temporal (votação em janela e montagem de palavras)
    min_confidence: float = 0.65   # limiar de confiança da predição
    window_size: int = 12          # tamanho da janela deslizante de votação
    min_votes: int = 8             # votos mínimos para confirmar uma letra
    release_frames: int = 6        # quadros sem mão p/ liberar letra repetida
    word_pause_frames: int = 30    # quadros sem mão que fecham a palavra
