"""Compare Russian NER models on one benchmark, so the comparison means something.

The project's own PiiNer is hard-wired to lockR/rubert-base-pii-ner. To put other
models on the same scale, this loads any BERT-family ONNX token-classification
model directly: tokenizer from `tokenizer.json`, logits from onnxruntime, spans
from offset mapping. No torch, no safetensors.

Everything is scored against redmadrobot-rnd/pii_benchmark with the same token-level
metric as run_pii_benchmark.py, and the label sets are folded to the benchmark's
coarse groups so a general NER model and a PII model are comparable.

Run: .venv/bin/python benchmarks/compare_ner_models.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(HERE))

import config  # noqa: E402
from run_pii_benchmark import FOLD, load_rows, score  # noqa: E402

CORPUS = HERE / "corpus" / "ner_models"

# Everything that must collapse onto the benchmark's own label groups.
EXTRA_FOLD = {
    # general-NER model label sets
    "PER": "PERSON", "PERSON": "PERSON",
    "LOC": "LOCATION", "GPE": "LOCATION", "GPE_LOC": "LOCATION",
    "GEOPOLIT": "LOCATION",
    "ORG": "ORGANIZATION", "ORGANIZATION": "ORGANIZATION",
    "ZIPCODE": "POSTCODE", "SETTLEMENT": "LOCATION", "DISTRICT": "LOCATION",
    "COUNTRY": "LOCATION", "STREET": "LOCATION", "HOUSE": "LOCATION",
    "MEDIA": "ORGANIZATION",
}
ALL_FOLD = {**FOLD, **EXTRA_FOLD}


class OnnxTokenTagger:
    """Minimal token-classification runner for an exported ONNX model."""

    def __init__(self, directory: Path, threads: int = 4):
        self.dir = directory
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=510)
        config_json = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        id2label = {int(k): v for k, v in config_json.get("id2label", {}).items()}
        self.id2label = id2label
        # onnx-community exports often put the labels only in the tokenizer config
        if not self.id2label:
            tokenizer_config = json.loads(
                (directory / "tokenizer_config.json").read_text(encoding="utf-8")
            )
            raw = tokenizer_config.get("id2label", {})
            self.id2label = {int(k): v for k, v in raw.items()} if raw else {}
        self.session = ort.InferenceSession(
            str(directory / "onnx" / "model.onnx"), providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}

    def predict(self, text: str, min_confidence: float = 0.0) -> list[tuple[int, int, str]]:
        encodings = self.tokenizer.encode(text)
        ids = encodings.ids
        if not ids:
            return []
        attention = np.array([encodings.attention_mask], dtype=np.int64)
        feed = {"input_ids": np.array([ids], dtype=np.int64), "attention_mask": attention}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.array([encodings.type_ids], dtype=np.int64)
        logits = self.session.run(None, feed)[0][0]
        probs = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs /= probs.sum(axis=-1, keepdims=True)

        spans: list[tuple[int, int, str]] = []
        start: int | None = None
        current = ""
        # Two tagging schemes appear here: plain BIO, and the B/I/U/L scheme used
        # by Gherman (U = a one-token entity, L = its final token).
        for index, (token_start, token_end) in enumerate(encodings.offsets):
            label = self.id2label.get(int(np.argmax(probs[index])), "O")
            if label in ("O", "") or float(probs[index].max()) < min_confidence:
                if start is not None:
                    spans.append((start, token_end, ALL_FOLD.get(current, current)))
                start, current = None, ""
                continue
            prefix, entity = label.split("-", 1) if "-" in label else ("O", "")
            if prefix == "U":
                spans.append((token_start, token_end, ALL_FOLD.get(entity, entity)))
                start, current = None, ""
            elif prefix == "B":
                if start is not None:
                    spans.append((start, token_end, ALL_FOLD.get(current, current)))
                start, current = token_start, entity
            elif prefix == "I" and start is not None:
                current = entity
            elif prefix == "L" and start is not None:
                current = entity
                spans.append((start, token_end, ALL_FOLD.get(current, current)))
                start, current = None, ""
            else:
                if start is not None:
                    spans.append((start, token_end, ALL_FOLD.get(current, current)))
                start, current = None, ""
        if start is not None:
            spans.append((start, int(encodings.offsets[-1][1]), ALL_FOLD.get(current, current)))
        return [s for s in spans if s[0] < s[1]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = load_rows(args.limit)
    print(f"предложений: {len(rows)}")
    print()

    candidates = {
        "ger_BertBase": "onnx-community/bert-base-NER-Russian-ONNX (Gherman, общий NER)",
        "rubert_tiny": "onnx-community/ner-rubert-tiny-news-ONNX (r1char9, общий NER)",
    }

    for name, description in candidates.items():
        directory = CORPUS / name
        if not (directory / "onnx" / "model.onnx").is_file():
            print(f"--- {name}: не скачана, пропускаю")
            continue
        model = OnnxTokenTagger(directory, threads=config.INFERENCE_THREADS)
        preds = []
        started = time.perf_counter()
        for text, _spans, _gold in rows:
            preds.append(model.predict(text))
        elapsed = time.perf_counter() - started

        result = score(rows, preds)
        precision, recall, f1 = result["prf"](result["total"])
        size = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
        print(f"--- {name}: {description}")
        print(
            f"    F1 {f1 * 100:5.1f}%  P {precision * 100:5.1f}%  R {recall * 100:5.1f}%  "
            f"вес {size / 1024 / 1024:.0f} МБ  {elapsed:.0f} с"
        )
        covered = {label for pred in preds for _, _, label in pred}
        print(f"    метки на данных: {', '.join(sorted(covered)) or '—'}")
        per = result["per_label"]
        top = sorted(per, key=lambda k: -per[k][2])[:6]
        for label in top:
            p, r, f = result["prf"](per[label])
            print(f"      {label:16s} F1 {f * 100:5.1f}%")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
