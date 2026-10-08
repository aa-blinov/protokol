"""Checks for the NER sliding windows.

The windowing is pure token arithmetic and easy to get wrong: relying on the
tokenizer's own `return_overflowing_tokens` silently dropped the tail of the
text on transformers 5.19 (722 tokens -> 512 + 135, the last ~800 characters in
no window at all), so PII past that point reached OpenRouter unmasked. These
tests pin the coverage property that failure violated, without loading the
700 MB model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ner import MAX_LENGTH, STRIDE, resolve_window_overlaps, window_starts  # noqa: E402


def test_window_starts_cover_every_token():
    for n_tokens in (1, 100, 510, 511, 512, 513, 720, 1000, 5000):
        starts = window_starts(n_tokens)
        covered: set[int] = set()
        for start in starts:
            covered.update(range(start, min(start + MAX_LENGTH - 2, n_tokens)))
        assert covered == set(range(n_tokens)), f"uncovered tokens for n={n_tokens}"


def test_window_starts_empty_for_no_tokens():
    assert window_starts(0) == []


def test_window_starts_step_leaves_a_stride_overlap():
    starts = window_starts(2000)
    assert len(starts) >= 2
    assert starts[1] - starts[0] == (MAX_LENGTH - 2) - STRIDE


def test_resolve_window_overlaps_keeps_one_span_for_a_duplicate():
    # The same entity seen in two overlapping windows must collapse to one.
    spans = [
        {"start": 10, "end": 20, "label": "FIRST_NAME", "score": 0.9},
        {"start": 10, "end": 20, "label": "FIRST_NAME", "score": 0.8},
    ]
    resolved = resolve_window_overlaps(spans)
    assert len(resolved) == 1
    assert resolved[0]["score"] == 0.9
