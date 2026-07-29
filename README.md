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
uv run python3 -m main
```

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
