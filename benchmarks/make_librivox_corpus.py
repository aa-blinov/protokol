"""Build a two-speaker file out of two real LibriVox readers, with ground truth.

Synthetic voices cannot answer whether diarization survives real humans, so this
uses recordings of actual readers. Both books are public domain:

  - Tolstoy, "Childhood"  -- read by Valery Yakovlev
  - Leskov, "Yuletide stories" -- read by Mark Chulsky

Each source is trimmed to a stretch of speech and the pieces are stitched in an
A/B/A/B order, so the diarizer has to find three speaker changes in a row. The
readers never overlap, which is what the DER in benchmarks/der.py expects.

Run: .venv/bin/python benchmarks/make_librivox_corpus.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import av
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
CORPUS = HERE / "corpus" / "librivox"
RATE = 16_000
GAP = 0.4  # seconds of silence between the pieces

# (file, reader, seconds to keep)
PIECES = [
    ("yakovlev_08_yigry.mp3", "Yakovlev", 150.0),
    ("yuletidestories_11_leskov_64kb.mp3", "Chulsky", 150.0),
    ("yakovlev_26_derevnya.mp3", "Yakovlev", 90.0),
    ("yuletidestories_11_leskov_64kb.mp3", "Chulsky", 90.0),
]


def decode(path: Path) -> np.ndarray:
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        chunks = [
            out.to_ndarray().reshape(-1)
            for frame in container.decode(container.streams.audio[0])
            for out in resampler.resample(frame)
        ]
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def trim_to_speech(audio: np.ndarray, seconds: float) -> np.ndarray:
    """Cut `seconds` of actual speech, skipping the long LibriVox intros."""
    frame = int(0.02 * RATE)
    count = audio.size // frame
    energy = np.array(
        [np.sqrt(np.mean(audio[i * frame : (i + 1) * frame] ** 2)) for i in range(count)]
    )
    threshold = energy.max() * 0.02
    voiced = np.flatnonzero(energy > threshold)
    if voiced.size == 0:
        raise RuntimeError("тишина в файле")
    start = voiced[0] * frame
    return audio[start : start + int(seconds * RATE)]


def main() -> int:
    audio_parts: list[np.ndarray] = []
    truth: list[dict] = []
    gap = np.zeros(int(GAP * RATE), dtype=np.float32)
    cursor = 0.0

    for name, reader, seconds in PIECES:
        path = CORPUS / name
        if not path.is_file():
            print(f"нет {path.name}, пропускаю")
            continue
        piece = trim_to_speech(decode(path), seconds)
        if audio_parts:
            audio_parts.append(gap)
            cursor += GAP
        audio_parts.append(piece)
        truth.append(
            {
                "start": round(cursor, 3),
                "end": round(cursor + piece.size / RATE, 3),
                "speaker": reader,
            }
        )
        cursor += piece.size / RATE

    audio = np.concatenate(audio_parts).astype(np.float32)
    np.save(CORPUS / "two_readers.npy", audio)
    (CORPUS / "two_readers.truth.json").write_text(
        json.dumps(truth, ensure_ascii=False), encoding="utf-8"
    )
    print(f"длительность: {audio.size / RATE:.1f} с")
    for item in truth:
        print(
            f"  {item['start']:7.1f}–{item['end']:7.1f} с  {item['speaker']}"
        )
    speakers = {item["speaker"] for item in truth}
    print(f"читателей: {len(speakers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())