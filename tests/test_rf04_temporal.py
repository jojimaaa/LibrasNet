"""RF-04 — Estabilização temporal e montagem de palavras (bloco B5).

Critério de aceitação do documento de requisitos: "Transições entre gestos
não geram letras espúrias; letra repetida exige liberação (mão fora do
quadro); pausa longa fecha a palavra."
"""
import pytest

from libras.classifier import Prediction
from libras.demo import ALPHABET, spell_sequence
from libras.temporal import LetterConfirmer, WordAssembler


def make_confirmer():
    return LetterConfirmer(min_confidence=0.7, window_size=6,
                           min_votes=4, release_frames=3)


# ---------------------------------------------- confirmação por votação
def test_letra_so_confirma_apos_estabilidade():
    confirmer = make_confirmer()
    prediction = Prediction("A", 0.95)
    assert [confirmer.update(prediction) for _ in range(3)] == [None] * 3
    assert confirmer.update(prediction) == "A"


def test_predicao_com_baixa_confianca_e_descartada():
    confirmer = make_confirmer()
    for _ in range(20):
        assert confirmer.update(Prediction("A", 0.5)) is None


def test_oscilacao_entre_classes_nao_confirma():
    """Transição entre gestos não pode gerar letra espúria."""
    confirmer = make_confirmer()
    for i in range(30):
        prediction = Prediction("A" if i % 2 == 0 else "B", 0.95)
        assert confirmer.update(prediction) is None


def test_letra_repetida_exige_liberacao_da_mao():
    """"SS" só sai se a mão deixar o quadro entre as duas letras."""
    confirmer = make_confirmer()
    prediction = Prediction("S", 0.95)
    for _ in range(3):
        confirmer.update(prediction)
    assert confirmer.update(prediction) == "S"

    for _ in range(10):                       # mão mantida: não repete
        assert confirmer.update(prediction) is None

    for _ in range(3):                        # liberação (sem mão)
        assert confirmer.update(None) is None
    for _ in range(3):
        confirmer.update(prediction)
    assert confirmer.update(prediction) == "S"


def test_ausencia_de_mao_nunca_confirma():
    confirmer = make_confirmer()
    for _ in range(20):
        assert confirmer.update(None) is None


def test_reset_limpa_o_estado_da_janela():
    confirmer = make_confirmer()
    prediction = Prediction("A", 0.95)
    for _ in range(3):
        confirmer.update(prediction)
    confirmer.reset()
    assert [confirmer.update(prediction) for _ in range(3)] == [None] * 3


def test_configuracao_incoerente_e_rejeitada():
    with pytest.raises(ValueError):
        LetterConfirmer(window_size=4, min_votes=5)


# ------------------------------------------------- montagem de palavras
def test_palavra_fecha_apos_pausa_e_buffer_limpa():
    words = []
    assembler = WordAssembler(word_pause_frames=5, on_word=words.append)
    for letter in "OLA":
        assembler.add_letter(letter)
    assert assembler.current_word == "OLA"
    for _ in range(4):
        assert assembler.tick(hand_present=False) is None
    assert assembler.tick(hand_present=False) == "OLA"
    assert words == ["OLA"]
    assert assembler.current_word == ""
    assert assembler.history == ["OLA"]


def test_mao_presente_reinicia_a_contagem_da_pausa():
    assembler = WordAssembler(word_pause_frames=4)
    assembler.add_letter("X")
    for _ in range(3):
        assembler.tick(hand_present=False)
    assembler.tick(hand_present=True)          # mão voltou: zera a pausa
    for _ in range(3):
        assert assembler.tick(hand_present=False) is None
    assert assembler.tick(hand_present=False) == "X"


def test_pausa_sem_conteudo_nao_gera_palavra_vazia():
    assembler = WordAssembler(word_pause_frames=3)
    for _ in range(10):
        assert assembler.tick(hand_present=False) is None
    assert assembler.history == []


# --------------------------------------- B4 + B5 em sequência de vídeo
def test_alfabeto_executado_em_sequencia_de_video(trained_classifier,
                                                 synthetic_dataset):
    """Cenário de aceitação do RF-03/RF-04 quadro a quadro, com ruído."""
    _, _, prototypes = synthetic_dataset
    sequence = spell_sequence(" ".join(ALPHABET), prototypes,
                              hold_frames=8, gap_frames=5,
                              word_pause_frames=6)
    confirmer = make_confirmer()
    confirmed = []
    for detection in sequence:
        prediction = (trained_classifier.predict_landmarks(detection.landmarks)
                      if detection else None)
        letter = confirmer.update(prediction)
        if letter:
            confirmed.append(letter)
    assert confirmed == list(ALPHABET)


def test_palavras_montadas_a_partir_de_gestos(trained_classifier,
                                              synthetic_dataset):
    """Somente gestos na entrada; palavras completas na saída."""
    _, _, prototypes = synthetic_dataset
    sequence = spell_sequence("LIBRAS USP", prototypes, hold_frames=8,
                              gap_frames=5, word_pause_frames=12)
    confirmer = make_confirmer()
    assembler = WordAssembler(word_pause_frames=10)
    for detection in sequence:
        prediction = (trained_classifier.predict_landmarks(detection.landmarks)
                      if detection else None)
        letter = confirmer.update(prediction)
        if letter:
            assembler.add_letter(letter)
        assembler.tick(hand_present=detection is not None)
    assert assembler.history == ["LIBRAS", "USP"]
