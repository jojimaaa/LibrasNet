"""Orquestração do pipeline de dutos e filtros (Seção 3.1 da documentação).

Cada quadro atravessa os estágios B1 → B5: captura, pré-processamento,
extração de landmarks, classificação e lógica temporal. O resultado fica em
``PipelineState``, que nas entregas seguintes é o que o servidor de aplicação
(B6) publica para o frontend. A latência de cada estágio é medida na
fronteira entre filtros — é assim que o gargalo fica localizado, e não apenas
indicado (Seção 3.1, consequência 2).
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .classifier import KnnClassifier
from .config import Config
from .features import normalize_landmarks
from .preprocess import preprocess
from .temporal import LetterConfirmer, WordAssembler

STAGES = ("captura", "preprocessamento", "landmarks", "classificacao")


class PipelineState:
    """Estado compartilhado (thread-safe) do pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {
            "letra_atual": None,
            "confianca": None,
            "mao_presente": False,
            "palavra_parcial": "",
            "ultima_palavra": None,
            "historico": [],
            "fps": 0.0,
            "quadros_processados": 0,
            "latencia_ms": {},
        }

    def update(self, **fields) -> None:
        with self._lock:
            self._data.update(fields)

    def add_word(self, word: str) -> None:
        with self._lock:
            self._data["ultima_palavra"] = word
            self._data["historico"] = self._data["historico"] + [word]

    def to_dict(self) -> dict:
        with self._lock:
            data = dict(self._data)
            data["historico"] = list(data["historico"])
            data["latencia_ms"] = dict(data["latencia_ms"])
            return data


class TranslationPipeline:
    """Executa os estágios do pipeline sobre cada quadro capturado."""

    def __init__(self, source, extractor, classifier: KnnClassifier,
                 config: Config, state: "PipelineState | None" = None,
                 on_letter=None, on_word=None):
        if classifier.n_samples == 0:
            raise ValueError(
                "O classificador precisa de amostras (dataset vazio); "
                "colete dados com 'python -m libras.collect'.")
        self.source = source
        self.extractor = extractor
        self.classifier = classifier
        self.config = config
        self.state = state or PipelineState()
        self.on_letter = on_letter
        self.on_word = on_word
        self.confirmer = LetterConfirmer(
            min_confidence=config.min_confidence,
            window_size=config.window_size,
            min_votes=config.min_votes,
            release_frames=config.release_frames,
        )
        self.assembler = WordAssembler(
            word_pause_frames=config.word_pause_frames)
        self._stage_times = {name: deque(maxlen=120) for name in STAGES}
        self._frame_stamps = deque(maxlen=90)
        self._frames = 0
        self._latest_frame = None  # último quadro BGR, para exibição
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    # ------------------------------------------------------------- 1 quadro
    def step(self) -> bool:
        """Processa um único quadro; retorna False quando a fonte termina."""
        t0 = time.perf_counter()
        frame = self.source.read()
        t1 = time.perf_counter()
        if frame is None:
            return False

        rgb = preprocess(frame, self.config.process_width)
        t2 = time.perf_counter()

        detection = self.extractor.extract(rgb)
        t3 = time.perf_counter()

        prediction = None
        if detection is not None:
            prediction = self.classifier.predict(
                normalize_landmarks(detection.landmarks))
        t4 = time.perf_counter()

        confirmed = self.confirmer.update(prediction)
        if confirmed is not None:
            self.assembler.add_letter(confirmed)
            if self.on_letter:
                self.on_letter(confirmed)

        word = self.assembler.tick(hand_present=detection is not None)
        if word is not None:
            self.state.add_word(word)
            if self.on_word:
                self.on_word(word)

        for name, dt in zip(STAGES, (t1 - t0, t2 - t1, t3 - t2, t4 - t3)):
            self._stage_times[name].append(dt * 1000.0)
        self._frames += 1
        self._frame_stamps.append(time.perf_counter())

        self.state.update(
            letra_atual=prediction.label if prediction else None,
            confianca=round(prediction.confidence, 3) if prediction else None,
            mao_presente=detection is not None,
            palavra_parcial=self.assembler.current_word,
            fps=round(self._fps(), 1),
            quadros_processados=self._frames,
            latencia_ms=self._latency_ms(),
        )
        with self._frame_lock:
            self._latest_frame = frame
        return True

    # ------------------------------------------------------------ métricas
    def _fps(self) -> float:
        if len(self._frame_stamps) < 2:
            return 0.0
        span = self._frame_stamps[-1] - self._frame_stamps[0]
        if span <= 0:
            return 0.0
        return (len(self._frame_stamps) - 1) / span

    def _latency_ms(self) -> dict:
        return {name: round(sum(times) / len(times), 3)
                for name, times in self._stage_times.items() if times}

    def stats(self) -> dict:
        """Métricas do pipeline; alimentam o painel de desempenho (RF-07)."""
        return {"fps": round(self._fps(), 1),
                "quadros_processados": self._frames,
                "latencia_ms": self._latency_ms()}

    # -------------------------------------------------------- segundo plano
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="pipeline")
        self._thread.start()

    def _run(self) -> None:
        period = (1.0 / self.config.target_fps
                  if self.config.target_fps > 0 else 0.0)
        next_t = time.perf_counter()
        while not self._stop.is_set():
            if not self.step():
                break
            if period:
                next_t += period
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.perf_counter()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # ------------------------------------------------------------- exibição
    def latest_frame(self):
        """Cópia do último quadro BGR processado (ou None)."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()
