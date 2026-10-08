"""Deterministic recognizers for structured PII, layered under the NER model.

The model card for the NER model this app uses reports its own weak spots:
IP_ADDRESS F1 0.36, INN 0.68, SNILS 0.79, PASSPORT 0.81 — and the model's
authors recover a large part of that with a rule layer on top (their pipeline
scores 88.9 F1 against 83.6 for the model alone). A missed identifier is exactly
the leak this product exists to prevent, so these recognizers cover the
machine-checkable types with regular expressions and checksums: high recall by
construction, no model, no CPU cost worth mentioning.

They only ever *add* spans. Masking too much is a small annoyance; masking too
little is a defect, so where a rule is unsure it still masks.
"""

from __future__ import annotations

import re

from masking import Span

# A number with optional grouping separators: starts at a digit, then 9..18 more
# digits each optionally preceded by one space/dot/paren/dash. Covers phones
# written "8 (912) 345-67-89", cards "4111 1111 1111 1111", bare INN/SNILS.
_NUMBER_RE = re.compile(r"\d(?:[\s().-]*\d){9,18}")
# Reject a following octet (".5" or "5") so a longer dotted run is not split,
# but allow a sentence-ending period after the last octet.
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)")
# Passport: series (2+2) and number (6). A separator before the number is
# required, so a bare ten-digit run is never read as a passport.
_PASSPORT_RE = re.compile(r"(?<![\d])\d{2}\s?\d{2}[\s-]\d{6}(?![\d])")


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _inn_valid(digits: str) -> bool:
    if len(digits) == 10:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        check = sum(int(digits[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(digits[9])
    if len(digits) == 12:
        weights11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        check11 = sum(int(digits[i]) * weights11[i] for i in range(10)) % 11 % 10
        if check11 != int(digits[10]):
            return False
        weights12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        check12 = sum(int(digits[i]) * weights12[i] for i in range(11)) % 11 % 10
        return check12 == int(digits[11])
    return False


def _snils_valid(digits: str) -> bool:
    if len(digits) != 11:
        return False
    total = sum(int(digits[i]) * (9 - i) for i in range(9))
    if total < 100:
        check = total
    elif total in (100, 101):
        check = 0
    else:
        check = total % 101
    if check == 100:
        check = 0
    return check == int(digits[9:11])


def _ipv4_valid(match: str) -> bool:
    return all(part.isdigit() and 0 <= int(part) <= 255 for part in match.split("."))


def _free(start: int, end: int, claimed: list[tuple[int, int]]) -> bool:
    return not any(start < c_end and c_start < end for c_start, c_end in claimed)


def _number_spans(text: str, claimed: list[tuple[int, int]]) -> list[Span]:
    spans: list[Span] = []
    for match in _NUMBER_RE.finditer(text):
        start, end = match.start(), match.end()
        if not _free(start, end, claimed):
            continue
        digits = re.sub(r"\D", "", match.group())
        length = len(digits)
        label: str | None = None
        if length == 11 and digits[0] in "78":
            label = "PHONE"
        elif length == 10 and digits[0] == "9":
            label = "PHONE"
        elif length == 10 and _inn_valid(digits):
            label = "INN"
        elif length == 12 and _inn_valid(digits):
            label = "INN"
        elif length == 11 and _snils_valid(digits):
            label = "SNILS"
        elif 13 <= length <= 19 and _luhn(digits):
            label = "CREDIT_CARD"
        elif length == 16:
            # 16 digits that fail Luhn: a medical-insurance policy number is the
            # likely reading and masking it is safe, so it is not left out.
            label = "OMS"
        if label is not None:
            spans.append(Span(start=start, end=end, label=label, score=1.0))
            claimed.append((start, end))
    return spans


def find_structured(text: str) -> list[Span]:
    """Return spans for structured PII found by rule, not by the model."""
    claimed: list[tuple[int, int]] = []
    spans: list[Span] = []

    for match in _IPV4_RE.finditer(text):
        if _ipv4_valid(match.group()):
            spans.append(Span(start=match.start(), end=match.end(), label="IP_ADDRESS", score=1.0))
            claimed.append((match.start(), match.end()))

    for match in _PASSPORT_RE.finditer(text):
        if _free(match.start(), match.end(), claimed):
            spans.append(Span(start=match.start(), end=match.end(), label="PASSPORT", score=1.0))
            claimed.append((match.start(), match.end()))

    spans += _number_spans(text, claimed)
    return spans
