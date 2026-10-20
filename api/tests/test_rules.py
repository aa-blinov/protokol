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
from rules import fill_gaps, fill_word_gaps, find_candidates, find_word_candidates, relabel_by_name  # noqa: E402


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


class TestInnRegressions:
    """Found on the PII benchmark, where INN tokens the model had found were lost.

    The passport pattern took every ten-digit run before the INN rule saw it, a KPP
    after an "ИНН" was read as a tax id, and a dictated INN spelled in digit words
    was not masked at all.
    """

    def test_valid_inn_without_keyword_is_an_inn_not_a_passport(self):
        assert [s.label for s in find_candidates("ИНН 7707083893")] == ["INN"]

    def test_passport_keyword_keeps_a_ten_digit_passport(self):
        assert [s.label for s in find_candidates("паспорт 7707083893")] == ["PASSPORT"]

    def test_kpp_after_the_inn_is_an_org_id_not_an_inn(self):
        text = "ИНН 7707083893, КПП 770101001"
        assert {text[s.start : s.end]: s.label for s in find_candidates(text)} == {
            "7707083893": "INN",
            "770101001": "ORG_ID",
        }

    def test_inn_inside_innovation_is_not_a_keyword(self):
        assert covered("инновационный проект 770101001") == []

    def test_dictated_inn_in_digit_words_after_the_keyword(self):
        words = "девять семь три шесть девять один восемь три один два один четыре"
        assert covered(f"мой ИНН {words}") == [words]

    def test_dictated_valid_inn_without_keyword(self):
        words = "семь семь ноль семь ноль восемь три восемь девять три"
        assert covered(f"номер {words}") == [words]

    def test_counting_in_words_is_not_an_identifier(self):
        assert covered("один два три четыре пять шесть семь восемь девять") == []

    def test_dictated_passport_is_not_an_inn_even_with_a_valid_sum(self):
        words = "шесть ноль четыре шесть один восемь три девять восемь два"
        assert [s.label for s in find_candidates(f"паспорт номер {words}")] == ["PASSPORT"]

    def test_dictated_driver_licence_is_not_an_inn_even_with_a_valid_sum(self):
        words = "шесть ноль четыре шесть один восемь три девять восемь два"
        assert [s.label for s in find_candidates(f"водительское удостоверение, номер {words}")] == ["DRIVER_LICENSE"]

    def test_dictated_inn_survives_gap_filling(self):
        # Without a digit character in the gap, the words were dropped as a connector.
        words = "девять семь три шесть девять один восемь три один два один четыре"
        text = f"мой ИНН {words}"
        spans = fill_gaps(text, [], find_candidates(text))
        assert [text[s.start : s.end] for s in spans] == [words]

    def test_named_inn_with_a_failing_sum_is_an_inn_not_a_passport(self):
        # 7712345678 fails the tax-id sum; the word "ИНН" still says what it is.
        assert [s.label for s in find_candidates("ИНН организации 7712345678")] == ["INN"]


