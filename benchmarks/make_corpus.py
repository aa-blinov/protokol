"""Build a multi-speaker corpus with ground truth, using macOS built-in voices.

There are no recordings in this repo, so diarization benchmarks need speech. The
`say` voices are synthetic and clean, so scores here are a smoke test, not a
stand-in for DER on real calls -- the point is to have *known* speaker turns to
measure against, which nothing else here provides.

A caveat worth keeping in mind: the embedding model is CAM++ zh-en
(campplus_zh_en), so Russian text is out of its training distribution. That is
the subject of hypothesis 7, not a reason to hide it from the results.

Run: .venv/bin/python benchmarks/make_corpus.py
"""

from __future__ import annotations

import tempfile
import json
import subprocess
import sys
from pathlib import Path

import av
import numpy as np

RATE = 16000
OUT = Path(__file__).resolve().parent / "corpus"

# Milena is the only ru_RU voice on the machine, so the other speakers come from
# other locales. Diarization keys on timbre, not language; the Russian one keeps
# at least one speaker inside the model's intended domain.
VOICES = {"A": "Milena", "B": "Daniel", "C": "Ralph"}

SCRIPT: list[tuple[str, str]] = [
    ("A", "Добрый день. Давайте начнём обсуждение отчётности за третий квартал."),
    ("B", "Good afternoon. I have reviewed the quarterly numbers you sent."),
    ("A", "Хорошо. Основная проблема в том, что расходы выросли почти вдвое."),
    ("B", "That is a large jump. Which department drove most of the increase?"),
    ("C", "I can answer that. The infrastructure line is the biggest single item."),
    ("B", "Thank you. Can you send the breakdown before Friday?"),
    ("A", "Конечно. Я попрошу бухгалтерию подготовить детализацию до среды."),
    ("C", "I will prepare the infrastructure part and send it separately."),
    ("B", "That works. Let us reconvene on Thursday to close this out."),
    ("A", "Договорились. Я разошлю приглашение всем участникам сегодня."),
]


def render(voice: str, text: str) -> np.ndarray:
    """One utterance as mono 16 kHz float samples in [-1, 1]."""
    # `say` refuses to write to stdout ("Opening output file failed: fmt?"),
    # so it renders to a temp file that is decoded and thrown away.
    with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
        subprocess.run(
            [
                "say",
                "-v",
                voice,
                "-r",
                "170",
                "--data-format=LEI16@16000",
                "-o",
                handle.name,
                text,
            ],
            capture_output=True,
            check=True,
        )
        with av.open(handle.name) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            chunks = [
                out.to_ndarray().reshape(-1)
                for frame in container.decode(container.streams.audio[0])
                for out in resampler.resample(frame)
            ]
    if not chunks:
        raise RuntimeError(f"no audio rendered for voice {voice}")
    samples = np.concatenate(chunks).astype(np.float32) / 32768.0
    return samples


def build(gap_seconds: float = 0.35) -> tuple[np.ndarray, list[dict]]:
    """Concatenate the script with silences, returning samples and ground truth."""
    rng = np.random.default_rng(0)
    gap = np.zeros(int(gap_seconds * RATE), dtype=np.float32)
    audio: list[np.ndarray] = []
    truth: list[dict] = []
    for index, (speaker, text) in enumerate(SCRIPT):
        chunk = render(VOICES[speaker], text)
        start = sum(part.size for part in audio) / RATE
        audio.append(chunk)
        truth.append(
            {"start": round(start, 3), "end": round(start + chunk.size / RATE, 3), "speaker": speaker}
        )
        if index != len(SCRIPT) - 1:
            audio.append(gap)
    samples = np.concatenate(audio)
    # A whisper of room noise, otherwise the segmentation model sees an unnaturally
    # clean floor and the benchmark is easier than any real call.
    samples = samples + rng.normal(0.0, 0.0006, samples.size).astype(np.float32)
    return np.clip(samples, -1.0, 1.0), truth


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    samples, truth = build()
    np.save(OUT / "call_2spk.npy", samples)
    (OUT / "call_2spk.truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    print(f"записано: {OUT / 'call_2spk.npy'}")
    print(f"длительность: {samples.size / RATE:.1f} с")
    print(f"реплик с разметкой: {len(truth)}, спикеров: {len({t['speaker'] for t in truth})}")

    # A longer take for the timing hypothesis: the same conversation repeated,
    # which gives a realistic turn count without hour-long rendering. 81 repeats
    # puts it just over an hour, the length hypothesis 5 asks to measure.
    base_minutes = samples.size / RATE / 60
    repeats = round(60 / base_minutes) + 1
    long_audio = np.concatenate([samples] * repeats)
    np.save(OUT / "call_long.npy", long_audio)
    print(f"длинный вариант: {repeats} повторов -> {long_audio.size / RATE / 60:.1f} мин")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())