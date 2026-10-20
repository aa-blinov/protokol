"""Measure the masking stack against the Russian PII benchmark.

redmadrobot-rnd/pii_benchmark (MIT) is the evaluation set behind the model card
we ship: 2,841 Russian sentences, 5,614 entities, 21 types. Its authors publish
83.6 F1 for the model alone and 88.9 for their rules+model pipeline, so this
gives a number to compare against instead of a feeling.

Reported twice: the model alone, and the model plus our deterministic rules,
which is what the app actually runs.

Run: .venv/bin/python benchmarks/run_pii_benchmark.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
import main as pipeline  # noqa: E402
from ner import PiiNer  # noqa: E402

CSV_PATH = HERE / "corpus" / "pii_bench" / "test.csv"
# The app folds the model's fine-grained address and name labels into coarser
# ones. Matching the benchmark means folding the gold spans the same way.
FOLD = {
    "FIRST_NAME": "PERSON",
    "MIDDLE_NAME": "PERSON",
    "LAST_NAME": "PERSON",
    "CITY": "LOCATION",
    "REGION": "LOCATION",
    "COUNTRY": "LOCATION",
    "DISTRICT": "LOCATION",
    "STREET": "LOCATION",
    "HOUSE": "LOCATION",
    "PERSON": "PERSON",
}


def load_rows(limit: int = 0) -> list[tuple[str, list[tuple[int, int]], list[str]]]:
    """Rebuild the benchmark as (text, token offsets, gold label per token).

    Two things make span-level scoring misleading here, so this scores per token
    instead -- the model is a token classifier and the gold is BIO-tagged, so
    token-level F1 is the metric the model card's numbers come from. The gold
    spans carry trailing punctuation ("info@sunlight.ru." with the dot) and the
    model splits some numbers in half, so exact span boundaries disagree with
    the gold on inputs where both are right.
    """
    rows: list[tuple[str, list[tuple[int, int]], list[str]]] = []
    with CSV_PATH.open(encoding="utf-8") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if limit and index >= limit:
                break
            text = row["text"]
            tokens = json.loads(row["tokens"])
            tags = json.loads(row["ner_tags"])
            spans: list[tuple[int, int]] = []
            cursor = 0
            for token in tokens:
                position = text.find(token, cursor)
                if position < 0:
                    spans = []
                    break
                spans.append((position, position + len(token)))
                cursor = position + len(token)
            if not spans:
                continue
            labels = ["O"] * len(tokens)
            active: str | None = None
            for index_, (tag, token_span) in enumerate(zip(tags, spans)):
                tag = tag or "O"
                if tag == "O":
                    active = None
                    continue
                kind = FOLD.get(tag[2:], tag[2:])
                if tag.startswith("B-") or active is None:
                    active = kind
                labels[index_] = active
            rows.append((text, spans, labels))
    return rows


def score(rows, preds) -> dict:
    """Token-level micro P/R/F1 over non-O tokens, plus per-label."""
    per_label = defaultdict(lambda: [0, 0, 0])
    total = [0, 0, 0]
    for (_text, spans, gold), pred_spans in zip(rows, preds):
        predicted = ["O"] * len(spans)
        for start, end, label in pred_spans:
            best = 0
            best_label = None
            for index, (token_start, token_end) in enumerate(spans):
                overlap = min(end, token_end) - max(start, token_start)
                if overlap > best:
                    best = overlap
                    best_label = label
            if best_label is None:
                continue
            for index, (token_start, token_end) in enumerate(spans):
                if min(end, token_end) > max(start, token_start):
                    predicted[index] = best_label
        for gold_label, pred_label in zip(gold, predicted):
            if gold_label == "O" and pred_label == "O":
                continue
            bucket = gold_label if gold_label != "O" else pred_label
            if gold_label == pred_label and gold_label != "O":
                per_label[bucket][0] += 1
                total[0] += 1
            elif pred_label != "O":
                per_label[bucket][1] += 1
                total[1] += 1
            else:
                per_label[gold_label][2] += 1
                total[2] += 1

    def prf(counts):
        tp, fp, fn = counts
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return precision, recall, f1

    return {"per_label": per_label, "total": total, "prf": prf}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not CSV_PATH.is_file():
        raise SystemExit(f"нет {CSV_PATH}, скачайте redmadrobot-rnd/pii_benchmark/test.csv")

    rows = load_rows(args.limit)
    entities = sum(sum(1 for label in labels if label != "O") for _, _, labels in rows)
    tokens = sum(len(labels) for _, _, labels in rows)
    print(f"предложений: {len(rows)}, токенов: {tokens}, сущностей (с эталонными метками): {entities}")
    print(f"провайдеры: {config.ort_providers()}")
    print()

    ner = PiiNer(config.PII_NER_DIR, threads=config.INFERENCE_THREADS)

    model_preds, full_preds = [], []
    started = time.perf_counter()
    for text, _spans, _gold in rows:
        model_spans = ner.predict(text)
        model_preds.append([(s.start, s.end, FOLD.get(s.label, s.label)) for s in model_spans])
        # What the app actually runs: model spans plus gap-filled rules.
        full_preds.append(
            [(s.start, s.end, FOLD.get(s.label, s.label)) for s in pipeline._spans(text)]
        )
    elapsed = time.perf_counter() - started

    for name, preds in (("только модель", model_preds), ("пайплайн (модель + gap-правила)", full_preds)):
        result = score(rows, preds)
        precision, recall, f1 = result["prf"](result["total"])
        print(f"{name:18s} precision {precision * 100:5.1f}%  recall {recall * 100:5.1f}%  F1 {f1 * 100:5.1f}%")

    print()
    print(f"время: {elapsed:.1f} с на {len(rows)} предложениях")

    published = {
        "PASSPORT": 81.3, "INN": 68.3, "SNILS": 78.5, "IP_ADDRESS": 36.0,
        "CREDIT_CARD": 87.9, "OMS": 90.1, "DRIVER_LICENSE": 81.8,
        "MILITARY_ID": 78.3, "BIRTH_CERTIFICATE": 83.7, "EMAIL": 97.6,
    }
    model_result = score(rows, model_preds)
    full_result = score(rows, full_preds)
    print()
    print("вклад слоя правил по типам (F1: модель -> пайплайн):")
    print(f"  {'тип':20s} {'модель':>8} {'пайплайн':>9} {'дельта':>8}")
    labels = sorted(
        set(model_result["per_label"]) | set(full_result["per_label"]),
        key=lambda k: -(full_result["per_label"][k][0] + full_result["per_label"][k][2]),
    )
    for label in labels:
        model_f1 = model_result["prf"](model_result["per_label"][label])[2]
        full_f1 = full_result["prf"](full_result["per_label"][label])[2]
        delta = (full_f1 - model_f1) * 100
        arrow = "+" if delta > 0.05 else ("-" if delta < -0.05 else " ")
        mark = f"   в карточке модели {published[label]:.1f}" if label in published else ""
        print(f"  {label:20s} {model_f1 * 100:>7.1f}% {full_f1 * 100:>8.1f}% {arrow}{delta:>7.1f}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
