"""Ponto de entrada do tradutor embarcado de LIBRAS.

Monta os blocos B1 → B8 e sobe o servidor de aplicação:

    python -m libras.main --demo                 # sem hardware (RF-08)
    python -m libras.main                        # webcam + MediaPipe + dataset
    python -m libras.main --demo --no-tts --port 8080

O painel de métricas do processador (RF-07) entra na entrega de
instrumentação; até lá ``/api/metrics`` publica só as métricas do pipeline.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .capture import CameraSource
from .classifier import KnnClassifier
from .config import DEFAULT_DATASET, Config
from .demo import make_demo_components
from .landmarks import MediaPipeExtractor
from .pipeline import PipelineState, TranslationPipeline
from .server import create_app
from .tts import AsyncSpeaker, create_engine


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m libras.main",
        description="Tradutor embarcado de LIBRAS (visão computacional)")
    parser.add_argument("--demo", action="store_true",
                        help="modo demonstração, sem webcam/MediaPipe")
    parser.add_argument("--demo-text", default="LIBRAS USP",
                        help="texto soletrado no modo demo")
    parser.add_argument("--camera", type=int, default=0,
                        help="índice da webcam (modo real)")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET),
                        help="CSV de amostras coletadas (modo real)")
    parser.add_argument("--host", default=None,
                        help="endereço de escuta do servidor (padrão 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"porta do servidor (padrão {Config.port})")
    parser.add_argument("--no-tts", action="store_true",
                        help="desliga a síntese de voz")
    parser.add_argument("--tts-engine", choices=["pyttsx3", "espeak", "null"],
                        default=None, help="força um motor de TTS específico")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args = parse_args(argv)
    config = Config(camera_index=args.camera)
    if args.host is not None:
        config.host = args.host
    if args.port is not None:
        config.port = args.port

    # ------------------------------------------------ montagem dos estágios
    if args.demo:
        source, extractor, classifier = make_demo_components(
            config, args.demo_text)
        mode = f"demonstração (soletrando: {args.demo_text!r})"
    else:
        dataset = Path(args.dataset)
        if not dataset.exists():
            print(f"Dataset não encontrado em {dataset}.\n"
                  "Colete amostras com:   python -m libras.collect\n"
                  "ou rode sem hardware:  python -m libras.main --demo",
                  file=sys.stderr)
            return 2
        classifier = KnnClassifier.load(dataset, k=config.knn_k)
        source = CameraSource(config.camera_index, config.frame_width,
                              config.frame_height)
        extractor = MediaPipeExtractor(
            model_complexity=config.model_complexity)
        mode = (f"real (câmera {config.camera_index}, "
                f"{classifier.n_samples} amostras, "
                f"{len(classifier.classes)} letras)")

    speaker = None
    if not args.no_tts:
        speaker = AsyncSpeaker(create_engine(args.tts_engine))

    state = PipelineState()

    def on_word(word: str) -> None:
        if speaker:
            speaker.speak(word)

    pipeline = TranslationPipeline(source, extractor, classifier, config,
                                   state=state, on_word=on_word)
    pipeline.start()

    frame_provider = pipeline.jpeg if pipeline.supports_video else None

    def metrics() -> dict:
        # O monitor do processador (RF-07) passa a preencher este dicionário
        # na entrega de instrumentação; a chave "pipeline" não muda.
        return {"pipeline": pipeline.stats()}

    app = create_app(state.to_dict, metrics, frame_provider=frame_provider,
                     stream_fps=config.video_stream_fps)

    tts_name = speaker.engine.name if speaker else "desligado"
    video = ("MJPEG em /video_feed" if frame_provider
             else "indisponível (sem OpenCV)")
    print("=" * 62)
    print("Tradutor embarcado de LIBRAS")
    print(f"  modo:     {mode}")
    print(f"  TTS:      {tts_name}")
    print(f"  vídeo:    {video}")
    print(f"  frontend: http://localhost:{config.port}/")
    print("=" * 62)

    try:
        app.run(host=config.host, port=config.port, threaded=True,
                use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.stop()
        if speaker:
            speaker.close()
        source.release()
        extractor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
