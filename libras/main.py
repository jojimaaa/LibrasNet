"""Ponto de entrada do tradutor embarcado de LIBRAS.

Monta os blocos B1 → B8 e sobe o servidor de aplicação:

    python -m libras.main --demo                 # sem hardware (RF-08)
    python -m libras.main                        # webcam + MediaPipe + dataset
    python -m libras.main --demo --no-tts --port 8080
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .capture import CameraSource, ThreadedFrameSource
from .classifier import KnnClassifier
from .config import DEFAULT_DATASET, Config
from .demo import make_demo_components
from .landmarks import MediaPipeExtractor
from .monitor import PerformanceMonitor, machine_info
from .pipeline import PipelineState, TranslationPipeline, measure_fps
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
    parser.add_argument("--process-width", type=int, default=None,
                        help="largura do quadro na inferência (padrão: 224 "
                             "em ARM, 320 em máquina de mesa)")
    parser.add_argument("--fps", type=float, default=None,
                        help="taxa usada para dimensionar a janela temporal; "
                             "sem ela, é medida na partida")
    parser.add_argument("--no-calibrate", action="store_true",
                        help="não mede a taxa na partida; usa as janelas "
                             "padrão (30 fps)")
    parser.add_argument("--no-threaded-capture", action="store_true",
                        help="lê a câmera dentro do laço, sem thread própria "
                             "(mais lento; útil para comparar)")
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
    if args.process_width is not None:
        config.process_width = args.process_width
    if args.no_threaded_capture:
        config.threaded_capture = False

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
        if config.threaded_capture:
            source = ThreadedFrameSource(source)
        extractor = MediaPipeExtractor(
            model_complexity=config.model_complexity)
        mode = (f"real (câmera {config.camera_index}, "
                f"{classifier.n_samples} amostras, "
                f"{len(classifier.classes)} letras)")

    # ------------------------------------------- calibragem da janela de B5
    if args.fps is not None:
        measured = args.fps
    elif args.no_calibrate:
        measured = None
    else:
        measured = measure_fps(source, extractor, classifier, config)

    if measured:
        config = config.tuned_for_fps(measured)
        tuning = (f"{measured:.1f} fps medidos → janela {config.window_size} "
                  f"quadros, {config.min_votes} votos "
                  f"({config.confirmation_latency_ms(measured):.0f} ms/letra)")
    else:
        tuning = (f"janela padrão ({config.window_size} quadros, "
                  f"{config.min_votes} votos)")

    speaker = None
    if not args.no_tts:
        speaker = AsyncSpeaker(create_engine(args.tts_engine))

    monitor = PerformanceMonitor(config.monitor_interval, config.cpi_interval)
    monitor.start()

    state = PipelineState()

    def on_word(word: str) -> None:
        if speaker:
            speaker.speak(word)

    pipeline = TranslationPipeline(source, extractor, classifier, config,
                                   state=state, on_word=on_word)
    pipeline.start()

    frame_provider = pipeline.jpeg if pipeline.supports_video else None

    def metrics() -> dict:
        # O painel lê o retrato já amostrado pela thread do monitor, e não
        # provoca uma coleta nova: a página atualiza a cada segundo e cada
        # requisição custaria uma leitura de sensores (RF-07).
        data = monitor.latest()
        data["pipeline"] = pipeline.stats()
        return data

    app = create_app(state.to_dict, metrics, machine_info, frame_provider,
                     stream_fps=config.video_stream_fps)

    tts_name = speaker.engine.name if speaker else "desligado"
    video = ("MJPEG em /video_feed" if frame_provider
             else "indisponível (sem OpenCV)")
    print("=" * 62)
    print("Tradutor embarcado de LIBRAS")
    print(f"  modo:     {mode}")
    print(f"  inferência: {config.process_width} px de largura")
    print(f"  ritmo:    {tuning}")
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
        monitor.stop()
        if speaker:
            speaker.close()
        source.release()
        extractor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