class TestNamedDocuments:
    """Found on the PII benchmark: SNILS, OMS and driver's licence numbers dictated in
    words after their name were never masked, and a misspelled name ("снисл",
    "полес омс") was no name at all.

    These numbers have no checksum to decide the label, so the name does. Of several
    names before a number, the nearest one decides: an INN named before a passport
    does not make the passport an INN.
    """

    def test_dictated_snils_after_its_name(self):
        words = "семь восемь девять - два три семь - три три два шесть ноль"
        text = f"СНИЛС, значение: {words}"
        assert covered(text) == [words]
        assert [s.label for s in find_candidates(text)] == ["SNILS"]

    def test_dictated_oms_after_its_name(self):
        words = "пять шесть два девять три восемь семь ноль ноль пять один шесть два семь один пять"
        text = f"полис ОМС. Номер: {words}"
        assert covered(text) == [words]
        assert [s.label for s in find_candidates(text)] == ["OMS"]

    def test_dictated_driver_licence_after_its_name(self):
        words = "пять два четыре три ноль шесть девять ноль три три"
        text = f"удостоверение, номер которого {words}"
        assert covered(text) == [words]
        assert [s.label for s in find_candidates(text)] == ["DRIVER_LICENSE"]

    def test_misspelled_snils_name_with_a_number_that_fails_its_checksum(self):
        assert [s.label for s in find_candidates("Подскажите, а снисл 12345678901")] == ["SNILS"]

    def test_misspelled_oms_name_with_sixteen_digits(self):
        assert [s.label for s in find_candidates("полес омс 5555666677778888")] == ["OMS"]

    def test_nearest_name_decides_the_label(self):
        text = "ИНН 7707083893, паспорт 4508123456"
        labels = {text[s.start : s.end]: s.label for s in find_candidates(text)}
        assert labels == {"7707083893": "INN", "4508123456": "PASSPORT"}

    def test_dictated_snils_with_non_breaking_hyphens(self):
        # Transcripts write "восемь‑пять" with U+2011, which is not an ASCII hyphen.
        words = "ноль пять восемь‑пять девять два‑три девять три ноль семь"
        text = f"мой СНИЛС: {words}"
        assert covered(text) == [words]
        assert [s.label for s in find_candidates(text)] == ["SNILS"]

    def test_oms_name_with_spaced_letters(self):
        assert [s.label for s in find_candidates("Мне номер о м с 1234567890123456")] == ["OMS"]

    def test_card_after_a_name_keeps_its_label(self):
        # A card passes its own checksum, which is checked before the name is read.
        assert [s.label for s in find_candidates("СНИЛС карта 4276380012345679")] == ["CREDIT_CARD"]

    def test_ten_digit_driver_licence_with_a_failing_sum_is_a_driver_licence(self):
        assert [s.label for s in find_candidates("водительское удостоверение 1234567890")] == ["DRIVER_LICENSE"]

    def test_ten_digit_driver_licence_whose_sum_holds_keeps_its_label(self):
        # 7707083893 passes the tax-id sum, but the name is what says what the number is.
        assert [s.label for s in find_candidates("водительское удостоверение 7707083893")] == ["DRIVER_LICENSE"]

    def test_unnamed_ten_digit_run_is_a_passport(self):
        assert [s.label for s in find_candidates("регистрация ИП № 1000567890")] == ["PASSPORT"]


class TestSpokenNumbers:
    """Cardinal words are read as digits, a spoken number with no name is masked as NUMBER,
    and an amount ("тысяч", "миллион") or a short phrase is left as ordinary text."""

    def test_cardinal_words_read_as_digits(self):
        # 636 756 384 38, eleven digits, read in the groups a person says them in.
        words = "шестьсот тридцать шесть - семьсот пятьдесят шесть - триста восемьдесят четыре тридцать восемь"
        text = f"СНИЛС, значение: {words}"
        assert covered(text) == [words]
        assert [s.label for s in find_candidates(text)] == ["SNILS"]

    def test_unnamed_spoken_number_is_masked_as_a_number(self):
        # Ten digits that are no tax id: masked generically, because it was spoken aloud.
        words = "один один один один один один один один один один"
        assert [s.label for s in find_candidates(f"код {words}")] == ["NUMBER"]

    def test_amount_with_a_scale_word_is_not_masked(self):
        assert covered("один два три четыре пять шесть семь восемь девять десять тысяч рублей") == []

    def test_short_cardinal_phrase_is_not_masked(self):
        assert covered("двадцать пять человек пришли") == []


class TestIpv6:
    def test_full_ipv6_address_is_an_ip(self):
        text = "адрес 2001:db8:0:0:0:0:0:1 в сети"
        assert covered(text) == ["2001:db8:0:0:0:0:0:1"]
        assert [s.label for s in find_candidates(text)] == ["IP_ADDRESS"]

    def test_seven_group_address_is_an_ip(self):
        text = "сеть с адресом 2001:0db8:85a3:0000:8a2e:0370:7334 внешним"
        assert covered(text) == ["2001:0db8:85a3:0000:8a2e:0370:7334"]
        assert [s.label for s in find_candidates(text)] == ["IP_ADDRESS"]

    def test_compressed_ipv6_address_is_an_ip(self):
        assert covered("сервер 2001:db8::1") == ["2001:db8::1"]

    def test_time_is_not_an_ip(self):
        assert covered("встреча в 12:30:45") == []


