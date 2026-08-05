"""RF-01 — Interface de visualização (B6 servidor + B7 frontend).

Critério de aceitação: "A página e todas as APIs que a alimentam respondem
sem falha; os campos refletem o estado do pipeline." O carregamento é
verificado por cliente HTTP de teste — sem navegador e sem câmera (RNF-07):
a página principal, os arquivos estáticos e as APIs.

As métricas do processador (RF-07) entram na entrega de instrumentação; aqui
só se exige o que o núcleo B1–B5 já produz, e que a rota de info responda sem
falhar mesmo sem provedor (RNF-06).
"""
import pytest

from libras.pipeline import PipelineState, TranslationPipeline
from libras.server import create_app


@pytest.fixture()
def state():
    return PipelineState()


@pytest.fixture()
def client(state):
    app = create_app(state.to_dict, lambda: {"pipeline": {}},
                     frame_provider=None)
    app.config["TESTING"] = True
    return app.test_client()


def test_pagina_principal_carrega_sem_falhas(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)
    assert "Tradutor Embarcado de LIBRAS" in html
    for element in ('id="traducao"', 'id="dashboard"', 'id="letra"',
                    'id="palavra"', 'id="historico"', 'id="video"'):
        assert element in html, f"frontend sem o elemento {element}"


def test_arquivos_estaticos_servidos(client):
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_api_de_estado_alimenta_a_interface(client):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("letra_atual", "confianca", "palavra_parcial",
                "ultima_palavra", "historico", "fps", "mao_presente",
                "latencia_ms"):
        assert key in data, f"estado sem a chave {key}"


def test_api_de_estado_reflete_o_pipeline(client, state):
    """Os campos da tela vêm do estado real, não de um valor fixo."""
    state.update(letra_atual="A", confianca=0.91, mao_presente=True,
                 palavra_parcial="AB")
    state.add_word("OI")

    data = client.get("/api/state").get_json()
    assert data["letra_atual"] == "A"
    assert data["confianca"] == pytest.approx(0.91)
    assert data["mao_presente"] is True
    assert data["palavra_parcial"] == "AB"
    assert data["ultima_palavra"] == "OI"
    assert data["historico"] == ["OI"]


def test_api_de_metricas_alimenta_o_painel(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "pipeline" in resp.get_json()


def test_metricas_do_pipeline_publicadas_na_interface(fast_config):
    """O painel recebe FPS, contagem de quadros e latência por estágio."""
    from libras.demo import make_demo_components
    from libras.pipeline import STAGES

    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config)
    for _ in range(15):
        pipeline.step()

    app = create_app(pipeline.state.to_dict,
                     lambda: {"pipeline": pipeline.stats()})
    app.config["TESTING"] = True
    data = app.test_client().get("/api/metrics").get_json()["pipeline"]

    assert data["quadros_processados"] == 15
    assert data["fps"] > 0
    assert set(data["latencia_ms"]) == set(STAGES)


def test_api_de_info_sem_monitor_nao_falha(client):
    """Sem o módulo de monitoramento a rota existe e responde vazio."""
    resp = client.get("/api/info")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_video_indisponivel_retorna_erro_claro(client):
    assert client.get("/video_feed").status_code == 503


def test_rota_inexistente_nao_derruba_o_servidor(client):
    assert client.get("/nao-existe").status_code == 404
    assert client.get("/").status_code == 200
