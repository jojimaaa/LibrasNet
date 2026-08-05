"""RF-07 — Painel de desempenho do processador.

Critério de aceitação: "O painel apresenta uso de CPU, memória, clock,
temperatura, FPS e latência por estágio; métrica sem fonte na plataforma
aparece como indisponível" (Seção 4.1 da documentação).

Os testes rodam em qualquer plataforma: o que se exige é a *presença* de cada
chave e o comportamento na ausência de fonte — não um valor que só a
Raspberry Pi produziria.
"""
import psutil

from libras.demo import make_demo_components
from libras.monitor import PerformanceMonitor, machine_info
from libras.pipeline import STAGES, PipelineState, TranslationPipeline
from libras.server import create_app

PAINEL_KEYS = ("cpu_percent", "cpu_por_nucleo", "ram_percent", "ram_usada_mb",
               "ram_total_mb", "clock_mhz", "temperatura_c", "cpi", "ipc")


def test_amostra_contem_todas_as_metricas_do_painel():
    sample = PerformanceMonitor().sample()
    for key in PAINEL_KEYS:
        assert key in sample, f"métrica ausente: {key}"
    assert 0.0 <= sample["cpu_percent"] <= 100.0
    assert 0.0 <= sample["ram_percent"] <= 100.0
    assert len(sample["cpu_por_nucleo"]) == psutil.cpu_count(logical=True)
    if sample["clock_mhz"] is not None:
        assert sample["clock_mhz"] > 0
    if sample["temperatura_c"] is not None:
        assert -20.0 < sample["temperatura_c"] < 130.0
    if sample["cpi"] is not None:
        assert 0.05 < sample["cpi"] < 50.0


def test_metrica_sem_fonte_aparece_como_indisponivel(monkeypatch):
    """Sem sensor térmico e sem contador de clock, o painel recebe None em vez
    de a coleta falhar (RNF-06)."""
    import libras.monitor as monitor_mod

    monkeypatch.setattr(monitor_mod, "read_temperature_c", lambda: None)
    monkeypatch.setattr(monitor_mod, "read_clock_mhz", lambda: None)
    monkeypatch.setattr(monitor_mod, "read_cpi_via_perf", lambda *a, **k: None)

    sample = PerformanceMonitor().sample()
    assert sample["temperatura_c"] is None
    assert sample["clock_mhz"] is None
    assert sample["cpi"] is None and sample["ipc"] is None
    assert sample["cpu_percent"] is not None  # o resto do painel segue vivo


def test_sensor_que_lanca_erro_nao_derruba_a_amostragem(monkeypatch):
    """Leitura de sensor que falha no meio da execução vira indisponível."""
    def boom(*args, **kwargs):
        raise OSError("sensor sumiu")

    monkeypatch.setattr(psutil, "sensors_temperatures", boom, raising=False)
    monkeypatch.setattr(psutil, "cpu_freq", boom)

    from libras.monitor import read_clock_mhz, read_temperature_c

    # Em Linux há as fontes alternativas (/sys, vcgencmd); o contrato é não
    # propagar a exceção — o valor pode vir de lá ou ser None.
    assert read_temperature_c() is None or isinstance(read_temperature_c(),
                                                     float)
    assert read_clock_mhz() is None or read_clock_mhz() > 0


def test_painel_completo_exposto_pela_api(fast_config):
    """A API que alimenta o painel entrega métricas do processador E do
    pipeline no mesmo retrato."""
    source, extractor, classifier = make_demo_components(fast_config)
    pipeline = TranslationPipeline(source, extractor, classifier, fast_config,
                                   state=PipelineState())
    for _ in range(12):
        pipeline.step()
    monitor = PerformanceMonitor()

    def metrics():
        data = monitor.latest()
        data["pipeline"] = pipeline.stats()
        return data

    app = create_app(pipeline.state.to_dict, metrics, machine_info)
    app.config["TESTING"] = True
    data = app.test_client().get("/api/metrics").get_json()

    for key in PAINEL_KEYS:
        assert key in data, f"API sem a métrica {key}"
    assert data["pipeline"]["quadros_processados"] == 12
    assert set(data["pipeline"]["latencia_ms"]) == set(STAGES)


def test_identificacao_da_maquina_no_rodape():
    """Comparar hardwares exige saber em qual deles o painel foi medido."""
    app = create_app(PipelineState().to_dict, lambda: {}, machine_info)
    app.config["TESTING"] = True
    info = app.test_client().get("/api/info").get_json()

    for key in ("hostname", "sistema", "arquitetura", "processador",
                "nucleos_fisicos", "nucleos_logicos", "python"):
        assert key in info, f"informação ausente: {key}"
    assert info["nucleos_logicos"] >= 1


def test_pagina_tem_os_elementos_do_painel():
    app = create_app(PipelineState().to_dict, lambda: {}, machine_info)
    app.config["TESTING"] = True
    html = app.test_client().get("/").get_data(as_text=True)

    for element in ('id="dashboard"', 'id="m-cpu"', 'id="m-ram"',
                    'id="m-clock"', 'id="m-temp"', 'id="m-cpi"',
                    'id="m-ipc"', 'id="m-fps"', 'id="latencias"',
                    'id="machine-info"'):
        assert element in html, f"painel sem o elemento {element}"
