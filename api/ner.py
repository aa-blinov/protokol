"""PII NER on CPU for ``lockR/rubert-base-pii-ner-onnx``.

The upstream ``pii_ner.py`` shipped with the model is CUDA-only: its
``OnnxBackend`` refuses to start without the CUDA provider. The graphs are
ordinary BERT token-classification graphs, so this module runs the same
``model.optimized.fp32.onnx`` on CPUExecutionProvider and keeps upstream's
windowing and span decoding unchanged.

Window/decoding helpers are adapted from ``lockR/rubert-base-pii-ner-onnx``
(Apache-2.0, Red Mad Robot R&D) so results match the reported benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

import config
from masking import Span

INPUT_NAMES = ("input_ids", "attention_mask", "token_type_ids")
MAX_LENGTH = 512
STRIDE = 128
MIN_CONFIDENCE = 0.3


def resolve_window_overlaps(entities: list[dict]) -> list[dict]:
    """Resolve conflicts between overflow windows: longest span, then confidence."""
    if not entities:
        return []
    ordered = sorted(entities, key=lambda item: item["start"])
    resolved, previous = [], ordered[0]
    for item in ordered[1:]:
        if item["start"] < previous["end"]:
            length = item["end"] - item["start"]
            previous_length = previous["end"] - previous["start"]
            if length > previous_length or (length == previous_length and item["score"] > previous["score"]):
                previous = item
        else:
            resolved.append(previous)
            previous = item
    resolved.append(previous)
    return resolved


def decode_window(text: str, offsets, logits, id2label: dict[int, str], min_confidence: float = MIN_CONFIDENCE):
    # Float32 softmax so aggregation is identical on every numeric backend.
    logits = np.asarray(logits, dtype=np.float32)
    shifted = logits - logits.max(axis=-1, keepdims=True)
    probabilities = np.exp(shifted)
    probabilities /= probabilities.sum(axis=-1, keepdims=True)
    ids = logits.argmax(axis=-1)
    confidences = probabilities[np.arange(len(ids)), ids]
    entities, current = [], None

    def flush():
        nonlocal current
        if current:
            current["score"] = float(np.mean(current.pop("_scores")))
            if current["score"] >= min_confidence:
                entities.append(current)
            current = None

    for (start, end), label_id, score in zip(offsets, ids, confidences):
        start, end = int(start), int(end)
        if end <= start:
            flush()
            continue
        label = id2label[int(label_id)]
        if label == "O":
            flush()
            continue
        prefix, kind = label.split("-", 1)
        if current and prefix == "I" and kind == current["label"]:
            current["end"] = end
            current["_scores"].append(float(score))
        else:
            flush()
            current = {"start": start, "end": end, "label": kind, "_scores": [float(score)]}
    flush()
    return entities


def window_starts(n_tokens: int, window: int = MAX_LENGTH - 2, step: int | None = None) -> list[int]:
    """Token offsets of the sliding windows that cover ``n_tokens`` completely.

    The tokenizer's own ``return_overflowing_tokens`` is not trusted here: on
    transformers 5.19 it produced a second window shorter than the remaining
    text (722 tokens -> windows of 512 + 135, chars 0..1967 + 1469..1976), so
    everything past ~1976 chars was never classified and PII leaked unmasked.
    Computing the windows from the full token list guarantees the tail is
    covered. ``step`` defaults to ``window - STRIDE``.
    """
    if n_tokens <= 0:
        return []
    step = step if step is not None else window - STRIDE
    starts = list(range(0, n_tokens, step))
    # The last window must reach the final token; when the fixed step would
    # leave a tail shorter than `window`, extend the last window back instead
    # of adding a sliver.
    if len(starts) > 1 and starts[-1] + window > n_tokens:
        starts[-1] = max(0, n_tokens - window)
    return starts


class PiiNer:
    """Recognize PII spans. Construct once and reuse; ``predict`` is thread-safe."""

    def __init__(self, model_dir: str | Path, threads: int = 4, min_confidence: float = MIN_CONFIDENCE):
        self.model_dir = Path(model_dir)
        self.min_confidence = min_confidence
        for filename in ("config.json", "tokenizer.json", "tokenizer_config.json"):
            if not (self.model_dir / filename).is_file():
                raise FileNotFoundError(f"Missing model artifact: {self.model_dir / filename}")
        model_path = self.model_dir / "model.optimized.fp32.onnx"
        if not model_path.is_file():
            raise FileNotFoundError(f"Missing model artifact: {model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, local_files_only=True)
        model_config = json.loads((self.model_dir / "config.json").read_text(encoding="utf-8"))
        self.id2label = {int(k): v for k, v in model_config["id2label"].items()}

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.providers = config.ort_providers()
        self.session = ort.InferenceSession(str(model_path), options, providers=self.providers)
        self.active_provider = self.session.get_providers()[0]
        self.input_names = [item.name for item in self.session.get_inputs()]
        # ONNX sessions are safe to call concurrently, but the shared batching
        # path below is not; one request at a time keeps memory bounded on CPU.
        self._lock = Lock()

    def predict(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        # Full token list, no truncation: the windows are built from it below,
        # so no part of the text can fall outside them.
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        token_ids = encoded["input_ids"]
        token_offsets = encoded["offset_mapping"]
        cls_id, sep_id = self.tokenizer.cls_token_id, self.tokenizer.sep_token_id
        window = MAX_LENGTH - 2

        raw: list[dict] = []
        with self._lock:
            for start in window_starts(len(token_ids), window):
                chunk_ids = token_ids[start : start + window]
                chunk_offsets = token_offsets[start : start + window]
                input_ids = [cls_id, *chunk_ids, sep_id]
                # [CLS]/[SEP] carry offset (0, 0), which decode_window drops.
                offsets = [(0, 0), *chunk_offsets, (0, 0)]
                features = {
                    "input_ids": np.asarray([input_ids], dtype=np.int64),
                    "attention_mask": np.ones((1, len(input_ids)), dtype=np.int64),
                    "token_type_ids": np.zeros((1, len(input_ids)), dtype=np.int64),
                }
                features = {name: features[name] for name in self.input_names}
                if "token_type_ids" not in features:
                    features["token_type_ids"] = np.zeros_like(features["input_ids"])
                logits = self.session.run(["logits"], features)[0]
                raw.extend(decode_window(text, offsets, logits[0, : len(offsets)], self.id2label, self.min_confidence))

        spans = [
            Span(start=item["start"], end=item["end"], label=item["label"], score=item["score"])
            for item in resolve_window_overlaps(raw)
        ]
        # Drop any span whose offsets drifted, so masking can never index out of bounds.
        return [span for span in spans if 0 <= span.start < span.end <= len(text)]
