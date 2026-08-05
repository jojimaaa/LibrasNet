"""RF-05 — Saída em voz (B8).

Critério de aceitação: cada palavra concluída é sintetizada em áudio, e a
"ausência de motor de voz degrada para somente texto, sem falhar" (RNF-06).
Os testes rodam sem placa de som: o motor nulo torna a fala observável
(RNF-07).
"""
import threading
import time

from libras.temporal import WordAssembler
from libras.tts import (
    AsyncSpeaker,
    EspeakEngine,
    NullEngine,
    Pyttsx3Engine,
    create_engine,
)


def unavailable(self, *args, **kwargs):
    raise RuntimeError("motor indisponível")


def test_palavra_concluida_e_sintetizada():
    """A palavra fechada por pausa chega ao motor de voz — uma vez só."""
    engine = NullEngine()
    assembler = WordAssembler(word_pause_frames=3, on_word=engine.speak)
    for letter in "OI":
        assembler.add_letter(letter)
    for _ in range(6):
        assembler.tick(hand_present=False)
    assert engine.spoken == ["OI"]


def test_sintese_nao_bloqueia_o_laco_de_captura():
    """speak() deve retornar imediatamente mesmo com um motor lento."""
    class SlowEngine(NullEngine):
        def speak(self, text):
            time.sleep(0.3)  # simula a latência de um motor de TTS real
            super().speak(text)

    engine = SlowEngine()
    speaker = AsyncSpeaker(engine)
    t0 = time.perf_counter()
    speaker.speak("LIBRAS")
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.1, f"speak() bloqueou o chamador por {elapsed:.3f}s"

    deadline = time.time() + 2.0
    while time.time() < deadline and not engine.spoken:
        time.sleep(0.01)
    speaker.close()
    assert engine.spoken == ["LIBRAS"]


def test_falas_sintetizadas_na_ordem_das_palavras():
    engine = NullEngine()
    speaker = AsyncSpeaker(engine)
    for word in ("OI", "MUNDO", "USP"):
        speaker.speak(word)
    speaker.close()  # drena a fila antes de encerrar a thread
    assert engine.spoken == ["OI", "MUNDO", "USP"]


def test_fallback_de_tts_sempre_disponivel(monkeypatch):
    """Sem nenhum motor de áudio disponível, a fábrica degrada para o motor
    nulo e o sistema segue funcionando (saída em texto)."""
    monkeypatch.setattr(Pyttsx3Engine, "__init__", unavailable)
    monkeypatch.setattr(EspeakEngine, "__init__", unavailable)

    engine = create_engine()
    assert isinstance(engine, NullEngine)
    engine.speak("TESTE")
    assert engine.spoken == ["TESTE"]


def test_pyttsx3_cria_a_engine_na_thread_que_fala(monkeypatch):
    """Regressão: o backend SAPI5 é COM e só toca na thread onde a engine foi
    criada; uma engine reaproveitada volta muda. Cada fala deve construir a
    sua, dentro da thread de voz."""
    created = []

    class FakeEngine:
        def __init__(self):
            created.append(threading.current_thread().name)

        def say(self, text):
            pass

        def runAndWait(self):
            pass

        def stop(self):
            pass

    engine = Pyttsx3Engine.__new__(Pyttsx3Engine)  # sem tocar em pyttsx3
    engine._factory = FakeEngine

    speaker = AsyncSpeaker(engine)
    speaker.speak("OI")
    speaker.speak("USP")
    speaker.close()

    assert len(created) == 2, "engine reaproveitada entre falas"
    assert set(created) == {"tts"}, f"engine criada fora da thread de voz: {created}"


def test_close_espera_a_fila_ser_drenada():
    """Uma palavra pendente não pode ser cortada no desligamento."""
    class SlowEngine(NullEngine):
        def speak(self, text):
            time.sleep(0.4)
            super().speak(text)

    engine = SlowEngine()
    speaker = AsyncSpeaker(engine)
    for word in ("OI", "MUNDO", "USP"):
        speaker.speak(word)
    speaker.close()
    assert engine.spoken == ["OI", "MUNDO", "USP"]


def test_close_nao_espera_para_sempre_por_motor_travado():
    """Motor travado atrasa o desligamento, mas não o impede (RNF-06)."""
    class HangingEngine(NullEngine):
        def speak(self, text):
            time.sleep(30)

    speaker = AsyncSpeaker(HangingEngine())
    speaker.speak("OI")
    t0 = time.perf_counter()
    speaker.close(timeout=0.5)
    assert time.perf_counter() - t0 < 5


def test_falha_do_motor_nao_derruba_a_thread_de_voz():
    """Uma exceção na síntese é registrada, e a próxima fala é atendida."""
    class FlakyEngine(NullEngine):
        def speak(self, text):
            if text == "FALHA":
                raise RuntimeError("motor caiu")
            super().speak(text)

    engine = FlakyEngine()
    speaker = AsyncSpeaker(engine)
    speaker.speak("FALHA")
    speaker.speak("OK")
    speaker.close()
    assert engine.spoken == ["OK"]
