"""Fixtures compartilhadas pela suíte de requisitos.

Os testes rodam em qualquer máquina, sem webcam, OpenCV ou MediaPipe: os
estágios dependentes de hardware são substituídos pelas implementações
sintéticas do pacote (RNF-07). Todos os demais estágios exercitados são os
de produção.

Os imports das fixtures são feitos dentro delas, e não no topo do arquivo,
porque o projeto é migrado em entregas parciais: um bloco ainda não migrado
não pode impedir a *coleta* dos testes dos blocos que já existem.
"""
import pytest


@pytest.fixture(scope="session")
def fast_config():
    """Config com janelas temporais curtas, para testes rápidos."""
    from libras.config import Config

    return Config(window_size=6, min_votes=4, release_frames=3,
                  word_pause_frames=10, target_fps=0)


@pytest.fixture(scope="session")
def synthetic_dataset():
    """(X, y, prototipos) do alfabeto sintético determinístico."""
    from libras.demo import make_synthetic_dataset

    return make_synthetic_dataset()


@pytest.fixture(scope="session")
def trained_classifier(synthetic_dataset):
    from libras.classifier import KnnClassifier

    X, y, _ = synthetic_dataset
    return KnnClassifier(k=5).fit(X, y)
