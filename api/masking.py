"""PII masking: entity spans -> stable placeholder tokens, plus faithful reversal.

Placeholders are bracketed (``[PERSON_1]``) so a language model preserves them
verbatim and so ordinary prose cannot be mistaken for a token.

Non-name entities are keyed by their exact surface string, so unmasking restores
them byte for byte. Names are keyed by person: "Ольга Николаевна", "Ольги
Николаевны Смирновой" and "Ольге Николаевне" are one placeholder (see names.py).
Their map value is the nominative form, and unmasking inflects it to the case the
model asks for with a tag: ``[PERSON_1|gen]``.
"""

import re
from dataclasses import dataclass

import names

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
    # Places the rules find after a preposition get the placeholder of the model's address parts.
    "LOCATION": "ADDRESS",
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
    "SECRET",
    "OGRNIP",
    "ORG_ID",
}


# Placeholder types a token can carry. A token whose type is none of these is an
# ordinary word with a number in it, not a placeholder the model invented.
_PLACEHOLDER_TYPES: frozenset[str] = KNOWN_TYPES | {"NUMBER"}


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


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Drop spans that overlap a kept one, preferring the longer span.

    The NER model and the rule recognizers can propose overlapping spans for the
    same characters. Masking both would make ``mask`` index the same text twice
    and corrupt the output, so one wins: the longer span, since it hides the most
    complete identifier. Ties go to the higher-confidence span.
    """
    kept: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if span.end <= span.start:
            continue
        if kept and span.start < kept[-1].end:
            previous = kept[-1]
            if (span.end - span.start) > (previous.end - previous.start):
                kept[-1] = span
            continue
        kept.append(span)
    return kept


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
            # Names are never joined across a comma: "Иван Петров, Пётр Петров" is two
            # people, and one token for both would restore the wrong name.
            name_gap = prev.display_type != "PERSON" or gap.strip() == ""
            touching = span.start <= prev.end or (_JOIN_GAP.match(gap) is not None and name_gap)
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


def hidden_spans(text: str, spans: list[Span]) -> list[Span]:
    """The spans that mask() actually hides: a name takes its case ending, then overlaps and
    neighbours of one type merge.

    Audits score this rather than the raw spans. A name hidden to its stem, with the ending
    outside the span, is not hidden in the text the model sees.
    """
    prepared = [_extend_over_ending(text, span) if span.display_type == "PERSON" else span for span in spans]
    return merge_spans(text, resolve_overlaps(prepared))


_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_NAME_WORD = re.compile(r"[А-Яа-яЁёA-Za-z]+(?:-[А-Яа-яЁёA-Za-z]+)*")


def _extend_over_ending(text: str, span: Span) -> Span:
    """Take a name's Russian case ending into the span: "Петрову" masks whole.

    Left alone, the ending would sit glued to the placeholder ("[PERSON_6]у"), and
    the model would copy that broken shape into the reply.
    """
    end = span.end
    while end < len(text) and _CYRILLIC.match(text[end]):
        end += 1
    if end == span.end:
        return span
    return Span(start=span.start, end=end, label=span.label, score=span.score)


def _link_persons(text: str, merged: list[Span]) -> tuple[dict[int, int], list[tuple[list[str], str]]]:
    """Group person mentions by who they name. Returns span index -> person index,
    and for each person the words and surface of its fullest mention.

    Longest mentions go first, so a bare surname finds the full name it belongs to.
    A mention with several candidate people gets a fresh placeholder rather than a
    guess: a wrong link would restore the wrong name.
    """
    mentions = []
    for index, span in enumerate(merged):
        if span.display_type != "PERSON":
            continue
        words = _NAME_WORD.findall(text[span.start : span.end])
        if words:
            mentions.append((index, words))

    persons: list[tuple[list[str], str]] = []
    owner: dict[int, int] = {}
    for index, words in sorted(mentions, key=lambda item: (-len(item[1]), item[0])):
        known_words = [known for known, _ in persons]
        candidates = [number for number, known in enumerate(known_words) if names.mention_matches(words, known)]
        if len(candidates) == 1:
            owner[index] = candidates[0]
        else:
            owner[index] = len(persons)
            span = merged[index]
            persons.append((words, text[span.start : span.end]))
    return owner, persons


def _person_value(surface: str, words: list[str]) -> str:
    """The map value for a person: the surface as written when it is already in
    the nominative, otherwise the nominative form. Keeps the exact spacing of a
    name that needs no change."""
    canonical = names.nominative(words)
    if canonical == " ".join(words):
        return surface
    return canonical


def mask(text: str, spans: list[Span]) -> MaskResult:
    """Replace every span with a ``[TYPE_n]`` token and return the reverse map.

    Counters run per display type and are assigned in order of first appearance.
    Non-name entities: the same surface string always maps to the same token.
    Names: the same person always maps to the same token, whatever the case.
    """
    merged = hidden_spans(text, spans)
    owner, persons = _link_persons(text, merged)

    counters: dict[str, int] = {}
    known: dict[str, str] = {}
    token_of_person: dict[int, str] = {}
    person_value: dict[int, str] = {}
    pieces: list[str] = []
    entities: list[MaskedEntity] = []
    cursor = 0

    for index, span in enumerate(merged):
        surface = text[span.start : span.end]
        entity_type = span.display_type
        if index in owner:
            person = owner[index]
            token = token_of_person.get(person)
            if token is None:
                counters[entity_type] = counters.get(entity_type, 0) + 1
                token = f"{entity_type}_{counters[entity_type]}"
                token_of_person[person] = token
                words, fullest = persons[person]
                person_value[person] = _person_value(fullest, words)
        else:
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

    entity_map = {entity.token: entity.text for entity in entities if not entity.token.startswith("PERSON_")}
    for person, token in token_of_person.items():
        entity_map[token] = person_value[person]
    return MaskResult("".join(pieces), entity_map, entities)


# Prepositions that fix the case of the noun after them without ambiguity. "на",
# "в", "за", "под" are left out: they take two cases, and a guess would be wrong
# as often as right. Those tokens fall back to the nominative unless tagged.
_CASE_BY_PREPOSITION: dict[str, str] = {
    "без": "gen", "для": "gen", "до": "gen", "из": "gen", "от": "gen", "после": "gen",
    "у": "gen", "около": "gen", "кроме": "gen", "вместо": "gen", "среди": "gen",
    "к": "dat", "ко": "dat", "по": "dat",
    "о": "loc", "об": "loc", "обо": "loc", "при": "loc",
    "с": "ins", "со": "ins", "над": "ins", "перед": "ins", "между": "ins",
    "про": "acc", "через": "acc", "сквозь": "acc",
}

_LAST_WORD = re.compile(r"([А-Яа-яЁё]+)\W*\Z")


def _case_from_preposition(text: str, start: int) -> str | None:
    """The case a preposition right before ``start`` puts the next noun in."""
    before = text[:start]
    match = _LAST_WORD.search(before)
    if match is None:
        return None
    return _CASE_BY_PREPOSITION.get(match.group(1).lower().replace("ё", "е"))


# A token, optionally followed by a case tag: [PERSON_1], PERSON_1|gen, [PERSON_1|dat].
_TOKEN_WITH_CASE = r"\[?({tokens})(?:\|([a-z]+))?(?![A-Za-z0-9_])\]?"


def unmask(text: str, entity_map: dict[str, str]) -> str:
    """Substitute every placeholder back to its original value.

    A person's token comes back in the case its tag names: ``[PERSON_1|gen]``
    gives the genitive. Without a tag the nominative is used. Brackets are
    optional, and a token glued to a Latin letter or digit is not a placeholder
    (``XPERSON_1X`` stays as it is). A Cyrillic letter next to a token is fine:
    that is an ending the model wrote, and it is handled by the case tag instead.
    """
    if not entity_map:
        return text
    alternatives = "|".join(re.escape(token) for token in sorted(entity_map, key=len, reverse=True))
    # Case-insensitive: a model that lowercases "[PERSON_1]" still gets its value back.
    pattern = re.compile(_TOKEN_WITH_CASE.format(tokens=alternatives), re.IGNORECASE)

    def restore(match: re.Match[str]) -> str:
        token = match.group(1).upper()
        value = entity_map[token]
        if not token.startswith("PERSON_"):
            return value
        # The model's tag is the best evidence; a preposition is the fallback.
        case = match.group(2).lower() if match.group(2) else _case_from_preposition(match.string, match.start())
        return names.inflect(value, case) if case else value

    return pattern.sub(restore, text)


# --- requirements -------------------------------------------------------------
#
# The user's own requirements ("выдели решения, которые озвучил Петров") are text
# the model reads, so they go through the same rule as the transcript: a name is
# sent as the token this recording already has for that person, or not at all.

_STRAY_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]+_\d+)(?![A-Za-z0-9_])")


class UnboundRequirement(ValueError):
    """The requirement names something personal that this recording does not hold."""

    def __init__(self, surfaces: list[str]):
        self.surfaces = surfaces
        super().__init__("personal data in requirement: " + ", ".join(surfaces))


def unknown_tokens(text: str, entity_map: dict[str, str]) -> list[str]:
    """Placeholders in ``text`` that the map cannot restore, in order of appearance.

    A model that invents a token, or writes one that was never in the recording,
    leaves it in the reply. Shown to the user, not silently kept.
    """
    seen: list[str] = []
    for match in _STRAY_TOKEN.finditer(text):
        token = match.group(1).upper()
        # A Latin word with a number ("test_1") is not a placeholder: only a prefix
        # that is a placeholder type counts.
        if token.rsplit("_", 1)[0] not in _PLACEHOLDER_TYPES:
            continue
        if token not in entity_map and token not in seen:
            seen.append(token)
    return seen


def _token_for(span: Span, surface: str, entity_map: dict[str, str]) -> str | None:
    """The token of this recording that the surface refers to, or None if there is none.

    A name is matched by identity (any case, a bare surname), so "Петрову" finds
    "Иван Сергеевич Петров". Anything else needs the same string. Two candidates
    is a refusal, not a guess: a wrong token would restore the wrong person.
    """
    if span.display_type == "PERSON":
        words = _NAME_WORD.findall(surface)
        candidates = [
            token
            for token, value in entity_map.items()
            if token.startswith("PERSON_") and names.mention_matches(words, value.split())
        ]
    else:
        wanted = " ".join(surface.split())
        candidates = [
            token
            for token, value in entity_map.items()
            if token.rsplit("_", 1)[0] == span.display_type and " ".join(value.split()) == wanted
        ]
    return candidates[0] if len(candidates) == 1 else None


def bind_requirements(text: str, spans: list[Span], entity_map: dict[str, str]) -> str:
    """Replace personal data in a requirement with this recording's tokens.

    Raises ``UnboundRequirement`` listing whatever has no token here, so the caller
    can refuse to send the requirement and say why.
    """
    if not text.strip():
        return text
    prepared = [_extend_over_ending(text, span) if span.display_type == "PERSON" else span for span in spans]
    merged = merge_spans(text, resolve_overlaps(prepared))
    pieces: list[str] = []
    cursor = 0
    unbound: list[str] = []
    for span in merged:
        surface = text[span.start : span.end]
        token = _token_for(span, surface, entity_map)
        if token is None:
            unbound.append(surface)
            continue
        pieces.append(text[cursor : span.start])
        pieces.append(f"[{token}]")
        cursor = span.end
    if unbound:
        raise UnboundRequirement(unbound)
    pieces.append(text[cursor:])
    return "".join(pieces)
