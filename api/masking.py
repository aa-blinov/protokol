"""PII masking: entity spans -> stable placeholder tokens, plus faithful reversal.

Placeholders are bracketed (``[PERSON_1]``) so a language model preserves them
verbatim and so ordinary prose cannot be mistaken for a token. ``entity_map`` is
keyed by the *exact* surface string of the span, which keeps the round trip
lossless: unmasking restores the original characters byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Model labels -> display types shown in the UI. Adjacent spans that share a
# display type are merged, so "Иван Петров" (FIRST_NAME + LAST_NAME) becomes one
# placeholder rather than two.
DISPLAY_TYPE: dict[str, str] = {
    "FIRST_NAME": "PERSON",
    "LAST_NAME": "PERSON",
    "MIDDLE_NAME": "PERSON",
    "COUNTRY": "ADDRESS",
    "REGION": "ADDRESS",
    "DISTRICT": "ADDRESS",
    "CITY": "ADDRESS",
    "STREET": "ADDRESS",
    "HOUSE": "ADDRESS",
    "CREDIT_CARD": "CARD",
    "IP_ADDRESS": "IP",
}

# Entity types the UI renders with a distinct colour. Anything unknown falls back
# to a neutral chip, so a new model label never breaks the view.
KNOWN_TYPES: frozenset[str] = frozenset(DISPLAY_TYPE.values()) | {
    "EMAIL",
    "PHONE",
    "URL",
    "PASSPORT",
    "INN",
    "SNILS",
    "OMS",
    "DRIVER_LICENSE",
    "MILITARY_ID",
    "BIRTH_CERTIFICATE",
}


# Spans of one display type merge when only formatting separates them. Comma
# separated address parts ("Москва, улица Тверская, дом 12") are a single
# address, so they mask as one token. When this over-merges two people
# ("Иван, Пётр") it errs on the safe side: it hides more, never less. A word or
# a sentence period between spans keeps them separate.
_JOIN_GAP = re.compile(r"[\s,;:]*\Z")


@dataclass(frozen=True)
class Span:
    """A detected entity in the original text. ``end`` is exclusive."""

    start: int
    end: int
    label: str
    score: float

    @property
    def display_type(self) -> str:
        return DISPLAY_TYPE.get(self.label, self.label)


@dataclass(frozen=True)
class MaskedEntity:
    """A placeholder in the masked text, back-referenceable to the original."""

    token: str
    type: str
    label: str
    start: int
    end: int
    text: str
    score: float


@dataclass(frozen=True)
class MaskResult:
    masked_text: str
    entity_map: dict[str, str]
    entities: list[MaskedEntity]


def merge_spans(text: str, spans: list[Span]) -> list[Span]:
    """Merge overlapping or whitespace-adjacent spans that share a display type.

    Scoring follows the upstream NER runtime: the merged span keeps the highest
    confidence of its parts.
    """
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if span.end <= span.start:
            continue
        if merged:
            prev = merged[-1]
            gap = text[prev.end : span.start]
            same_type = prev.display_type == span.display_type
            touching = span.start <= prev.end or _JOIN_GAP.match(gap) is not None
            if same_type and touching:
                merged[-1] = Span(
                    start=prev.start,
                    end=max(prev.end, span.end),
                    label=prev.label,
                    score=max(prev.score, span.score),
                )
                continue
        merged.append(span)
    return merged


def mask(text: str, spans: list[Span]) -> MaskResult:
    """Replace every span with a ``[TYPE_n]`` token and return the reverse map.

    Counters run per display type and are assigned in order of first appearance.
    The same surface string always maps to the same token, so a repeated name
    stays consistent throughout the text.
    """
    merged = merge_spans(text, spans)
    counters: dict[str, int] = {}
    known: dict[str, str] = {}
    pieces: list[str] = []
    entities: list[MaskedEntity] = []
    cursor = 0

    for span in merged:
        surface = text[span.start : span.end]
        entity_type = span.display_type
        token = known.get(surface)
        if token is None:
            counters[entity_type] = counters.get(entity_type, 0) + 1
            token = f"{entity_type}_{counters[entity_type]}"
            known[surface] = token
        pieces.append(text[cursor : span.start])
        pieces.append(f"[{token}]")
        cursor = span.end
        entities.append(
            MaskedEntity(
                token=token,
                type=entity_type,
                label=span.label,
                start=span.start,
                end=span.end,
                text=surface,
                score=span.score,
            )
        )
    pieces.append(text[cursor:])

    entity_map = {entity.token: entity.text for entity in entities}
    return MaskResult("".join(pieces), entity_map, entities)


def unmask(text: str, entity_map: dict[str, str]) -> str:
    """Substitute every placeholder back to its original surface string.

    Brackets are optional on the way back: a model that drops them still round
    trips. The word guards stop a short token from matching inside a longer one
    (``[PERSON_1]`` must not corrupt ``[PERSON_12]``).
    """
    if not entity_map:
        return text
    alternatives = "|".join(re.escape(token) for token in sorted(entity_map, key=len, reverse=True))
    pattern = re.compile(rf"\[?\b({alternatives})\b\]?")
    return pattern.sub(lambda match: entity_map[match.group(1)], text)