class TestMacAddress:
    """A MAC address names a device, not a place on the network, so it is never an IP."""

    def test_colon_mac_is_a_number(self):
        text = "устройство с MAC AA:BB:CC:11:22:33 в сети"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [
            ("NUMBER", "AA:BB:CC:11:22:33")
        ]

    def test_hyphen_mac_is_a_number(self):
        text = "адрес 00-1A-2B-3C-4D-5E"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [
            ("NUMBER", "00-1A-2B-3C-4D-5E")
        ]

    def test_ipv6_address_is_still_an_ip(self):
        text = "сервер 2001:db8::1"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("IP_ADDRESS", "2001:db8::1")]


class TestAddressNumbers:
    """House, flat, building and entrance numbers are part of an address, so they are masked too."""

    def numbers(self, text):
        spans = sorted(find_word_candidates(text), key=lambda s: s.start)
        return [text[s.start : s.end] for s in spans if text[s.start : s.end][:1].isdigit()]

    def test_number_after_a_street(self):
        assert self.numbers("живу на ул. Тверская 15") == ["15"]

    def test_unit_words_are_followed_by_their_numbers(self):
        assert self.numbers("дом 45, корп. 2, кв. 87") == ["45", "2", "87"]

    def test_entrance_before_and_after_its_word(self):
        assert self.numbers("3 подъезд, подъезд 1") == ["3", "1"]

    def test_full_address_keeps_every_number(self):
        assert self.numbers("Москва, ул. Профсоюзная, д. 45, корп. 2, кв. 87, 3 подъезд") == ["45", "2", "87", "3"]

    def test_street_without_a_number_has_no_number(self):
        assert self.numbers("едем по ул. Тверской") == []

    def test_floor_is_part_of_the_address(self):
        assert self.numbers("Тула, проспект Ленина, 34, 5 этаж") == ["34", "5"]

    def test_count_of_floors_is_not_an_address(self):
        assert self.numbers("на 5 этажей здания") == []

    def test_hyphenated_place_name_is_masked_whole(self):
        text = "офис в Санкт-Петербурге"
        names = [text[s.start : s.end] for s in find_word_candidates(text) if s.label == "LOCATION"]
        assert "Санкт-Петербурге" in names

    def test_hyphenated_company_name_is_not_a_place(self):
        assert [s for s in find_word_candidates("договор с Газпром-Нефть") if s.label == "LOCATION"] == []

    def test_street_name_is_part_of_the_address(self):
        text = "живу на ул. Тверская 15"
        names = [text[s.start : s.end] for s in find_word_candidates(text) if s.label == "LOCATION"]
        assert "Тверская" in names


class TestElevenDigitPhone:
    def test_eleven_digits_from_eight_are_a_phone(self):
        assert [s.label for s in find_candidates("звонил по номеру 84951234567")] == ["PHONE"]

    def test_eleven_digits_from_seven_are_a_phone(self):
        assert [s.label for s in find_candidates("рабочий номер 74951112233")] == ["PHONE"]

    def test_valid_snils_stays_a_snils(self):
        # 11223344595 passes the SNILS checksum, so it is a SNILS and not a phone.
        assert [s.label for s in find_candidates("номер 11223344595")] == ["SNILS"]


