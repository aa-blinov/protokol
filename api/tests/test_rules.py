"""Checks for the deterministic PII rules.

The model's weak spots are exactly the structured identifiers a rule layer can
catch for certain (IP, INN, SNILS, card, passport). These tests pin both sides:
a real identifier is found, and a checksum-invalid look-alike is not turned into
noise. The privacy rule of the house applies — a false negative is a leak, a
false positive is only an annoyance — so where the rules are unsure they mask.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import Span, resolve_overlaps  # noqa: E402
from rules import find_structured  # noqa: E402


def labels(text: str) -> list[str]:
    return [span.label for span in find_structured(text)]


def matched(text: str) -> list[str]:
    return [text[span.start : span.end] for span in find_structured(text)]


def test_ipv4_is_masked():
    text = "Сервер отвечает на 192.168.0.1, резервный 10.0.0.254."
    assert labels(text) == ["IP_ADDRESS", "IP_ADDRESS"]
    assert matched(text) == ["192.168.0.1", "10.0.0.254"]


def test_an_out_of_range_octet_is_not_an_ip():
    assert labels("Версия 999.1.1.1 не адрес.") == []


def test_valid_inn_ten_and_twelve_digits():
    assert labels("ИНН 7707083893.") == ["INN"]
    assert labels("ИНН 500100732259.") == ["INN"]


def test_an_inn_that_fails_its_checksum_is_left_alone():
    # 1234567890 fails the ten-digit INN checksum and is not a phone.
    assert labels("Код 1234567890.") == []


def test_valid_snils():
    assert labels("СНИЛС 123-456-789 64.") == ["SNILS"]


def test_a_snils_lookalike_with_a_bad_check_is_not_masked():
    assert labels("Число 123-456-789 00.") == []


def test_a_luhn_valid_card_is_masked():
    assert labels("Карта 4111 1111 1111 1111 принята.") == ["CREDIT_CARD"]


def test_passport_series_and_number():
    assert labels("Паспорт 45 06 123456 выдан.") == ["PASSPORT"]


def test_phone_formats():
    assert labels("Звоните 8 (912) 345-67-89.") == ["PHONE"]
    assert labels("Звоните +7 912 345-67-89.") == ["PHONE"]
    assert labels("Звоните 89123456789.") == ["PHONE"]


def test_several_types_in_one_line():
    text = "ИНН 7707083893, СНИЛС 123-456-789 64, карта 4111 1111 1111 1111, IP 10.0.0.1."
    assert labels(text) == ["IP_ADDRESS", "INN", "SNILS", "CREDIT_CARD"]


def test_resolve_overlaps_keeps_the_longer_span():
    spans = [Span(0, 5, "PERSON", 0.9), Span(3, 12, "PHONE", 1.0)]
    kept = resolve_overlaps(spans)
    assert len(kept) == 1
    assert (kept[0].start, kept[0].end) == (3, 12)
