"""Bloco B8 — síntese de voz (RF-05).

A saída dupla texto+voz é o recurso central de acessibilidade (RNF-01). Os
motores são tentados em ordem de preferência e o sistema degrada
graciosamente para um motor nulo quando não há áudio na plataforma (RNF-06).

A síntese roda em thread própria, alimentada por fila: uma fala de ~1 s não
pode roubar quadros do laço de captura (RNF-02).
"""
from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class TtsEngine(ABC):
    name = "abstract"

    @abstractmethod
    def speak(self, text: str) -> None:
        """Sintetiza e reproduz o texto (chamada bloqueante)."""

    def close(self) -> None:
        """Libera recursos do motor (padrão: nada a fazer)."""


class Pyttsx3Engine(TtsEngine):
    """pyttsx3: SAPI5 no Windows, espeak no Linux — multiplataforma."""

    name = "pyttsx3"

    def __init__(self):
        import pyttsx3  # ImportError tratado na fábrica

        self._engine = pyttsx3.init()

    def speak(self, text):
        self._engine.say(text)
        self._engine.runAndWait()


class EspeakEngine(TtsEngine):
    """Binário espeak/espeak-ng — leve e padrão em Raspberry Pi OS."""

    name = "espeak"

    def __init__(self):
        self._bin = shutil.which("espeak-ng") or shutil.which("espeak")
        if not self._bin:
            raise RuntimeError("espeak não encontrado no PATH")

    def speak(self, text):
        subprocess.run([self._bin, "-v", "pt-br", text], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class NullEngine(TtsEngine):
    """Sem áudio disponível — apenas registra as falas (degradação graciosa).

    Também é o motor usado pela suíte de testes: ``spoken`` torna a saída de
    voz observável sem placa de som (RNF-07).
    """

    name = "null"

    def __init__(self):
        self.spoken: "list[str]" = []

    def speak(self, text):
        self.spoken.append(text)
        log.info("TTS indisponível; texto que seria falado: %s", text)


def create_engine(prefer: "str | None" = None) -> TtsEngine:
    """Escolhe o primeiro motor disponível: pyttsx3 → espeak → nulo."""
    candidates = {"pyttsx3": Pyttsx3Engine, "espeak": EspeakEngine,
                  "null": NullEngine}
    order = [prefer] if prefer else ["pyttsx3", "espeak", "null"]
    for name in order:
        try:
            return candidates[name]()
        except Exception as exc:
            log.warning("Motor TTS %s indisponível: %s", name, exc)
    return NullEngine()


class AsyncSpeaker:
    """Fila + thread dedicada: a síntese nunca bloqueia o laço de captura."""

    def __init__(self, engine: TtsEngine):
        self.engine = engine
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="tts")
        self._thread.start()

    def speak(self, text: str) -> None:
        self._queue.put(text)

    def _loop(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                self.engine.speak(text)
            except Exception:
                log.exception("Falha ao sintetizar voz")

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=2)
        self.engine.close()
