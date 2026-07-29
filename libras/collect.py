"""RF-06 — modo de coleta: alimenta o dataset com gestos reais.

Uso:
    python -m libras.collect [--camera 0] [--dataset data/dataset.csv] \
        [--burst 20]

Na janela de vídeo:
  - faça o gesto da letra e pressione a tecla correspondente (A–Z) para
    gravar uma rajada de amostras;
  - pressione ESC para encerrar.

Recomenda-se ao menos ~20 amostras por letra, variando levemente o ângulo e
a distância da mão.

O laço de vídeo (OpenCV) é apenas a casca: toda a lógica de rajada e
persistência vive em ``CollectSession``, que roda sem câmera e é o que a
suíte de testes exercita (RNF-07).
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .capture import CameraSource
from .config import DEFAULT_DATASET, Config
from .dataset import append_samples, load_dataset
from .features import normalize_landmarks
from .landmarks import MediaPipeExtractor
from .preprocess import preprocess

# Conexões do esqueleto da mão (índices dos 21 landmarks do MediaPipe).
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # polegar
    (0, 5), (5, 6), (6, 7), (7, 8),          # indicador
    (5, 9), (9, 10), (10, 11), (11, 12),     # médio
    (9, 13), (13, 14), (14, 15), (15, 16),   # anelar
    (13, 17), (17, 18), (18, 19), (19, 20),  # mínimo
    (0, 17),
)


class CollectSession:
    """Núcleo do modo de coleta, independente de câmera e de OpenCV.

    Mantém a rajada corrente e a contagem por letra, e grava cada amostra
    aceita no CSV do dataset. Uma rajada em andamento não é substituída: a
    tecla só vale quando a anterior terminou, senão um toque acidental
    partiria a rajada em duas letras.
    """

    def __init__(self, dataset_path, burst: int = 20, on_burst_end=None):
        self.dataset_path = Path(dataset_path)
        self.burst = burst
        self.on_burst_end = on_burst_end
        self.counts: "Counter[str]" = Counter()
        self.label: "str | None" = None
        self.remaining = 0
        if self.dataset_path.exists():
            _, labels = load_dataset(self.dataset_path)
            self.counts.update(labels)

    # ------------------------------------------------------------- estado
    @property
    def recording(self) -> bool:
        return self.remaining > 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def letters(self) -> int:
        return len(self.counts)

    def status(self) -> str:
        if self.recording:
            return f"gravando '{self.label}': faltam {self.remaining}"
        return "aguardando tecla A-Z"

    # -------------------------------------------------------------- coleta
    @staticmethod
    def key_to_label(key: int) -> "str | None":
        """Traduz o código de tecla do OpenCV em rótulo (A–Z) ou None."""
        if 65 <= key <= 90 or 97 <= key <= 122:
            return chr(key).upper()
        return None

    def start_burst(self, label) -> bool:
        """Inicia uma rajada; False se já há uma em andamento ou o rótulo
        não é uma letra do alfabeto."""
        if self.recording:
            return False
        label = str(label).strip().upper()
        if len(label) != 1 or not ("A" <= label <= "Z"):
            return False
        self.label = label
        self.remaining = self.burst
        return True

    def feed(self, landmarks) -> bool:
        """Grava uma amostra se houver rajada ativa; devolve se gravou."""
        if not self.recording or self.label is None:
            return False
        append_samples(self.dataset_path, self.label,
                       [normalize_landmarks(landmarks)])
        self.counts[self.label] += 1
        self.remaining -= 1
        if self.remaining == 0 and self.on_burst_end is not None:
            self.on_burst_end(self.label)
        return True


def draw_overlay(cv2, frame, session, detection) -> None:
    """Desenha o esqueleto da mão e o estado da coleta sobre o quadro."""
    if detection is not None:
        h, w = frame.shape[:2]
        pts = [(int(x * w), int(y * h)) for x, y in detection.landmarks[:, :2]]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (0, 200, 255), 1)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 255, 0), -1)
    cv2.putText(frame, session.status(), (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 128), 2)
    cv2.putText(frame,
                f"amostras: {session.total} | letras: {session.letters}",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


def main(argv=None) -> int:
    import cv2  # a coleta só faz sentido com OpenCV instalado

    parser = argparse.ArgumentParser(
        prog="python -m libras.collect",
        description="Coleta de amostras de gestos para o classificador")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--burst", type=int, default=20,
                        help="amostras gravadas por tecla pressionada")
    args = parser.parse_args(argv)

    config = Config(camera_index=args.camera)
    session = CollectSession(
        args.dataset, burst=args.burst,
        on_burst_end=lambda label: print(f"Rajada de {label} concluída."))
    if session.total:
        print(f"Dataset existente: {session.total} amostras, "
              f"{session.letters} letras.")

    source = CameraSource(config.camera_index, config.frame_width,
                          config.frame_height)
    # Mesmo model_complexity da execução: coletar com um modelo e inferir com
    # o outro desloca a distribuição dos landmarks e piora o k-NN.
    extractor = MediaPipeExtractor(model_complexity=config.model_complexity)

    print("Coleta de amostras — pressione a letra (A–Z) para gravar; ESC sai.")
    try:
        while True:
            frame = source.read()
            if frame is None:
                break
            rgb = preprocess(frame, config.process_width)
            detection = extractor.extract(rgb)
            if detection is not None:
                session.feed(detection.landmarks)

            draw_overlay(cv2, frame, session, detection)
            cv2.imshow("Coleta LIBRAS", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                break
            label = CollectSession.key_to_label(key)
            if label and session.start_burst(label):
                print(f"Gravando {args.burst} amostras da letra {label}…")
    finally:
        source.release()
        extractor.close()
        cv2.destroyAllWindows()

    print("Resumo da coleta:", dict(sorted(session.counts.items())))
    print(f"Dataset salvo em {session.dataset_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
