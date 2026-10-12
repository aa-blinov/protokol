"""Does masking still hold when the text comes from speech recognition?

Everything measured so far fed the masking layer typed text. The real path is
audio -> GigaAM -> text -> mask, and the recogniser can mangle a number into
something the rules no longer recognise. This speaks the identifiers aloud, runs
the recogniser, and then checks whether any of them survive into the masked
text.

Run: .venv/bin/python benchmarks/run_dictation_leak.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
from main import _spans  # noqa: E402
from masking import mask  # noqa: E402
from stt import Stt, TARGET_SAMPLE_RATE  # noqa: E402

# Read the way a person on a call would: numbers digit by digit, the way
# dictated Russian handles identity numbers in practice.
CASES = [
    ("ИНН", "сто ноль ноль ноль ноль ноль ноль ноль ноль ноль семь четыре", "100000000074"),
    ("карта", "четыре два семь шесть три восемь ноль ноль один два три четыре пять шесть семь девять", "4276380012345679"),
    ("паспорт", "серия четыре пять ноль восемь номер один два три четыре пять шесть", "4508123456"),
    ("телефон", "плюс семь девятьсот шестнадцать четыреста сорок восемь двадцать два ноль девять", "79164482209"),
]


def speak(text: str, voice: str = "Milena") -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
        subprocess.run(
            ["say", "-v", voice, "-r", "170", "--data-format=LEI16@16000", "-o", handle.name, text],
            check=True,
            capture_output=True,
        )
        with av.open(handle.name) as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
            chunks = [
                out.to_ndarray().reshape(-1)
                for frame in container.decode(container.streams.audio[0])
                for out in resampler.resample(frame)
            ]
    return np.concatenate(chunks).astype(np.int16)


def main() -> int:
    stt = Stt(config.GIGAAM_DIR, threads=config.INFERENCE_THREADS)
    leaks = 0
    print(f"модель: {config.GIGAAM_DIR.name}, провайдеры: {config.ort_providers()}\n")
    for name, spoken, expected in CASES:
        samples = speak(spoken)
        transcript = stt.transcribe_samples(samples)
        result = mask(transcript, _spans(transcript))

        digits_in = [d for d in expected]
        survived = [d for d in digits_in if d in result.masked_text]
        full_present = expected in transcript
        # A leak is any surviving run of four or more digits from the identifier.
        runs = [r for r in __import__("re").findall(r"\d{4,}", result.masked_text) if r in expected]

        verdict = "УТЕЧКА" if runs else "закрыто"
        leaks += bool(runs)
        print(f"--- {name}")
        print(f"    распознано: {transcript[:110]}")
        print(f"    замаскировано: {result.masked_text[:110]}")
        print(f"    исходное число целиком в тексте: {full_present}")
        print(f"    уцелевшие куски по 4+ цифр: {runs or 'нет'}  →  {verdict}")
        print()

    print(f"итого утечек: {leaks} из {len(CASES)}")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())