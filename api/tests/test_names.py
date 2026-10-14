"""Russian name identity and inflection. The masking tests use these through mask()."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import names  # noqa: E402


def test_case_forms_of_one_name_match():
    full = "Ольга Николаевна Смирнова".split()
    for form in ["Ольги Николаевны Смирновой", "Ольге Николаевне Смирновой", "Ольгу Николаевну"]:
        assert names.mention_matches(form.split(), full), form


def test_short_mention_links_to_the_full_name():
    assert names.mention_matches(["Петрову"], ["Иван", "Сергеевич", "Петров"])
    assert names.mention_matches(["Иван"], ["Иван", "Сергеевич", "Петров"])


def test_different_people_do_not_match():
    assert not names.mention_matches(["Иван"], ["Ольга", "Николаевна", "Смирнова"])
    assert not names.mention_matches(["Петров"], ["Ольга", "Николаевна", "Смирнова"])


def test_nominative_is_restored_from_any_case():
    assert names.nominative(["Ольги", "Николаевны", "Смирновой"]) == "Ольга Николаевна Смирнова"
    assert names.nominative(["Петрову"]) == "Петров"


def test_gender_comes_from_the_name_itself():
    assert names.gender_of(["Ольга", "Николаевна", "Смирнова"]) == "femn"
    assert names.gender_of(["Иван", "Сергеевич", "Петров"]) == "masc"


def test_inflect_all_cases():
    display = "Ольга Николаевна Смирнова"
    assert names.inflect(display, "nom") == display
    assert names.inflect(display, "gen") == "Ольги Николаевны Смирновой"
    assert names.inflect(display, "dat") == "Ольге Николаевне Смирновой"
    assert names.inflect(display, "acc") == "Ольгу Николаевну Смирнову"
    assert names.inflect(display, "ins") == "Ольгой Николаевной Смирновой"


def test_unknown_case_leaves_the_name_alone():
    assert names.inflect("Иван Петров", "xyz") == "Иван Петров"


def test_latin_names_are_not_inflected():
    assert names.inflect("John Smith", "gen") == "John Smith"
