"""Placeholders the model rewrites: the case it changes, and the words that only look like one.

A model sometimes lowercases the placeholders it copies. The value must still come back, and a
token the map cannot restore must be listed, not silently kept. A Latin word with a number in it
is not a placeholder at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import Span, mask, unknown_tokens, unmask  # noqa: E402


def find(text: str, needle: str, label: str) -> Span:
    start = text.index(needle)
    return Span(start=start, end=start + len(needle), label=label, score=1.0)


def test_lowercased_placeholder_is_restored():
    text = "телефон 89161234567 срочно"
    result = mask(text, [find(text, "89161234567", "PHONE")])
    assert unmask(result.masked_text.lower(), result.entity_map) == text


def test_lowercased_placeholder_the_map_lacks_is_listed():
    text = "телефон 89161234567 срочно"
    result = mask(text, [find(text, "89161234567", "PHONE")])
    assert unknown_tokens("телефон [phone_9] срочно", result.entity_map) == ["PHONE_9"]


def test_latin_word_with_a_number_is_not_a_placeholder():
    assert unknown_tokens("см. test_1 в файле", {}) == []
