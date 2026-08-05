"""Configuração central do tradutor, agrupada pelos blocos do diagrama.

Os valores padrão foram escolhidos para a plataforma-alvo (Raspberry Pi 4
com webcam USB), conforme as metas do RNF-02.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_ROOT / "data" / "dataset.csv"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
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
    model_complexity: int = 0

    # B4 — classificador
    knn_k: int = 5

    # B5 — lógica temporal (votação em janela e montagem de palavras)
    min_confidence: float = 0.65   # limiar de confiança da predição
    window_size: int = 12          # tamanho da janela deslizante de votação
    min_votes: int = 8             # votos mínimos para confirmar uma letra
    release_frames: int = 6        # quadros sem mão p/ liberar letra repetida
    word_pause_frames: int = 30    # quadros sem mão que fecham a palavra

    # B6 — servidor de aplicação
    host: str = "0.0.0.0"
    port: int = 8001

    video_stream_fps: float = 10.0
    video_stream_width: int = 320
    video_jpeg_quality: int = 60

    monitor_interval: float = 1.0  # s entre amostras de CPU/RAM/clock/temp
    cpi_interval: float = 5.0
