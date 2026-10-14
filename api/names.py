"""Russian personal names: one identity per person, and the right case on the way back.

A name appears in a recording in whatever case the sentence needs: "Ольга
Николаевна", "Ольги Николаевны Смирновой", "Ольге Николаевне". Masking by exact
string gave each form its own placeholder, so one person read as three people
to the model. Here a mention is matched to a person by the set of dictionary
lemmas each of its words could be, and the restored name is inflected to the case
the model asks for.

The dictionary is ambiguous on purpose: "Смирновой" is a feminine genitive, but
without context it also parses as a masculine lemma. Candidate sets absorb that.
Where the context does decide (a first name or patronymic in the same mention),
the gender from that context picks the form.
"""

from __future__ import annotations

from functools import lru_cache

import pymorphy3

_morph = pymorphy3.MorphAnalyzer()

# Tokens the model may write as [PERSON_1|gen]. Anything else is ignored.
CASE_TAGS: dict[str, str] = {
    "nom": "nomn",
    "gen": "gent",
    "dat": "datv",
    "acc": "accs",
    "ins": "ablt",
    "loc": "loct",
}

_NAME_TAGS = {"Name", "Surn", "Patr", "Geox"}


def _fold(word: str) -> str:
    return word.lower().replace("ё", "е")


def oblique_surname(word: str) -> bool:
    """True when a capitalised word can be a surname in a case other than the nominative.

    "Ковалёвой" and "Петровым" look the same in several cases, so their parse weight is low;
    0.3 keeps the clear surnames and drops rare readings. The caller checks the capital letter.
    """
    return any(
        parse.score >= 0.3
        and "Surn" in parse.tag.grammemes
        and set(parse.tag.grammemes) & {"gent", "datv", "ablt", "loct"}
        for parse in _parses(word)
    )


def surname_like(word: str) -> bool:
    """True when a word can be a surname at a usable weight, in whatever case it is written.

    For text where the capital letter is missing: the grammar of the word has to carry the evidence.
    """
    return any(parse.score >= 0.3 and "Surn" in parse.tag.grammemes for parse in _parses(word))


def geo_word(word: str) -> bool:
    """True when a capitalised word can be a geographic name at a usable weight ("Москве", "Урале").

    The caller checks the preposition before the word, which is what keeps common nouns out.
    """
    return any(parse.score >= 0.5 and "Geox" in parse.tag.grammemes for parse in _parses(word))


_COMMON_PARTS_OF_SPEECH = {
    "NOUN", "ADJF", "ADJS", "VERB", "INFN", "ADVB", "PRCL", "CONJ", "PREP", "NPRO",
    "NUMR", "INTJ", "PRED", "COMP", "GRND", "PRTF", "PRTS",
}


def name_like(word: str) -> bool:
    """True when a capitalised word can be a name, a patronymic or a surname.

    A word the dictionary reads as a name, patronymic or surname counts. So does a word the
    dictionary does not know as an ordinary part of speech: an unfamiliar surname is more
    likely a name than a verb or a noun. "Решили" and "Данные" are ordinary words, so no.
    """
    parses = _parses(word)
    if any(parse.score >= 0.1 and set(parse.tag.grammemes) & {"Name", "Surn", "Patr"} for parse in parses):
        return True
    return not any(parse.score >= 0.5 and parse.tag.POS in _COMMON_PARTS_OF_SPEECH for parse in parses)


@lru_cache(maxsize=8192)
def _parses(word: str):
    parses = [p for p in _morph.parse(word) if p.score >= 0.05]
    return tuple(parses) or tuple(_morph.parse(word)[:1])


@lru_cache(maxsize=8192)
def lemmas(word: str) -> frozenset[str]:
    """Every dictionary lemma the word could be. Two mentions can be the same name
    if their words share one."""
    return frozenset(_fold(p.normal_form) for p in _parses(word)) | {_fold(word)}


def gender_of(words: list[str]) -> str | None:
    """The gender the name itself declares, if any: first name or patronymic."""
    votes: dict[str, float] = {}
    for word in words:
        for p in _parses(word):
            if p.tag.gender in ("masc", "femn") and _NAME_TAGS & set(p.tag.grammemes):
                votes[p.tag.gender] = votes.get(p.tag.gender, 0.0) + p.score
    if not votes:
        return None
    return max(votes, key=votes.get)


def _pick(word: str, gender: str | None):
    parses = _parses(word)
    if gender is not None:
        matching = [p for p in parses if p.tag.gender in (gender, None)]
        if matching:
            return max(matching, key=lambda p: p.score)
    return max(parses, key=lambda p: p.score)


def nominative(words: list[str]) -> str:
    """The name in the nominative: how it is shown in the map and in the UI."""
    gender = gender_of(words)
    out = []
    for word in words:
        parsed = _pick(word, gender)
        form = parsed.inflect({"nomn"})
        base = form.word if form else word
        out.append(base[:1].upper() + base[1:] if word[:1].isupper() else base)
    return " ".join(out)


def inflect(display: str, case: str) -> str:
    """Put a nominative display name into ``case`` ("nom", "gen", ...).

    Unknown cases return the name unchanged, so a bad tag never breaks the reply.
    """
    grammeme = CASE_TAGS.get(case)
    words = display.split()
    if grammeme is None or not words:
        return display
    gender = gender_of(words)
    out = []
    for word in words:
        parsed = _pick(word, gender)
        form = parsed.inflect({grammeme})
        base = form.word if form else word
        out.append(base[:1].upper() + base[1:] if word[:1].isupper() else base)
    return " ".join(out)


def same_person_word(a: str, b: str) -> bool:
    return bool(lemmas(a) & lemmas(b))


def mention_matches(mention: list[str], person_words: list[str]) -> bool:
    """A mention is the person when it names the same words in some order.

    Equal length: each word lines up with its counterpart. Shorter mention: each of
    its words appears somewhere in the full name ("Петров" in "Иван Сергеевич Петров").
    """
    if len(mention) == len(person_words):
        return all(same_person_word(m, p) for m, p in zip(mention, person_words))
    if len(mention) < len(person_words):
        return all(any(same_person_word(m, p) for p in person_words) for m in mention)
    return False
