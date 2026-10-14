"""Word Error Rate of the GigaAM int8 model on real Russian speech (FLEURS).

FLEURS is CC-BY-4.0 and needs no access token. Every clip comes with its exact
transcription, which is what a WER needs and what the synthetic corpus in
make_corpus.py could never provide.

The text is normalised the usual way for Russian: lowercase, ё folded to е,
punctuation dropped. GigaAM writes numbers out as words, so no number expansion
is needed on either side.

Run: .venv/bin/python benchmarks/run_wer_fleurs.py [--limit N]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import av
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
from stt import Stt, TARGET_SAMPLE_RATE  # noqa: E402

CORPUS = HERE / "corpus" / "fleurs"
PUNCT = re.compile(r"[^\w\sЀ-ӿ]", re.UNICODE)
SPACES = re.compile(r"\s+")


def normalise(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    text = PUNCT.sub(" ", text)
    return [w for w in SPACES.split(text) if w]


def load(path: Path) -> np.ndarray:
    """Decode to the int16 mono samples Stt.transcribe_samples expects.

    stt._write_wav dumps ``samples.tobytes()`` under a 16-bit WAV header, so a
    float array here would be written as raw float32 and decode to noise.
    """
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
        chunks = [
            out.to_ndarray().reshape(-1)
            for frame in container.decode(container.streams.audio[0])
            for out in resampler.resample(frame)
        ]
    return np.concatenate(chunks).astype(np.int16)


def edit_distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int, int, int]:
    """Unit-cost Levenshtein between two word lists.

    Returns (errors, substitutions, deletions, insertions, len(ref)). Each cell keeps the
    counts of its cheapest alignment, so the three kinds always add up to the total,
    including the edges where only one kind of edit is possible.
    """
    previous = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        current = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                current.append(previous[j - 1])
                continue
            diag, up, left = previous[j - 1], previous[j], current[j - 1]
            current.append(
                min(
                    (diag[0] + 1, diag[1] + 1, diag[2], diag[3]),  # substitution
                    (up[0] + 1, up[1], up[2] + 1, up[3]),  # deletion
                    (left[0] + 1, left[1], left[2], left[3] + 1),  # insertion
                    key=lambda c: c[0],
                )
            )
        previous = current
    errors, subs, dels, ins = previous[-1]
    return errors, subs, dels, ins, len(ref)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 = весь сплит")
    args = parser.parse_args()

    tsv = CORPUS / "test.tsv"
    audio_dir = CORPUS / "test"
    if not tsv.is_file() or not audio_dir.is_dir():
        raise SystemExit("нет FLEURS, скачайте: benchmarks/fetch_fleurs.sh")

    rows = [line.rstrip("\n").split("\t") for line in tsv.read_text(encoding="utf-8").splitlines()[1:]]
    rows = [r for r in rows if len(r) >= 3]
    if args.limit:
        rows = rows[: args.limit]

    stt = Stt(config.GIGAAM_DIR, threads=config.INFERENCE_THREADS)
    total_words = errors = 0
    substitutions = deletions = insertions = 0
    audio_seconds = 0.0
    worst: list[tuple[float, str, str]] = []

    started = time.perf_counter()
    for row in rows:
        path = audio_dir / row[1]
        if not path.is_file():
            continue
        samples = load(path)
        audio_seconds += samples.size / TARGET_SAMPLE_RATE
        reference = normalise(row[2])
        hypothesis = normalise(stt.transcribe_samples(samples))
        clip_errors, sub, dele, ins, words = edit_distance(reference, hypothesis)
        substitutions += sub
        deletions += dele
        insertions += ins
        total_words += words
        errors += clip_errors
        if words and clip_errors / words > 0.5:
            worst.append((clip_errors / words, " ".join(reference), " ".join(hypothesis)))
    elapsed = time.perf_counter() - started

    print(f"клипов: {len(rows)}, аудио: {audio_seconds / 60:.1f} мин")
    print(f"USE_COREML={config.USE_COREML}, провайдеры: {config.ort_providers()}")
    print()
    print(f"слов в эталоне: {total_words}")
    print(f"замен: {substitutions}  удалений: {deletions}  вставок: {insertions}")
    print(f"WER: {100 * errors / max(total_words, 1):.2f}%")
    print(f"время: {elapsed:.1f} с, реальный фактор {elapsed / max(audio_seconds, 1):.3f}")

    if worst:
        print()
        print("худшие случаи (WER больше 50%):")
        for rate, ref, hyp in sorted(worst, reverse=True)[:5]:
            print(f"  {rate * 100:.0f}%")
            print(f"    эталон: {ref[:110]}")
            print(f"    модель: {hyp[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())