"""Tests for the rule layer and the gap-filling that applies it.

The rules used to be merged into the NER output unconditionally, which cost
6.2 F1 on cards because two spans could claim the same digits under different
labels. `fill_gaps` is what stopped that, and the leak cases are what it is
there for, so both are pinned here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import Span  # noqa: E402
from rules import fill_gaps, find_candidates  # noqa: E402


def model(start: int, end: int, label: str) -> Span:
    return Span(start=start, end=end, label=label, score=0.99)


def covered(text: str) -> list[str]:
    return [text[s.start : s.end] for s in find_candidates(text)]


class TestChecksums:
    def test_inn_12_valid(self):
        assert find_candidates("ИНН 100000000074")

    def test_inn_with_broken_checksum_is_ignored(self):
        assert covered("номер 100000000075") == []

    def test_card_passes_luhn(self):
        assert covered("карта 4276380012345679") == ["4276380012345679"]

    def test_card_with_broken_luhn_is_ignored(self):
        assert covered("карта 4276380012345678") == []

    def test_ipv4_out_of_range_is_ignored(self):
        assert covered("хост 999.1.1.1") == []


class TestContext:
    def test_order_number_glued_to_a_letter_is_not_an_inn(self):
        assert covered("заказ № AZ9876543210 отправлен") == []

    def test_plain_inn_is_still_found(self):
        assert covered("ИНН 100000000074") == ["100000000074"]


class TestPassportSpoken:
    def test_word_nomer_between_series_and_number(self):
        assert covered("Серия 4508 номер 123456") == ["4508 номер 123456"]

    def test_series_and_number_adjacent(self):
        assert covered("паспорт 4508 123456") == ["4508 123456"]


class TestGapFilling:
    def test_rule_is_dropped_where_the_model_already_covered_it(self):
        text = "ИНН 100000000074"
        spans = fill_gaps(text, [model(4, 16, "INN")], find_candidates(text))
        assert spans == []

    def test_only_the_uncovered_tail_is_kept(self):
        # The model caught ten of the twelve digits; the last two leak without help.
        text = "ИНН 100000000074"
        spans = fill_gaps(text, [model(4, 14, "INN")], find_candidates(text))
        assert [text[s.start : s.end] for s in spans] == ["74"]

    def test_rule_completes_a_number_the_model_missed_entirely(self):
        text = "ИНН 100000000074"
        spans = fill_gaps(text, [], find_candidates(text))
        assert [text[s.start : s.end] for s in spans] == ["100000000074"]

    def test_gap_without_digits_is_dropped(self):
        # "номер" between the series and the digits is ordinary text; masking it
        # would hide a word while protecting nothing.
        text = "Серия 4508 номер 123456"
        spans = fill_gaps(text, [model(6, 10, "PASSPORT"), model(17, 23, "PASSPORT")], find_candidates(text))
        assert spans == []

    def test_rules_never_remove_a_model_span(self):
        text = "карта 4276380012345679 и ИНН 100000000074"
        model_spans = [model(6, 22, "CREDIT_CARD")]
        spans = fill_gaps(text, model_spans, find_candidates(text))
        assert all(s.start >= 22 for s in spans)


class TestDoesNotOverreach:
    def test_order_number_with_spaces(self):
        assert covered("Заказ номер 4471 отправлен") == []

    def test_amount_and_date(self):
        assert covered("Договор от 14 марта 2026 года, переплата 4500 рублей") == []

    def test_plain_year_sequence(self):
        assert covered("в 2025 и 2026 годах") == []

    def test_meeting_time(self):
        assert covered("Встреча в 14 30, зал 5") == []


class TestDictatedGrouping:
    """Speech recognition breaks numbers into uneven groups.

    Measured on dictated audio: a card number came back as "427 63800 1234
    5679" and stayed unmasked, because every other rule wants one contiguous run
    of digits. The checksums are what keep this from swallowing prose -- dates,
    amounts and years never add up to a valid card.
    """

    def test_card_split_into_four_groups(self):
        assert covered("карта 427 63800 1234 5679") == ["427 63800 1234 5679"]

    def test_card_split_into_many_small_groups(self):
        assert covered("карта 4 276 3800 1 23 4 56 7 9") == ["4 276 3800 1 23 4 56 7 9"]

    def test_grouped_card_with_wrong_checksum_is_ignored(self):
        assert covered("карта 427 63800 1234 5678") == []

    def test_grouped_date_is_not_an_identifier(self):
        assert covered("договор 14 марта 2026 года") == []


class TestInnByName:
    """When the speaker names the identifier, mask it even on a bad checksum.

    A checksum that fails here usually means the recogniser miscounted a digit,
    not that the number is harmless, so the word carries the decision.
    """

    def test_mangled_inn_after_the_word(self):
        assert covered("мой ИИН 010000000000074 вот") == ["010000000000074"]

    def test_dotted_spelling(self):
        assert covered("мой И.Н.Н. 100000000074") == ["100000000074"]

    def test_long_number_without_the_word_is_not_masked(self):
        assert covered("переменная 010000000000074") == []