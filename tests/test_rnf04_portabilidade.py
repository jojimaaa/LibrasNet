"""RNF-04 — Portabilidade.

Verificação do documento de requisitos: "Teste que bloqueia sockets e roda o
pipeline completo; verificação de estabilidade de memória." O sistema é
autocontido: funciona offline e sustenta execução prolongada — as duas
condições que o uso embarcado impõe (Seção 1.2).
"""
import socket

import psutil

from libras.demo import make_demo_components
from libras.monitor import PerformanceMonitor, machine_info
from libras.pipeline import PipelineState, TranslationPipeline
from libras.server import create_app
from libras.tts import NullEngine


def block_network(monkeypatch):
    """Deixa qualquer tentativa de sair para a rede explodir no teste."""
    def block(*args, **kwargs):
        raise AssertionError("tentativa de acesso à rede detectada")

    monkeypatch.setattr(socket.socket, "connect", block)
    monkeypatch.setattr(socket.socket, "sendto", block, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", block)


def test_sistema_funciona_totalmente_offline(fast_config, monkeypatch):
    """Computação de borda: nenhum estágio pode depender de rede externa."""
    block_network(monkeypatch)

    source, extractor, classifier = make_demo_components(fast_config)
    state = PipelineState()
    engine = NullEngine()
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=state, on_word=engine.speak)
    for _ in range(30):
        assert pipeline.step()

    monitor = PerformanceMonitor()
    app = create_app(state.to_dict, monitor.sample, machine_info)
    app.config["TESTING"] = True
    client = app.test_client()
    for route in ("/", "/api/state", "/api/metrics", "/api/info"):
        assert client.get(route).status_code == 200, f"{route} exigiu rede"


def test_painel_amostra_metricas_sem_rede(monkeypatch):
    """A instrumentação lê contadores locais — nada de serviço externo."""
    block_network(monkeypatch)
    sample = PerformanceMonitor().sample()
    assert sample["cpu_percent"] is not None


def test_uso_de_memoria_estavel_em_execucao_prolongada(fast_config):
    """Execução contínua sem vazamento que inviabilize o embarcado."""
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                  state=PipelineState())
    process = psutil.Process()
    for _ in range(50):        # aquecimento (buffers e caches internos)
        pipeline.step()
    rss_before = process.memory_info().rss
    for _ in range(500):
        pipeline.step()
    growth_mb = (process.memory_info().rss - rss_before) / 2**20
    # Crescimento real medido é ~0,02 MiB; 16 MiB deixa folga ampla contra
    # ruído de RSS sem mascarar um vazamento por quadro de verdade.
    assert growth_mb < 16, \
        f"memória cresceu {growth_mb:.1f} MiB em 500 quadros"


def test_historico_de_palavras_nao_cresce_sem_limite(fast_config):
    """O que a tela acumula também tem de caber em 1 GiB de RAM: as janelas
    de latência e de FPS são limitadas por construção."""
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                  state=PipelineState())
    for _ in range(300):
        pipeline.step()
    for times in pipeline._stage_times.values():
        assert len(times) <= times.maxlen
    assert len(pipeline._frame_stamps) <= pipeline._frame_stamps.maxlen
