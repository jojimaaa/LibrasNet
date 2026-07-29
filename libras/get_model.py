"""Baixa o modelo ``hand_landmarker.task`` da API Tasks do MediaPipe.

Necessário apenas com ``mediapipe`` >= 0.10.31 (que removeu a API legada
``mp.solutions``). Download único de ~7,8 MB; depois o sistema segue 100%
offline (RNF-04, RNF-05).

Uso:
    python -m libras.get_model [--destino data/hand_landmarker.task]
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

from .config import MODEL_PATH

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m libras.get_model",
        description="Baixa o modelo hand_landmarker.task (API Tasks)")
    parser.add_argument("--destino", default=str(MODEL_PATH),
                        help="caminho do arquivo de modelo")
    args = parser.parse_args(argv)

    destination = Path(args.destino)
    if destination.exists():
        print(f"Modelo já existe em {destination} "
              f"({destination.stat().st_size / 2**20:.1f} MB); nada a fazer.")
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Baixando {MODEL_URL}\n  -> {destination}")
    try:
        urllib.request.urlretrieve(MODEL_URL, destination)
    except OSError as exc:
        print(f"Falha no download: {exc}", file=sys.stderr)
        return 1
    print(f"Concluído ({destination.stat().st_size / 2**20:.1f} MB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
