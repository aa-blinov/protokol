"""Deterministic recognizers for identifiers, applied only where the model missed.

The previous rule layer ran unconditionally on top of the NER model. Measured on
redmadrobot-rnd/pii_benchmark that cost more than it bought: card -6.2 F1, phone
-2.2, OMS -1.5, because a rule span and a model span could land on the same number
under different labels and the conflict counted as both a hit and a miss.

The fix is not to delete the layer but to stop it from arguing with the model.
`fill_gaps` keeps a rule span only for the part of it the model did not already
cover, so:

  - a number the model found is left alone, with the model's own label;
  - a number the model split in half is completed by the rule;
  - a number the model missed entirely is picked up whole.

That is what catches identifiers in dictated speech, where the model is
unstable, without disturbing the clean-text cases it already gets right.
"""

from __future__ import annotations

import re

from masking import Span

# Rule spans carry no model confidence, so they sit at the bottom of the scale.
# It only ever matters where a rule and the model disagree about a label, and
# that case is now avoided by fill_gaps rather than decided by this number.
_RULE_SCORE = 0.0


def _span(start: int, end: int, label: str) -> Span:
    """A rule hit, built the same way the NER model builds its spans."""
    return Span(start=start, end=end, label=label, score=_RULE_SCORE)


def _luhn(digits: str) -> bool:
    """Luhn check over the whole number, check digit included.

    Walking right to left, the check digit is index 0 and is never doubled, so
    the digits that get doubled sit at odd indices.
    """
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
    """INN control sum. A 12-digit INN carries two check digits, not one."""
    if len(digits) == 10:
        first, second = (2, 4, 10, 3, 5, 9, 4, 6, 8), None
    elif len(digits) == 12:
        first, second = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8), (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    else:
        return False
    check_first = sum(int(digits[i]) * first[i] for i in range(len(first))) % 11 % 10
    if check_first != int(digits[len(first)]):
        return False
    if second is None:
        return True
    check_second = sum(int(digits[i]) * second[i] for i in range(len(second))) % 11 % 10
    return check_second == int(digits[-1])


def _snils_valid(digits: str) -> bool:
    total = sum(int(digits[i]) * (9 - i) for i in range(9))
    check = total if total < 100 else (0 if total in (100, 101) else total % 101)
    return check == int(digits[9:11])


# Series and number of a Russian passport. In speech they are separated by the
# word "номер", which the earlier pattern did not allow for; the optional group
# is what stops "серия 4508 номер 123456" from falling straight through to the
# model, which tags such numbers only partially.
_PASSPORT_RE = re.compile(
    r"\b(\d{2}\s?\d{2})\s*(?:№|no|n|номер)?\s*[-–—]?\s*(\d{6})\b",
    re.IGNORECASE,
)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DIGITS_RE = re.compile(r"\d+")
_SPACED_INN_RE = re.compile(r"\b(\d{3})[- ](\d{3})[- ](\d{3})\s?(\d{2,3})\b")
_SPACED_SNILS_RE = re.compile(r"\b(\d{3})[- ](\d{3})[- ](\d{3})\s?(\d{2})\b")
# Speech recognition breaks a dictated number into uneven groups: a card number
# comes out as "427 63800 1234 5679" rather than sixteen unbroken digits. The
# patterns above all expect one contiguous run, so without this a card dictated
# aloud is not masked at all. Measured on dictated audio, not assumed.
# Groups run to six digits: the recogniser emits "427 63800 1234 5679",
# and a five-digit group such as 63800 must not break the match.
_GROUPED_NUMBER_RE = re.compile(r"(?<![\d-])\d{1,6}(?: +\d{1,6}){2,}(?![\d-])")


def _valid_ipv4(text: str) -> bool:
    return all(0 <= int(part) <= 255 for part in text.split("."))


def _standalone_number(text: str, start: int) -> bool:
    """True when the digit run is a number in its own right.

    A run glued to a letter or a numero sign is part of something else: an
    order number like "AZ9876543210" is not a tax id, and it is exactly the kind
    of number the earlier version mislabelled. Requiring the word "ИНН" nearby
    was worse -- dictated speech arrives as "ИИН" or "и.н.н" often enough that
    the keyword could not be relied on.
    """
    if start == 0:
        return True
    previous = text[start - 1]
    return not (previous.isalpha() or previous in "№#")


def _says_inn(text: str, start: int) -> bool:
    """True when the speaker named the identifier right before the digits.

    Matched on letters alone: recognition writes this as "ИНН", "ИИН", "и.н.н"
    or "и н н", and an exact spelling cannot be relied on. Both "инн" and "иин"
    are accepted for the same reason -- a dropped letter is the common failure.
    """
    window = re.sub(r"[^\w]", "", text[max(0, start - 40) : start]).lower()
    return "инн" in window or "иин" in window


def find_candidates(text: str) -> list[Span]:
    """Every structured identifier in the text, validated by shape and checksum."""
    spans: list[Span] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return not any(start < other_end and other_start < end for other_start, other_end in taken)

    for match in _PASSPORT_RE.finditer(text):
        if free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "PASSPORT"))
            taken.append((match.start(), match.end()))

    for match in _IPV4_RE.finditer(text):
        if _valid_ipv4(match.group()) and free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "IP_ADDRESS"))
            taken.append((match.start(), match.end()))

    # Grouped spellings. The checksum still has to hold: "110 116 101 114" is a
    # column of character codes, not a tax id.
    for pattern, validator in ((_SPACED_INN_RE, _inn_valid), (_SPACED_SNILS_RE, _snils_valid)):
        for match in pattern.finditer(text):
            digits = re.sub(r"\D", "", match.group())
            if validator(digits) and free(match.start(), match.end()):
                spans.append(_span(match.start(), match.end(), "INN" if pattern is _SPACED_INN_RE else "SNILS"))
                taken.append((match.start(), match.end()))

    for match in _DIGITS_RE.finditer(text):
        digits = match.group()
        if not free(match.start(), match.end()):
            continue
        if len(digits) in (10, 12) and _inn_valid(digits):
            if _standalone_number(text, match.start()):
                spans.append(_span(match.start(), match.end(), "INN"))
        elif (
            9 <= len(digits) <= 19
            and _standalone_number(text, match.start())
            and _says_inn(text, match.start())
        ):
            # The speaker named a tax id, so mask it even though the digits
            # fail their checksum: a wrong checksum here usually means the
            # recogniser miscounted a digit, not that the number is harmless.
            spans.append(_span(match.start(), match.end(), "INN"))
        elif len(digits) == 11 and _snils_valid(digits):
            spans.append(_span(match.start(), match.end(), "SNILS"))
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            spans.append(_span(match.start(), match.end(), "CREDIT_CARD"))

    # Grouped readings, checked after the spaces are squeezed out. The checksum
    # is what keeps this from swallowing ordinary prose: "14 марта 2026 года"
    # and "4500 рублей" never add up to a valid card or tax id.
    for match in _GROUPED_NUMBER_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        digits = re.sub(r"\s", "", match.group())
        if len(digits) in (10, 12) and _inn_valid(digits):
            spans.append(_span(match.start(), match.end(), "INN"))
        elif 9 <= len(digits) <= 19 and _says_inn(text, match.start()):
            spans.append(_span(match.start(), match.end(), "INN"))
        elif len(digits) == 11 and _snils_valid(digits):
            spans.append(_span(match.start(), match.end(), "SNILS"))
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            spans.append(_span(match.start(), match.end(), "CREDIT_CARD"))
    return spans


def fill_gaps(text: str, model_spans: list, rule_spans: list[Span]) -> list[Span]:
    """Keep only the parts of each rule span the model did not already cover.

    A gap that holds no digits is dropped: it is the connector between two
    numbers -- the word "номер" between a passport series and its number -- and
    masking it would hide ordinary text while protecting nothing.
    """
    result: list[Span] = []
    for rule in rule_spans:
        cursor = rule.start
        for start, end in sorted((s.start, s.end) for s in model_spans):
            if end <= cursor:
                continue
            if start >= rule.end:
                break
            if start > cursor:
                result.extend(_gaps(cursor, min(start, rule.end), rule.label, text))
            cursor = max(cursor, end)
        if cursor < rule.end:
            result.extend(_gaps(cursor, rule.end, rule.label, text))
    return result


def _gaps(start: int, end: int, label: str, text: str) -> list[Span]:
    if any(char.isdigit() for char in text[start:end]):
        return [_span(start, end, label)]
    return []