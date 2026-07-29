"""Bloco B5 — lógica temporal: votação em janela, confirmação e palavras.

Uma letra só é confirmada quando a confiança supera o limiar E a mesma
classe domina a janela deslizante; uma pausa prolongada sem mão fecha a
palavra. Essa suavização elimina as letras espúrias das decisões tomadas
quadro a quadro — o maior ganho de qualidade percebida do pipeline (decisão
arquitetural 4, Seção 3.5).
"""
from __future__ import annotations

from collections import Counter, deque


class LetterConfirmer:
    """Confirma letras por limiar de confiança + votação em janela."""

    def __init__(self, min_confidence: float = 0.7, window_size: int = 12,
                 min_votes: int = 8, release_frames: int = 6):
        if min_votes > window_size:
            raise ValueError("min_votes não pode exceder window_size")
        self.min_confidence = min_confidence
        self.min_votes = min_votes
        self.release_frames = release_frames
        self._window: "deque[str | None]" = deque(maxlen=window_size)
        self._blank_streak = 0
        self._last_confirmed: "str | None" = None

    def update(self, prediction) -> "str | None":
        """Processa a predição de um quadro (``None`` quando não há mão).

        Retorna a letra confirmada neste quadro ou ``None`` (amostra
        descartada — ainda instável, com confiança baixa ou repetida).
        """
        label = None
        if (prediction is not None
                and prediction.confidence >= self.min_confidence):
            label = prediction.label

        self._window.append(label)

        if label is None:
            self._blank_streak += 1
            if self._blank_streak >= self.release_frames:
                # Pausa longa: libera a repetição da mesma letra (ex.: "SS").
                self._last_confirmed = None
            return None

        self._blank_streak = 0
        votes = Counter(v for v in self._window if v is not None)
        top, count = votes.most_common(1)[0]
        if (top == label and count >= self.min_votes
                and top != self._last_confirmed):
            self._last_confirmed = top
            self._window.clear()
            return top
        return None

    def reset(self) -> None:
        self._window.clear()
        self._blank_streak = 0
        self._last_confirmed = None


class WordAssembler:
    """Acumula letras confirmadas; a pausa longa sem mão fecha a palavra."""

    def __init__(self, word_pause_frames: int = 30, on_word=None):
        self.word_pause_frames = word_pause_frames
        self.on_word = on_word
        self.history: "list[str]" = []
        self._buffer: "list[str]" = []
        self._pause_frames = 0

    @property
    def current_word(self) -> str:
        return "".join(self._buffer)

    def add_letter(self, letter: str) -> None:
        self._buffer.append(letter)
        self._pause_frames = 0

    def tick(self, hand_present: bool) -> "str | None":
        """Deve ser chamada uma vez por quadro.

        Retorna a palavra finalizada no quadro em que a pausa atinge o
        limiar; ``None`` nos demais quadros.
        """
        if hand_present:
            self._pause_frames = 0
            return None
        self._pause_frames += 1
        if self._pause_frames == self.word_pause_frames and self._buffer:
            word = self.current_word
            self._buffer.clear()
            self.history.append(word)
            if self.on_word:
                self.on_word(word)
            return word
        return None

    def reset(self) -> None:
        self._buffer.clear()
        self._pause_frames = 0
