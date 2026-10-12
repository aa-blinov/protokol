"""Checks for the masking core: the only part of the pipeline that can silently
leak PII if it is wrong."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import Span, mask, merge_spans, unmask  # noqa: E402


def find(text, needle, label, occurrence=0):
    """Span with offsets computed from the text, so fixtures cannot drift."""
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(needle, start + 1)
    return Span(start=start, end=start + len(needle), label=label, score=1.0)


def find_all(text, needle, label):
    out, start = [], -1
    while True:
        try:
            start = text.index(needle, start + 1)
        except ValueError:
            return out
        out.append(Span(start=start, end=start + len(needle), label=label, score=1.0))


def test_person_name_merges_into_one_token():
    text = "Иван Петров"
    # NER returns first and last name as separate spans.
    result = mask(text, [find(text, "Иван", "FIRST_NAME"), find(text, "Петров", "LAST_NAME")])
    assert result.masked_text == "[PERSON_1]", result.masked_text
    assert result.entity_map == {"PERSON_1": "Иван Петров"}
    assert (result.entities[0].start, result.entities[0].end) == (0, len(text))


def test_repeated_value_gets_the_same_token():
    text = "Иван Петров звонил, потом Иван Петров написал"
    result = mask(text, find_all(text, "Иван Петров", "LAST_NAME"))
    assert result.masked_text == "[PERSON_1] звонил, потом [PERSON_1] написал"
    assert result.entity_map == {"PERSON_1": "Иван Петров"}


def test_distinct_values_get_distinct_tokens():
    text = "Иван Петров и Пётр Иванов"
    result = mask(text, [find(text, "Иван Петров", "LAST_NAME"), find(text, "Пётр Иванов", "LAST_NAME")])
    assert result.masked_text == "[PERSON_1] и [PERSON_2]"
    assert result.entity_map == {"PERSON_1": "Иван Петров", "PERSON_2": "Пётр Иванов"}


def test_numbering_is_per_type():
    text = "Иван и +7 900 123-45-67, почта a@b.ru"
    result = mask(
        text,
        [
            find(text, "Иван", "FIRST_NAME"),
            find(text, "+7 900 123-45-67", "PHONE"),
            find(text, "a@b.ru", "EMAIL"),
        ],
    )
    assert result.masked_text == "[PERSON_1] и [PHONE_1], почта [EMAIL_1]"
    assert set(result.entity_map) == {"PERSON_1", "PHONE_1", "EMAIL_1"}


def test_credit_card_maps_to_card():
    text = "карта 4111 1111 1111 1111"
    result = mask(text, [find(text, "4111 1111 1111 1111", "CREDIT_CARD")])
    assert result.masked_text == "карта [CARD_1]"


def test_address_parts_merge_across_comma():
    text = "Адрес: Москва, улица Тверская, дом 12"
    result = mask(
        text,
        [
            find(text, "Москва", "CITY"),
            find(text, "улица Тверская", "STREET"),
            find(text, "дом 12", "HOUSE"),
        ],
    )
    assert result.masked_text == "Адрес: [ADDRESS_1]", result.masked_text
    assert result.entity_map == {"ADDRESS_1": "Москва, улица Тверская, дом 12"}


def test_spans_separated_by_a_word_do_not_merge():
    text = "Москва и Санкт-Петербург"
    result = mask(text, [find(text, "Москва", "CITY"), find(text, "Санкт-Петербург", "CITY")])
    assert result.masked_text == "[ADDRESS_1] и [ADDRESS_2]"


def test_different_types_never_merge():
    text = "Иван Петров, Москва"
    result = mask(text, [find(text, "Иван Петров", "LAST_NAME"), find(text, "Москва", "CITY")])
    assert result.masked_text == "[PERSON_1], [ADDRESS_1]"


def test_round_trip_restores_exact_text():
    text = "Иван Петров, тел. +7 900 123-45-67, паспорт 45 11 123456."
    result = mask(
        text,
        [
            find(text, "Иван Петров", "LAST_NAME"),
            find(text, "+7 900 123-45-67", "PHONE"),
            find(text, "45 11 123456", "PASSPORT"),
        ],
    )
    assert unmask(result.masked_text, result.entity_map) == text


def test_round_trip_is_lossless_with_original_spacing():
    text = "Иван  Петров"  # double space must survive
    result = mask(text, [find(text, "Иван", "FIRST_NAME"), find(text, "Петров", "LAST_NAME")])
    assert result.entity_map == {"PERSON_1": "Иван  Петров"}
    assert unmask(result.masked_text, result.entity_map) == text


def test_unmask_survives_dropped_brackets():
    result = mask("Иван", [find("Иван", "Иван", "FIRST_NAME")])
    assert unmask("PERSON_1", result.entity_map) == "Иван"
    assert unmask("PERSON_1.", result.entity_map) == "Иван."


def test_unmask_does_not_corrupt_longer_tokens():
    entity_map = {"PERSON_1": "Иван", "PERSON_12": "Пётр"}
    assert unmask("[PERSON_12]", entity_map) == "Пётр"
    assert unmask("[PERSON_1]", entity_map) == "Иван"
    # Both in one string, in both orders: the shorter token must not win first.
    assert unmask("[PERSON_1] и [PERSON_12]", entity_map) == "Иван и Пётр"
    assert unmask("[PERSON_12] потом [PERSON_1]", entity_map) == "Пётр потом Иван"


def test_unmask_needs_a_word_boundary():
    """A token glued to letters is part of some other word, not a placeholder."""
    entity_map = {"PERSON_1": "Иван"}
    assert unmask("XPERSON_1X", entity_map) == "XPERSON_1X"


def test_unknown_token_is_left_alone():
    """A token with no entry cannot be substituted and must stay visible.

    Silently dropping it would hide the fact that the model mentioned a value
    the mask never saw.
    """
    entity_map = {"PERSON_1": "Иван"}
    assert unmask("[PERSON_9] и [PERSON_1]", entity_map) == "[PERSON_9] и Иван"


def test_empty_input_is_unchanged():
    assert mask("", []).masked_text == ""
    assert unmask("нет данных", {}) == "нет данных"


def test_no_entities_keeps_text():
    text = "встреча в среду"
    result = mask(text, [])
    assert result.masked_text == text
    assert result.entity_map == {}


def test_overlapping_spans_collapse():
    text = "Иван Петров"
    merged = merge_spans(
        text,
        [
            Span(0, 11, "LAST_NAME", 1.0),
            Span(0, 4, "FIRST_NAME", 0.5),
        ],
    )
    assert len(merged) == 1
    assert (merged[0].start, merged[0].end) == (0, 11)
    assert merged[0].score == 1.0


def test_offset_invariant_holds():
    text = "Иван Петров, +7 900 123-45-67"
    result = mask(
        text,
        [find(text, "Иван Петров", "LAST_NAME"), find(text, "+7 900 123-45-67", "PHONE")],
    )
    for entity in result.entities:
        assert text[entity.start : entity.end] == entity.text
