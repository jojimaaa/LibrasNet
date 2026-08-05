"""Configuração central do tradutor, agrupada pelos blocos do diagrama.

Os valores padrão foram escolhidos para a plataforma-alvo (Raspberry Pi 4
com webcam USB), conforme as metas do RNF-02.
"""
from __future__ import annotations

import platform
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = PROJECT_ROOT / "data" / "dataset.csv"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
MODEL_PATH = PROJECT_ROOT / "data" / "hand_landmarker.task"

ARM_MACHINES = {"aarch64", "armv7l", "armv6l", "arm64"}


def default_process_width() -> int:
    """224 px em ARM (Raspberry Pi), 320 px em máquina de mesa.

    O detector de palma do MediaPipe custa aproximadamente com a área do
    quadro: 320→224 corta ~50% dos pixels. Os landmarks saem normalizados em
    [0, 1], então o dataset e o classificador não percebem a diferença.
    """
    return 224 if platform.machine().lower() in ARM_MACHINES else 320


@dataclass
class Config:
    # B1 — captura de vídeo
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    target_fps: float = 30.0
    threaded_capture: bool = True

    # B2 — pré-processamento
    process_width: int = field(default_factory=default_process_width)

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
    vote_window_s: float = 0.40
    min_vote_ratio: float = 0.67   # fração da janela exigida para confirmar
    release_s: float = 0.20
    word_pause_s: float = 1.0

    # B6 — servidor de aplicação
    host: str = "0.0.0.0"
    port: int = 8001

    video_stream_fps: float = 10.0
    video_stream_width: int = 320
    video_jpeg_quality: int = 60

    monitor_interval: float = 1.0  # s entre amostras de CPU/RAM/clock/temp
    cpi_interval: float = 5.0

    def tuned_for_fps(self, fps: float) -> "Config":
        """Recalcula as janelas de B5 para a taxa de quadros informada.

        A 30 fps devolve exatamente os valores padrão em quadros; abaixo
        disso, encurta as janelas para preservar o tempo de resposta.
        """
        if fps <= 0:
            return replace(self)
        window = max(3, round(self.vote_window_s * fps))
        return replace(
            self,
            window_size=window,
            min_votes=max(2, min(window, round(window * self.min_vote_ratio))),
            release_frames=max(1, round(self.release_s * fps)),
            word_pause_frames=max(2, round(self.word_pause_s * fps)),
        )

    def confirmation_latency_ms(self, fps: float) -> float:
        """Tempo até uma letra estável ser confirmada, na taxa informada."""
        if fps <= 0:
            return float("inf")
        return self.min_votes / fps * 1000.0
