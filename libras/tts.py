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
    """pyttsx3: SAPI5 no Windows, espeak no Linux — multiplataforma.

    Cada fala usa uma instância nova de ``Engine``, criada dentro da thread
    que fala. Não é desperdício: no Windows o backend é COM (SAPI5), que só
    funciona na thread onde o objeto foi criado, e uma engine reaproveitada
    depois de ``runAndWait`` volta muda — nos dois casos o áudio é engolido em
    silêncio, e só a duração da chamada denuncia (0,2 s em vez de ~1,5 s).
    Construir a engine custa uma fração da própria síntese, e o custo cai na
    thread de voz, nunca no laço de captura.

    Usa ``pyttsx3.engine.Engine`` em vez de ``pyttsx3.init()`` porque a
    fábrica devolve uma engine em cache por nome de driver — o que anularia a
    criação por thread.
    """

    name = "pyttsx3"

    def __init__(self):
        from pyttsx3.engine import Engine  # ImportError tratado na fábrica

        self._factory = Engine
        self._factory().stop()  # falha aqui = motor indisponível na máquina

    def speak(self, text):
        engine = self._factory()
        engine.say(text)
        engine.runAndWait()


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

    def close(self, timeout: float = 15.0) -> None:
        """Drena a fila e encerra a thread de voz.

        O limite é generoso porque a fila pode ter palavras pendentes e cada
        uma leva ~1,5 s de síntese: um join curto encerraria o processo no
        meio da última fala. Ainda assim é um limite, e não uma espera
        infinita — um motor travado não pode impedir o desligamento.
        """
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        self.engine.close()
