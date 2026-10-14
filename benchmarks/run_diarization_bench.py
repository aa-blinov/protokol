"""Benchmarks for the diarization hypotheses that do not need real call audio.

H4 (clustering thresholds) and H5 (the lock held for the whole of diarize) run on
a synthetic corpus built by make_corpus.py. Scores are a smoke test, not a DER
number for production calls -- see that script for why.

Usage:
  .venv/bin/python benchmarks/run_diarization_bench.py grid
  .venv/bin/python benchmarks/run_diarization_bench.py timing
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from diarization import (  # noqa: E402
    SAMPLE_RATE,
    _CLUSTER_THRESHOLD,
    _MAX_FRAGMENT_SECONDS,
    Diarizer,
)

from der import Turns, der, load_truth, turns_from_objects  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus"
# diarization.py:67 marks 20 s a guess. The grid brackets it on both sides.
GRID = [0.20, 0.30, 0.35, 0.42, 0.50, 0.60, 0.70]


def load_diarizer(threads: int = 4) -> Diarizer:
    return Diarizer(
        config.DIARIZATION_SEG_DIR,
        config.DIARIZATION_EMB_PATH,
        threads=threads,
    )


def corpus(name: str) -> np.ndarray:
    """Load a corpus file, pointing at the generator when it is missing.

    The hour-long take is 222 MB, so it is not kept in the repo; run make_corpus.py
    to rebuild it before the timing mode.
    """
    path = CORPUS / name
    if not path.is_file():
        raise SystemExit(
            f"нет {path}\nсначала соберите корпус: .venv/bin/python benchmarks/make_corpus.py"
        )
    return np.load(path)


def short(noise_snr: float | None = None, seed: int = 7) -> np.ndarray:
    audio = corpus("call_2spk.npy")
    if noise_snr is None:
        return audio
    return add_noise(audio, noise_snr, seed)


def add_noise(audio: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """Mix in pink-ish noise at a given SNR against speech RMS.

    make_corpus.py already adds a whisper of noise; this pushes the recording to
    a stated SNR so the threshold grid is measured somewhere other than silence,
    which is where speaker splitting would actually show up.
    """
    rng = np.random.default_rng(seed)
    white = rng.normal(0.0, 1.0, audio.size).astype(np.float32)
    # One-pole low-pass: white noise alone is too easy for the segmenter to reject.
    smoothed = np.empty_like(white)
    alpha = 0.25
    accumulator = 0.0
    for index in range(white.size):
        accumulator += alpha * (white[index] - accumulator)
        smoothed[index] = accumulator
    signal_rms = float(np.sqrt(np.mean(audio**2)))
    noise_rms = signal_rms / (10 ** (snr_db / 20))
    current = float(np.sqrt(np.mean(smoothed**2)))
    smoothed *= noise_rms / current
    return np.clip(audio + smoothed, -1.0, 1.0)


def long() -> np.ndarray:
    return corpus("call_long.npy")


def run_grid(noise_snr: float | None = None) -> None:
    reference = load_truth(CORPUS / "call_2spk.truth.json")
    diarizer = load_diarizer()
    audio = short(noise_snr)
    condition = "чистая запись" if noise_snr is None else f"шум {noise_snr:.0f} дБ SNR"
    print(f"USE_COREML={config.USE_COREML}  провайдеры: {config.ort_providers()}")
    print(f"условие: {condition}")
    print(f"эталон: {len(reference.speakers)} спикера, {reference.duration:.1f} с речи")
    print()
    print(f"{'порог':>6} {'спикеров':>9} {'DER':>7} {'ошибка':>7} {'FA':>6} {'точность':>9}")
    results: list[tuple[float, float]] = []
    for threshold in GRID:
        diarizer.cluster_threshold = threshold
        started = time.perf_counter()
        turns = diarizer.diarize(audio)
        elapsed = time.perf_counter() - started
        hypothesis = turns_from_objects(turns)
        scores = der(reference, hypothesis)
        results.append((threshold, scores["der"], len(hypothesis.speakers), len(turns), scores, elapsed))

    best = min(results, key=lambda row: row[1])
    for threshold, rate, found, count, scores, elapsed in results:
        marks = []
        if threshold == best[0]:
            marks.append("<- минимум")
        if abs(threshold - _CLUSTER_THRESHOLD) < 1e-9:
            marks.append("<- текущее значение")
        print(
            f"{threshold:>6.2f} {found:>9} {rate * 100:>6.1f}% "
            f"{scores['miss']:>6.1f}s {scores['false_alarm']:>5.1f}s "
            f"{scores['accuracy'] * 100:>8.1f}%  {'  '.join(marks)}"
        )
        print(f"       (вызов занял {elapsed:.1f} с, реплик: {count})")
    print()
    print(f"минимум DER на сетке: порог {best[0]:.2f}, DER {best[1] * 100:.1f}%")
    best_at_current = next(row for row in results if abs(row[0] - _CLUSTER_THRESHOLD) < 1e-9)
    print(f"при текущем пороге {_CLUSTER_THRESHOLD:.2f}: DER {best_at_current[1] * 100:.1f}%")
    print(f"фрагменты короче {_MAX_FRAGMENT_SECONDS:.0f} с сворачиваются при любом числе спикеров")


def run_timing() -> None:
    diarizer = load_diarizer()
    audio = long()
    minutes = audio.size / SAMPLE_RATE / 60
    print(f"длительность записи: {minutes:.1f} мин")

    started = time.perf_counter()
    turns = diarizer.diarize(audio)
    single = time.perf_counter() - started
    print(f"один вызов diarize: {single:.1f} с ({single / minutes:.2f} с на минуту аудио)")
    print(f"реплик найдено: {len(turns)}, спикеров: {len({t.speaker for t in turns})}")

    # The lock spans segmentation, embedding and clustering (diarization.py:327),
    # so two concurrent calls should cost two single calls if it serialises them.
    threads = [threading.Thread(target=diarizer.diarize, args=(audio,)) for _ in range(2)]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    parallel = time.perf_counter() - started
    print()
    print(f"два вызова подряд: {2 * single:.1f} с")
    print(f"два вызова параллельно: {parallel:.1f} с")
    ratio = parallel / single if single else float("nan")
    print(f"отношение к одному вызову: {ratio:.2f}x")
    print(
        "вывод: блокировка сериализует вызовы целиком"
        if ratio > 1.7
        else "вывод: вызовы заметно перекрываются, блокировка не доминирует"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["grid", "timing"])
    parser.add_argument(
        "--snr",
        type=float,
        default=None,
        help="уровень шума в дБ относительно речи; без флага запись чистая",
    )
    args = parser.parse_args()
    if args.mode == "grid":
        run_grid(args.snr)
    else:
        run_timing()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())