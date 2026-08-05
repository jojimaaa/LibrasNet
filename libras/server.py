"""Bloco B6 — servidor de aplicação.

Desacopla o núcleo de processamento das interfaces de saída (Seção 3.1 da
documentação): serve o frontend web (B7) e expõe, por API local, o estado da
tradução, as métricas de desempenho e o fluxo de vídeo MJPEG.

Os provedores são funções sem argumento — é o que permite testar o servidor
isoladamente e substituir qualquer estágio sem alterá-lo. ``info_provider``
fica opcional porque o módulo transversal de monitoramento (RF-07) entra na
entrega seguinte; sem ele a rota responde um objeto vazio, e o frontend
degrada para "—" (RNF-06).

Nenhuma rota sai do dispositivo: o servidor escuta na rede local e não faz
requisição de saída alguma (RNF-04 e RNF-05).
"""
from __future__ import annotations

import time

from flask import Flask, Response, jsonify

from .config import FRONTEND_DIR


def create_app(state_provider, metrics_provider, info_provider=None,
               frame_provider=None, stream_fps: float = 10.0) -> Flask:
    """Cria a aplicação Flask.

    - ``state_provider()``  → dict com o estado da tradução (letra, palavra…)
    - ``metrics_provider()``→ dict com as métricas do pipeline/monitor
    - ``info_provider()``   → dict com a identificação da máquina
    - ``frame_provider()``  → bytes JPEG do quadro atual (None = sem vídeo)
    - ``stream_fps``        → taxa do fluxo MJPEG; cada quadro enviado custa
      um ``cv2.imencode`` nesta thread, disputando CPU com o pipeline, então
      no dispositivo embarcado ela fica bem abaixo da taxa de captura
    """
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/state")
    def api_state():
        return jsonify(state_provider())

    @app.get("/api/metrics")
    def api_metrics():
        return jsonify(metrics_provider())

    @app.get("/api/info")
    def api_info():
        return jsonify(info_provider() if info_provider else {})

    @app.get("/video_feed")
    def video_feed():
        if frame_provider is None:
            return Response("vídeo indisponível neste modo", status=503,
                            mimetype="text/plain")

        period = 1 / stream_fps if stream_fps > 0 else 0.0

        def generate():
            while True:
                jpeg = frame_provider()
                if jpeg is None:
                    time.sleep(0.1)
                    continue
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + jpeg + b"\r\n")
                if period:
                    time.sleep(period)

        return Response(generate(),
                        mimetype="multipart/x-mixed-replace; boundary=frame")

    return app