class TestKeywordNumbers:
    """A number that only its keyword identifies: the keyword must sit right before it."""

    def test_ogrnip_is_masked_even_when_the_keyword_is_a_sentence_earlier(self):
        text = "Уточните ОГРНИП для сверки. Мой номер 304567890123457"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [
            ("OGRNIP", "304567890123457")
        ]

    def test_cvc_on_the_back_of_the_card(self):
        text = "укажите код на обороте карты 274"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("CREDIT_CARD", "274")]

    def test_cvc_after_its_keyword_is_card_data(self):
        text = "CVC 456"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("CREDIT_CARD", "456")]

    def test_cvc_spelled_in_cyrillic_with_a_word_between(self):
        text = "я же вводил цвс был 408"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("CREDIT_CARD", "408")]

    def test_bare_three_digit_code_is_a_secret(self):
        # Nothing around it says what it is, so it is masked as a one-time or security code.
        text = "код 789 пришёл по смс"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", "789")]

    def test_bare_three_digit_code_in_a_scam_sentence_is_a_secret(self):
        text = "боюсь что обман, но код 901"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", "901")]

    def test_access_token_after_its_word_is_a_secret(self):
        token = "7f8d9a2b4e1c6f3a8b5d2e9c4a7f1b8e3d6c9a2f5b8e1d4a7c"
        text = f"мой API токен {token} спасибо"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", token)]

    def test_long_word_after_token_is_not_a_secret(self):
        assert find_candidates("токен доступа устарел") == []
        assert find_candidates("token authentication flow") == []

    def test_token_after_an_exclamation_mark_is_still_a_secret(self):
        token = "7pR9sT2vW4xY6zA8bC0dE2fG4hJ6kL8mN0pQ3rS5tU"
        text = f"срочно нужен новый токен доступа! старый перестал работать: {token}"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", token)]

    def test_misspelled_token_word_is_still_a_secret(self):
        token = "2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a"
        text = f"вот токн подтверждения действия {token}"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", token)]

    def test_one_time_code_after_its_word_is_a_secret(self):
        text = "пришел код 847593, подтверждаю"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", "847593")]

    def test_sms_code_with_a_word_between_is_a_secret(self):
        text = "получил смс с кодом 392847, все верно"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", "392847")]

    def test_three_digit_city_code_is_not_a_secret(self):
        assert find_candidates("код города 495") == []

    def test_error_code_is_not_a_secret(self):
        assert find_candidates("Код ошибки: 4808, обратитесь в поддержку") == []

    def test_spaced_eleven_digit_phone_is_a_phone(self):
        text = "звоните 8 495 123 45 67 в любое время"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("PHONE", "8 495 123 45 67")]

    def test_three_digit_confirmation_code_is_a_secret(self):
        text = "нужен код подтверждения 382"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", "382")]

    def test_jwt_token_with_dots_is_a_secret(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV"
        text = f"обновите токен {token}"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SECRET", token)]

    def test_sentence_period_after_a_token_is_not_part_of_it(self):
        text = "мой токен abc123def456ghi789jkl."
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [
            ("SECRET", "abc123def456ghi789jkl")
        ]

    def test_six_digit_number_after_a_passport_name(self):
        text = "потерял паспорт, номер 789012"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("PASSPORT", "789012")]

    def test_six_digit_number_without_a_name_is_left_alone(self):
        assert find_candidates("номер 789012 в прайсе") == []

    def test_spelled_snils_with_a_name_and_a_failing_checksum(self):
        text = "снилс 147-852-369 00"
        assert [(s.label, text[s.start : s.end]) for s in find_candidates(text)] == [("SNILS", "147-852-369 00")]


class TestLegalEntityNumbers:
    """KPP and OGRN name a company, not a person. They are masked on request, under their own type."""

    def labelled(self, text):
        return [(s.label, text[s.start : s.end]) for s in find_candidates(text)]

    def test_kpp_after_its_word_is_an_org_id(self):
        assert self.labelled("договор с компанией, КПП 772543001") == [("ORG_ID", "772543001")]

    def test_ogrn_of_a_company_is_an_org_id(self):
        assert self.labelled("ОГРН организации 1057746298103") == [("ORG_ID", "1057746298103")]

    def test_ogrn_with_the_recogniser_spelling_is_an_org_id(self):
        assert self.labelled("у них огргн 1197746789239") == [("ORG_ID", "1197746789239")]

    def test_ogrn_with_a_missing_letter_is_an_org_id(self):
        assert self.labelled("проверил фирму по огрг 1234567890127") == [("ORG_ID", "1234567890127")]

    def test_ogrn_is_not_taken_from_ogrnip(self):
        assert self.labelled("ОГРНИП 304567890123457") == [("OGRNIP", "304567890123457")]

    def test_company_number_without_its_word_is_left_alone(self):
        assert self.labelled("номер 772543001 в прайсе") == []

    def test_registration_number_in_full_wording_is_an_org_id(self):
        assert self.labelled("основной государственный регистрационный номер 5097746123459") == [
            ("ORG_ID", "5097746123459")
        ]

    def test_registration_number_with_a_filler_word_is_an_org_id(self):
        assert self.labelled("продиктовать регистрационный номер, это 5587812345676.") == [
            ("ORG_ID", "5587812345676")
        ]

    def test_registration_number_of_another_length_is_left_alone(self):
        assert self.labelled("регистрационный номер автомобиля 12345") == []


