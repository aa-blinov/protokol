"""How often the pipeline damages a name, not just how often it mishears words.

Headline WER is a poor proxy: research on speech NER repeatedly finds that errors
concentrated inside entity spans cost far more NER F1 than the same errors spread
across ordinary words. So this measures entity survival directly.

Ground truth comes from FLEURS, which ships the exact reference sentence for each
clip. A clip qualifies when the *clean reference* contains an entity -- otherwise
there is nothing to lose. Each clip is then put through the real pipeline and
the found entities are compared with the gold ones:

  found exactly     name survived intact
  fragmented        same name, split across two or more tokens
  mangled           token present but the text differs
  missed            gold name absent from the output
  spurious          output has a name that was never in the reference

Usage: .venv/bin/python benchmarks/measure_entity_damage.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import av  # noqa: E402
import config  # noqa: E402
from ner import PiiNer  # noqa: E402
from rules import fill_gaps, find_candidates  # noqa: E402
from stt import Stt, TARGET_SAMPLE_RATE  # noqa: E402

TSV = ROOT / "benchmarks" / "corpus" / "fleurs" / "test.tsv"
AUDIO = ROOT / "benchmarks" / "corpus" / "fleurs" / "test"
# Same display types as Highlight.tsx groups into one chip.
MERGEABLE = {"PERSON", "LOCATION", "ORGANIZATION"}


def load_samples(path: Path) -> np.ndarray:
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
        chunks = [
            out.to_ndarray().reshape(-1)
            for frame in container.decode(container.streams.audio[0])
            for out in resampler.resample(frame)
        ]
    return np.concatenate(chunks).astype(np.int16)


def display(label: str) -> str:
    if label in {"FIRST_NAME", "MIDDLE_NAME", "LAST_NAME"}:
        return "PERSON"
    if label in {"CITY", "REGION", "COUNTRY", "STREET", "HOUSE", "DISTRICT"}:
        return "LOCATION"
    return label


def spans(text: str, model: PiiNer, drop_regex: bool) -> list[tuple[str, str, str]]:
    """(type, surface, start) for every entity, NER plus gap-filled rules."""
    found = [(display(s.label), text[s.start : s.end], s.start) for s in model.predict(text)]
    if drop_regex:
        return found
    return found + [
        (display(s.label), text[s.start : s.end], s.start)
        for s in fill_gaps(text, model.predict(text), find_candidates(text))
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    # No header row: speaker_id, path, transcription, raw, phonemes, samples, gender.
    rows = [
        {"path": row[1], "transcription": row[2]}
        for row in csv.reader(TSV.open(encoding="utf-8"), delimiter="\t")
        if len(row) > 2
    ]
    model = PiiNer(config.PII_NER_DIR, threads=config.INFERENCE_THREADS)

    # Qualify on the clean reference: a clip counts only if a name is actually there.
    candidates = []
    for row in rows:
        gold = spans(row["transcription"], model, drop_regex=True)
        gold = [g for g in gold if g[0] in MERGEABLE]
        if gold:
            candidates.append((row, gold))
        if len(candidates) >= args.limit:
            break

    stt = Stt(config.GIGAAM_DIR, threads=config.INFERENCE_THREADS)
    tally = {"found": 0, "fragmented": 0, "mangled": 0, "missed": 0, "spurious": 0}
    gold_total = 0
    started = time.perf_counter()

    for row, gold in candidates:
        transcript = stt.transcribe_samples(load_samples(AUDIO / row["path"]))
        got = spans(transcript, model, drop_regex=False)
        gold_total += len(gold)
        used = set()
        for kind, surface, _ in gold:
            matches = [
                i
                for i, (k, s, _) in enumerate(got)
                if i not in used and k == kind and s == surface
            ]
            if matches:
                used.add(matches[0])
                tally["found"] += 1
                continue
            # A name cut in two shows up as two same-kind spans separated only by
            # space or a dash. Check every such pair, not each half separately.
            fragmented = []
            for i in range(len(got) - 1):
                if i in used or i + 1 in used:
                    continue
                if got[i][0] != kind or got[i + 1][0] != kind:
                    continue
                between = transcript[got[i][2] + len(got[i][1]) : got[i + 1][2]]
                if not re.fullmatch(r"[\s\-—]*", between):
                    continue
                joined = got[i][1] + between + got[i + 1][1]
                if re.sub(r"[\s\-—]", "", joined) == re.sub(r"[\s\-—]", "", surface):
                    fragmented = [i, i + 1]
                    break
            if fragmented:
                used.update(fragmented)
                tally["fragmented"] += 1
                continue
            if any(i not in used and k == kind for i, (k, _s, _p) in enumerate(got)):
                tally["mangled"] += 1
            else:
                tally["missed"] += 1
        tally["spurious"] += sum(1 for i in range(len(got)) if i not in used)

    total = gold_total
    print(f"клипов с сущностями в эталоне: {len(candidates)}")
    print(f"сущностей в эталоне: {total}")
    print(f"разобрано за {time.perf_counter() - started:.0f} с\n")
    print(f"{'исход':>12}  {'штук':>5}  {'доля':>7}")
    for key, label in (
        ("found", "уцелела"),
        ("fragmented", "разрезана"),
        ("mangled", "искажена"),
        ("missed", "потеряна"),
    ):
        share = tally[key] / total * 100 if total else 0
        print(f"{label:>12}  {tally[key]:>5}  {share:>6.1f}%")
    print(f"{'лишних':>12}  {tally['spurious']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
