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


def edit_distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int, int]:
    """Levenshtein with substitution=2, insertion/deletion=1; returns counts."""
    previous = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        current = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                current.append(previous[j - 1])
            else:
                best = min(
                    previous[j - 1],  # substitution
                    previous[j],  # deletion
                    current[j - 1],  # insertion
                    key=lambda c: c[0],
                )
                current.append((best[0] + 1, best[1] + 1, best[2], best[3]))
        previous = current
    _, subs, dels, ins = previous[-1]
    return subs, dels, ins, len(ref)


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
        sub, dele, ins, words = edit_distance(reference, hypothesis)
        substitutions += sub
        deletions += dele
        insertions += ins
        total_words += words
        errors += sub + dele + ins
        if words and (sub + dele + ins) / words > 0.5:
            worst.append(((sub + dele + ins) / words, " ".join(reference), " ".join(hypothesis)))
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