class TestCardCodes:
    """The three-digit code on the back of a card: asked for right before the number, in a sentence
    about a card or a payment. Any one of those alone is too common to mask."""

    def labelled(self, text):
        return [(s.label, text[s.start : s.end]) for s in find_candidates(text)]

    def test_code_asked_for_in_a_payment_sentence_is_card_data(self):
        assert self.labelled("назовите CVC-код для завершения оплаты, это 156") == [("CREDIT_CARD", "156")]

    def test_code_asked_for_in_a_card_sentence_is_card_data(self):
        assert self.labelled("при привязке карты система не принимает код 789") == [("CREDIT_CARD", "789")]

    def test_amount_after_a_card_word_is_not_a_code(self):
        assert self.labelled("оплата это 123 рубля, карта") == []

    def test_city_code_next_to_a_card_word_is_not_a_code(self):
        assert self.labelled("код города 495 у карты") == []


class TestRelabel:
    """The model's span keeps its place, so the masked text does not change; only the label
    moves to the identifier the name asks for. Phones and cards are never renamed."""

    def test_model_label_moves_to_the_named_identifier(self):
        spans = relabel_by_name("мой СНИЛС 12345678901", [model(10, 21, "OMS")])
        assert [(s.start, s.end, s.label) for s in spans] == [(10, 21, "SNILS")]

    def test_phone_is_never_renamed_by_a_name_before_it(self):
        spans = relabel_by_name("ИНН телефон 89161234567", [model(12, 23, "PHONE")])
        assert [s.label for s in spans] == ["PHONE"]


class TestNamesAndPlaces:
    """A surname in an oblique case, and a street adjective after a preposition, are caught
    even when the model missed them. An ordinary capitalised word is not."""

    def test_oblique_surname_without_a_first_name_is_a_person(self):
        text = "Ковалёвой нужно перезвонить"
        spans = find_word_candidates(text)
        assert [(text[s.start : s.end], s.label) for s in spans] == [("Ковалёвой", "PERSON")]

    def test_street_adjective_after_a_preposition_is_a_place(self):
        text = "офис на Тверской, решили"
        spans = find_word_candidates(text)
        assert [(text[s.start : s.end], s.label) for s in spans] == [("Тверской", "LOCATION")]

    def test_ordinary_sentence_has_no_word_candidates(self):
        assert find_word_candidates("Сегодня мы обсуждаем план") == []

    def test_word_gap_keeps_a_name_without_digits(self):
        text = "Ковалёвой нужно"
        spans = fill_word_gaps(text, [], find_word_candidates(text))
        assert [text[s.start : s.end] for s in spans] == ["Ковалёвой"]


class TestInitialsAndPlaces:
    """Initials before a surname name a person, and a place name after a preposition is a
    place, both as they appear in Russian diaries and letters."""

    def test_initials_before_a_surname_are_a_person(self):
        text = "статьи о В . М . Брадисе и П. Петрова"
        spans = find_word_candidates(text)
        assert [(text[s.start : s.end], s.label) for s in spans] == [
            ("В . М . Брадисе", "PERSON"),
            ("П. Петрова", "PERSON"),
        ]

    def test_a_lone_initial_is_not_a_person(self):
        assert find_word_candidates("т. е. это так") == []

    def test_place_name_after_a_preposition_is_a_location(self):
        text = "встреча в Москве"
        spans = find_word_candidates(text)
        assert [(text[s.start : s.end], s.label) for s in spans] == [("Москве", "LOCATION")]

    def test_place_name_without_a_preposition_is_left_alone(self):
        assert find_word_candidates("Москве нужен ремонт") == []
