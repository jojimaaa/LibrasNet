"""Bloco B3 — extração de landmarks da mão.

Em produção usa o MediaPipe Hands (ZHANG et al., 2020): 21 pontos de
referência a partir de uma única câmera RGB. O contrato
``LandmarkExtractor`` permite substituir o extrator por versões roteirizadas
nos testes e no modo demonstração, sem alterar os demais estágios (RNF-07).

Depois deste bloco o problema deixa de ser de visão computacional e passa a
ser de classificação geométrica de baixa dimensionalidade (Seção 3.4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

NUM_LANDMARKS = 21


@dataclass
class HandDetection:
    """Resultado da extração: 21 pontos (x, y) normalizados em [0, 1]."""

    landmarks: np.ndarray          # shape (21, 2) ou (21, 3), float32
    score: float = 1.0
    handedness: str = "Right"


class LandmarkExtractor(ABC):
    @abstractmethod
    def extract(self, rgb: np.ndarray) -> "HandDetection | None":
        """Extrai a mão do quadro RGB; None quando não há mão no quadro."""

    def close(self) -> None:
        """Libera recursos do modelo (padrão: nada a fazer)."""


class MediaPipeExtractor(LandmarkExtractor):
    """Extrator real usando MediaPipe Hands.

    Suporta as duas gerações da API do MediaPipe:

    - **legada** (``mediapipe`` <= 0.10.30): ``mp.solutions.hands``;
    - **Tasks** (``mediapipe`` >= 0.10.31, que removeu ``mp.solutions``):
      ``HandLandmarker``, que exige o arquivo de modelo
      ``data/hand_landmarker.task`` — baixe uma única vez com
      ``python -m libras.get_model``.

    ``static=True`` otimiza para imagens avulsas; ``static=False`` (padrão)
    usa rastreamento entre quadros de vídeo.

    ``model_complexity`` (só na API legada) escolhe entre o modelo lite (0,
    padrão — cerca de metade do tempo de inferência, o que decide o FPS na
    Raspberry Pi) e o completo (1). A API Tasks não tem esse parâmetro: quem
    define a complexidade é o arquivo ``.task`` carregado.
    """

    def __init__(self, max_hands: int = 1, det_conf: float = 0.6,
                 track_conf: float = 0.5, static: bool = False,
                 model_path=None, model_complexity: int = 0):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError(
                "mediapipe não está instalado; instale o extra 'hardware' "
                "(uv sync --extra hardware)."
            ) from exc
        self._mp = mp
        self._static = static
        if hasattr(mp, "solutions"):
            self._api = "solutions"
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=static,
                max_num_hands=max_hands,
                model_complexity=model_complexity,
                min_detection_confidence=det_conf,
                min_tracking_confidence=track_conf,
            )
        else:
            self._api = "tasks"
            self._init_tasks_api(mp, max_hands, det_conf, track_conf,
                                 model_path)

    def _init_tasks_api(self, mp, max_hands, det_conf, track_conf,
                        model_path):
        from pathlib import Path

        from mediapipe.tasks.python import vision

        from .config import MODEL_PATH

        model = Path(model_path) if model_path else MODEL_PATH
        if not model.exists():
            raise RuntimeError(
                f"Modelo do MediaPipe não encontrado em {model}.\n"
                "Baixe-o uma única vez com:  python -m libras.get_model")
        mode = (vision.RunningMode.IMAGE if self._static
                else vision.RunningMode.VIDEO)
        options = vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
            running_mode=mode,
            num_hands=max_hands,
            min_hand_detection_confidence=det_conf,
            min_tracking_confidence=track_conf,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._timestamp_ms = 0

    # ------------------------------------------------------------- extração
    def extract(self, rgb):
        if self._api == "solutions":
            return self._extract_solutions(rgb)
        return self._extract_tasks(rgb)

    def _extract_solutions(self, rgb):
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return None
        hand = result.multi_hand_landmarks[0]
        pts = np.array([[p.x, p.y] for p in hand.landmark], dtype=np.float32)
        score, handedness = 1.0, "Right"
        if result.multi_handedness:
            cls = result.multi_handedness[0].classification[0]
            score, handedness = float(cls.score), cls.label
        return HandDetection(landmarks=pts, score=score,
                             handedness=handedness)

    def _extract_tasks(self, rgb):
        mp = self._mp
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        if self._static:
            result = self._landmarker.detect(image)
        else:
            # O modo VIDEO exige timestamps estritamente crescentes.
            self._timestamp_ms += 33
            result = self._landmarker.detect_for_video(image,
                                                       self._timestamp_ms)
        hands = getattr(result, "hand_landmarks", None)
        if not hands:
            return None
        pts = np.array([[p.x, p.y] for p in hands[0]], dtype=np.float32)
        score, handedness = 1.0, "Right"
        categories = getattr(result, "handedness", None)
        if categories and categories[0]:
            category = categories[0][0]
            score = float(getattr(category, "score", 1.0))
            handedness = getattr(category, "category_name", "Right") or "Right"
        return HandDetection(landmarks=pts, score=score,
                             handedness=handedness)

    def close(self):
        if self._api == "solutions":
            self._hands.close()
        else:
            self._landmarker.close()


class NullExtractor(LandmarkExtractor):
    """Nunca detecta mão — degradação graciosa sem hardware/modelo (RNF-06)."""

    def extract(self, rgb):
        return None


class ScriptedExtractor(LandmarkExtractor):
    """Reproduz uma sequência pré-definida de detecções (demo e testes).

    A sequência contém um item por quadro: ``HandDetection`` quando há mão,
    ``None`` quando não há. Com ``loop=True`` a sequência recomeça ao fim.
    """

    def __init__(self, sequence, loop: bool = False):
        self._seq = list(sequence)
        self._loop = loop
        self._i = 0

    def extract(self, rgb):
        if self._i >= len(self._seq):
            if not self._loop or not self._seq:
                return None
            self._i = 0
        detection = self._seq[self._i]
        self._i += 1
        return detection
