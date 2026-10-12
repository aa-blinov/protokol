"""Diarization on real human voices instead of synthetic ones.

Everything measured so far in benchmarks/ came from macOS `say` voices. This runs
the same code on two real LibriVox readers stitched into one file, with the
reader change as ground truth -- the first DER from real speech in this repo.

Run: .venv/bin/python benchmarks/run_real_eval.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(HERE))

import config  # noqa: E402
from diarization import SAMPLE_RATE, _CLUSTER_THRESHOLD, Diarizer  # noqa: E402

from der import Turns, der, load_truth, turns_from_objects  # noqa: E402

CORPUS = HERE / "corpus" / "librivox"
GRID = [0.30, 0.42, 0.50, 0.60, 0.70]


def main() -> int:
    audio_path = CORPUS / "two_readers.npy"
    truth_path = CORPUS / "two_readers.truth.json"
    if not audio_path.is_file():
        raise SystemExit(
            "нет корпуса, соберите его: .venv/bin/python benchmarks/make_librivox_corpus.py"
        )

    reference = load_truth(truth_path)
    audio = np.load(audio_path)
    diarizer = Diarizer(
        config.DIARIZATION_SEG_DIR, config.DIARIZATION_EMB_PATH, threads=config.INFERENCE_THREADS
    )

    minutes = audio.size / SAMPLE_RATE / 60
    print(f"запись: {audio.size / SAMPLE_RATE:.0f} с ({minutes:.1f} мин), реальные голоса")
    print(f"читателей в эталоне: {len(reference.speakers)} — {reference.speakers}")
    print(f"USE_COREML={config.USE_COREML}, провайдеры: {config.ort_providers()}")
    print()

    print(f"{'порог':>6} {'найдено':>8} {'DER':>7} {'пропуск':>8} {'ложн.':>7} {'точн.':>8} {'время':>7}")
    for threshold in GRID:
        diarizer.cluster_threshold = threshold
        started = time.perf_counter()
        turns = diarizer.diarize(audio)
        elapsed = time.perf_counter() - started
        hypothesis = turns_from_objects(turns)
        scores = der(reference, hypothesis)
        mark = "  <- текущее" if abs(threshold - _CLUSTER_THRESHOLD) < 1e-9 else ""
        print(
            f"{threshold:>6.2f} {len(hypothesis.speakers):>8} {scores['der'] * 100:>6.1f}% "
            f"{scores['miss']:>7.1f}s {scores['false_alarm']:>6.1f}s "
            f"{scores['accuracy'] * 100:>7.1f}% {elapsed:>6.1f}s{mark}"
        )

    # At the shipped threshold, show where the boundaries actually landed.
    diarizer.cluster_threshold = _CLUSTER_THRESHOLD
    turns = diarizer.diarize(audio)
    hypothesis = turns_from_objects(turns)
    scores = der(reference, hypothesis)
    print()
    print(f"при пороге {_CLUSTER_THRESHOLD}: DER {scores['der'] * 100:.1f}%, спикеров {len(hypothesis.speakers)}")
    print()
    print("эталон:")
    for item in reference.items:
        print(f"  {item[0]:7.1f}–{item[1]:7.1f} с  {item[2]}")
    print("найдено:")
    for item in hypothesis.items:
        print(f"  {item[0]:7.1f}–{item[1]:7.1f} с  спикер {item[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())