# LibrasNet

Escola Politécnica da Universidade de São Paulo

Enzo Koichi Jojima 14568285 (enzo.jojima@usp.br)

Pedro Biagioni Matusita (14602115) (pedromatusita@usp.br)

## Requirements

- git
- curl
- [uv package manager](https://docs.astral.sh/uv/)
- Python 3.12

## Usage

### Install requirements and clone

```bash
# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/jojimaaa/LibrasNet.git
```

### Install dependencies
```bash
# Core: enough to run the test suite on any machine (no camera required)
uv sync

# Target device / dev machine with a webcam: adds OpenCV and MediaPipe
uv sync --extra hardware
```

### Run project
```bash
# Demo mode: full pipeline on synthetic gestures, no camera required (RF-08)
uv run python3 -m libras.main --demo

# Real mode: webcam + MediaPipe + data/dataset.csv (needs the hardware extra)
uv run python3 -m libras.main
```

Then open <http://localhost:8001/>. The page shows the live camera stream
(MJPEG), the current letter with its confidence, the word being assembled, the
word history and the pipeline latency per stage. Each finished word is also
spoken out loud (RF-05).

Useful flags: `--port`, `--host`, `--camera`, `--demo-text`, `--no-tts` and
`--tts-engine {pyttsx3,espeak,null}`. On Raspberry Pi OS, `espeak-ng` is the
lightest engine (`sudo apt install espeak-ng`); with no engine at all the
system keeps running with text-only output (RNF-06).

The video stream needs OpenCV (the `hardware` extra); without it every other
output still works and `/video_feed` answers `503`.

Local HTTP API: `/api/state` (translation state), `/api/metrics` (pipeline
metrics), `/api/info` (machine identification, filled in by the performance
monitor in the next delivery). Nothing leaves the device (RNF-04, RNF-05).

### Run the requirements test suite
Each requirement of `docs/documentacao.md` maps to a test module; the suite
runs without a camera, OpenCV or MediaPipe (RNF-07).

```bash
uv run pytest
```

### Collect gesture samples (RF-06)
The k-NN classifier has no offline training step: the dataset **is** the
model. Requires the `hardware` extra and a webcam.

```bash
# One-time, only for mediapipe >= 0.10.31 (~7.8 MB, then fully offline)
uv run python3 -m libras.get_model

uv run python3 -m libras.collect --camera 0 --burst 20
```

In the video window: hold the gesture and press the matching letter key
(A–Z) to record a burst of samples; `ESC` exits. Aim for at least ~20
samples per letter, varying the hand angle and distance slightly. Samples
are appended to `data/dataset.csv`, and the model is reloaded at the end of
each burst — the live prediction on screen shows which letters still need
reinforcement.

`data/dataset.csv` already ships with 9032 collected samples covering the 20
static letters (A–G, I, L–W). `H`, `J`, `K`, `X`, `Y` and `Z` involve
movement and are out of scope for this iteration.
