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

import ipaddress
import re

from masking import Span
import names

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
# A colon-separated run of hex groups, checked by the standard library afterwards:
# "12:30:45" is a time, not an address, and only the full or compressed IPv6 forms validate.
_IPV6_TOKEN_RE = re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f:]{2,39}(?![0-9A-Fa-f:])")
# Six hex pairs, "AA:BB:CC:11:22:33" or "AA-BB-CC-11-22-33". A MAC address names a device, not a
# place on the network, and the five-group IPv6 fallback would otherwise label it as an IP.
_MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])")
# Words that may sit between a keyword and its number: "CVC: это 456", "цвс был 408".
_BETWEEN_WORDS = r"[\s:,.\-–—(]*(?:[а-яёa-z]+[\s:,.\-–—(]+){0,3}"
# An access token is often a few sentences after the word that names it, so it may sit further off.
# Exclamation and question marks end a sentence but not a phrase, so they stay inside the gap.
_TOKEN_GAP = r"[\s:,.\-–—()!?;]*(?:[а-яёa-z]+[\s:,.\-–—()!?;]+){0,8}"
# A one-time code (SMS, confirmation, recovery) is a secret too: a 4 to 8 digit number right after
# its word. A three-digit city code or a year does not match, so a short gap is enough.
# "Код ошибки", "код отслеживания", "код сессии" name no secret: the number after them is a
# reference, so these words end the keyword's reach.
_NOT_A_SECRET_CODE = r"(?![\s:]*(?:ошибк|отслеж|сесси|статус|заказ|товар|промо|купон|скидк|страны|города|региона|октмо|окато|инн|кпп|бик))"
_OTP_RE = re.compile(
    r"(?<![а-яёa-z])(?:код(?:а|у|ом|е|ы)?" + _NOT_A_SECRET_CODE + r"|смс|sms|парол[ьюяе]?)(?![а-яё])"
    + r"[\s:,.\-–—()!?;]*(?:[а-яёa-z]+[\s:,.\-–—()!?;]+){0,4}"
    + r"(?<!\d)(?P<number>\d{4,8})(?!\d)",
    re.IGNORECASE,
)
# A three-digit confirmation code ("код подтверждения 382") is a secret too. Without the
# confirmation word a three-digit number after "код" is a city code, so it stays unmasked.
_OTP_CONFIRM_RE = re.compile(
    r"(?<![а-яёa-z])код(?:а|у|ом|е|ы)?\s+(?:для\s+)?(?:подтвержд|верификац|восстановлен|активац)[а-яё]*"
    r"[\s:,.\-–—()!?;]*(?<!\d)(?P<number>\d{3})(?!\d)",
    re.IGNORECASE,
)
_CVC_RE = re.compile(
    r"(?<![а-яёa-z])(?:cvc2?|cvv2?|цвс|цвв|код\s+безопасности|с\s+обратной\s+стороны"
    r"|на\s+обороте|на\s+обратной\s+стороне)"
    + _BETWEEN_WORDS
    + r"(?<!\d)(?P<number>\d{3})(?!\d)",
    re.IGNORECASE,
)
# An access token or API key: a long run of letters and digits after the word that names it.
_SECRET_RE = re.compile(
    r"(?<![а-яёa-z])(?:токе?н\w*|token|api[\s-]?ключ\w*|api[\s-]?key|ключ\s+api|код(?:а|у|ом|е|ы)?(?![а-яё])"
    + _NOT_A_SECRET_CODE +
    r"|смс|sms|парол[ьюяе]?)"
    + _TOKEN_GAP
    + r"(?P<number>(?<![A-Za-z0-9_])[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*(?![A-Za-z0-9_\-]))",
    re.IGNORECASE,
)
_PASSPORT_NUMBER_RE = re.compile(r"(?<![а-яёa-z])(?:номер|№|no)\.?\s*(?P<number>\d{6})(?!\d)", re.IGNORECASE)
# A company's number named in its own words: "регистрационный номер", as in "основной
# государственный регистрационный номер". Thirteen digits only: fifteen is a sole proprietor's
# ОГРНИП, which the keyword rules mask as its own type.
_REGISTRATION_NUMBER_RE = re.compile(
    r"(?<![а-яёa-z])регистрационн\w*\s+номер\w*" + _BETWEEN_WORDS + r"(?<!\d)(?P<number>\d{13})(?!\d)",
    re.IGNORECASE,
)
# The three-digit code on the back of a card. A bare number names nothing, so the rule needs a word
# that asks for the code right before it ("код", "это", "вот") and a card word in the same sentence:
# either one alone is too common in ordinary speech. "код города" and "код ошибки" are not codes.
_CODE_ASK_RE = re.compile(
    r"(?<![а-яёa-z])(?:код(?!\s+(?:город|стран|ошибк|отслеж|сесси|заказ|регион|статус|промо|купон|скидк))"
    r"|это|вот|ввожу|введите|назовите|сообщите)[\s:,.\-–—()]*(?:[а-яёa-z]+[\s:,.\-–—()]+){0,2}$",
    re.IGNORECASE,
)
# A strong ask names the code outright, so a few more words may sit between it and the number:
# "CVC-код для завершения транзакции, мой 901".
_STRONG_CODE_ASK_RE = re.compile(
    r"(?<![а-яёa-z])(?:cvc|cvv|цвс|с\s+обратной\s+стороны|на\s+обороте)"
    r"[\s:,.\-–—()]*(?:[а-яёa-z]+[\s:,.\-–—()]+){0,5}$",
    re.IGNORECASE,
)
# A bare three-digit code with nothing around it to say what it is: a one-time or security code.
# Masked as a secret, the same as an SMS code. "код города" and "код ошибки" are not codes.
_GENERIC_CODE_RE = re.compile(
    r"(?<![а-яёa-z])код(?!\s+(?:город|стран|ошибк|отслеж|сесси|заказ|регион|статус|промо|купон|скидк))"
    r"[\s:]+(?P<number>\d{3})(?!\d)",
    re.IGNORECASE,
)
_CARD_WORD_RE = re.compile(r"карт|cvc|cvv|оплат|платеж|оборот|сзади|цвс", re.IGNORECASE)
# A three-digit number followed by a unit is an amount, not a code: "это 123 рубля".
_AMOUNT_AFTER_RE = re.compile(r"\s*(?:руб|₽|тыс|млн|процент|%|шт)", re.IGNORECASE)
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

# Spoken numbers: a digit word stands for one digit, and a cardinal word for its value
# ("шестьсот тридцать шесть" is 636). Both kinds are read from the same runs.
_NUMBER_WORDS = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_WORD_RE = re.compile(r"[а-яё]+", re.IGNORECASE)
_NUMBER_WORD_ALTERNATION = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
# A run of number words joined by spaces or punctuation. The dashes include the
# non-breaking hyphen (U+2011) that transcripts write in "восемь‑пять".
_NUMBER_RUN_RE = re.compile(
    rf"(?<![а-яё])(?:{_NUMBER_WORD_ALTERNATION})(?![а-яё])"
    rf"(?:[\s,.\-‐‑–—]+(?:{_NUMBER_WORD_ALTERNATION})(?![а-яё]))*",
    re.IGNORECASE,
)
# A number next to a scale word is an amount ("сто тысяч рублей"), not an identifier.
_SCALE_AFTER_RE = re.compile(r"\s*(?:тысяч|миллион|миллиард)[а-яё]*", re.IGNORECASE)
_SCALE_BEFORE_RE = re.compile(r"(?:тысяч|миллион|миллиард)[а-яё]*\s*$", re.IGNORECASE)


def _spoken_digits(words: list[str]) -> str:
    """Digits of spoken number words, read in the groups a person says them in.

    A word continues the group before it only when it is of a lower order (hundreds,
    then tens, then units): "тридцать восемь" after "четыре" starts a new group, while
    "шестьсот тридцать шесть" is one group of 636. Single digit words give one digit each.
    """
    groups: list[list[int]] = []
    for word in words:
        value = _NUMBER_WORDS[word]
        order = 0 if value >= 100 else 1 if value >= 20 else 2
        if groups and order > groups[-1][1]:
            groups[-1] = [groups[-1][0] + value, order]
        else:
            groups.append([value, order])
    return "".join(str(value) for value, _ in groups)


def _amount_context(text: str, start: int, end: int) -> bool:
    return bool(_SCALE_AFTER_RE.match(text, end)) or bool(_SCALE_BEFORE_RE.search(text, max(0, start - 20), start))


def _valid_ipv4(text: str) -> bool:
    return all(0 <= int(part) <= 255 for part in text.split("."))


def _ipv6(token: str) -> bool:
    if token.count(":") < 2 or not re.search(r"[0-9A-Fa-f]", token):
        return False
    try:
        ipaddress.IPv6Address(token)
        return True
    except ValueError:
        pass
    # Five or more hex groups are an address even when the count is off: a colon run that
    # long is never a time or a ratio in prose, and a written address is often malformed.
    groups = [group for group in token.split(":") if group]
    return len(groups) >= 5 and all(re.fullmatch(r"[0-9A-Fa-f]{1,4}", group) for group in groups)


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


# Keywords as whole words, in the spellings recognition produces: "ИНН", "ИИН",
# "и.н.н", "и н н"; "снилс" and "снисл"; "полис", "полес", "полюс" with "омс" or
# "осм". A substring match would also fire on "инновации" and "Инна".
_INN_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])(?:и\W?н\W?н|и\W?и\W?н)(?![а-яёa-z])", re.IGNORECASE)
# "удостоверение личности" is a passport, so "личности" is a passport keyword: the nearest
# name wins, and that name is the passport one.
_PASSPORT_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])(?:паспорт\w*|серия|пасп\w*|личност\w*)", re.IGNORECASE)
_DRIVER_LICENSE_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])(?:водительск\w*|удостоверени\w*)", re.IGNORECASE)
_SNILS_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])сн[иы][лс][сл][а-яё]{0,3}(?![а-яё])", re.IGNORECASE)
_OMS_KEYWORD_RE = re.compile(
    r"(?<![а-яёa-z])(?:пол[иеёю]с\w*|о\W?м\W?с|осм|оэмэс)(?![а-яёa-z])", re.IGNORECASE
)

# ОГРНИП, the registration number of a sole proprietor: personal, unlike the company's ОГРН.
_OGRNIP_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])о\W?г\W?р\W?н\W?и\W?п(?![а-яёa-z])", re.IGNORECASE)
# КПП and ОГРН of a legal entity: public registry data, masked on request under their own type.
# "огргн" is the spelling a recogniser produces for "огрн"; the lookahead keeps "огрнип" apart.
_KPP_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])кпп(?![а-яёa-z])", re.IGNORECASE)
_OGRN_KEYWORD_RE = re.compile(r"(?<![а-яёa-z])о\W?г\W?р\W?(?:г\W?н|н|г)(?![а-яё])", re.IGNORECASE)

_IDENTIFIER_KEYWORDS = (
    ("INN", _INN_KEYWORD_RE),
    ("PASSPORT", _PASSPORT_KEYWORD_RE),
    ("DRIVER_LICENSE", _DRIVER_LICENSE_KEYWORD_RE),
    ("SNILS", _SNILS_KEYWORD_RE),
    ("OMS", _OMS_KEYWORD_RE),
    ("OGRNIP", _OGRNIP_KEYWORD_RE),
    ("KPP", _KPP_KEYWORD_RE),
    ("OGRN", _OGRN_KEYWORD_RE),
)
# Named identifiers that have no checksum to check, so the name alone decides.
_NAMED_WITHOUT_CHECKSUM = {"PASSPORT", "DRIVER_LICENSE", "SNILS", "OMS"}
# Named legal-entity numbers and the type each is masked under: a company's, not a person's.
_ORG_NAMES = {"KPP": "ORG_ID", "OGRN": "ORG_ID"}
# How far back a name may sit before a number and still apply. On pii_bench 120 characters
# gave the best overall F1 (96.7 against 96.5 for 40): driver-licence and passport labels
# rise, INN and SNILS dip slightly.
_NAME_WINDOW = 120
# Identifier labels the model may guess wrongly, and the digits they cover.
_IDENTIFIER_LABELS = frozenset({"INN", "PASSPORT", "DRIVER_LICENSE", "SNILS", "OMS"})
_DIGIT_SPAN_RE = re.compile(r"[\d\s\-‐‑–—./]+")


def _named_identifier(text: str, start: int) -> str | None:
    """The identifier the speaker named last before these digits, if no digits came after it.

    Only words may come between the keyword and the digits. A digit run in between is
    another identifier: in "ИНН 7707083893, КПП 770101001" the keyword belongs to the
    first number, so the KPP is not mistaken for a tax id. When several keywords sit in
    the window, the nearest one wins: in "ИНН …, паспорт 4508 123456" the number is a
    passport.
    """
    window = text[max(0, start - _NAME_WINDOW) : start]
    label, nearest = None, -1
    for name, pattern in _IDENTIFIER_KEYWORDS:
        matches = list(pattern.finditer(window))
        if not matches:
            continue
        last = matches[-1]
        if last.end() > nearest and not any(char.isdigit() for char in window[last.end() :]):
            label, nearest = name, last.end()
    return label


def find_candidates(text: str) -> list[Span]:
    """Every structured identifier in the text, validated by shape and checksum."""
    spans: list[Span] = []
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return not any(start < other_end and other_start < end for other_start, other_end in taken)

    for match in _PASSPORT_RE.finditer(text):
        # Ten contiguous digits go to the rules below when the speaker named another
        # identifier, or when their tax-id sum holds. Left to this pattern, every such
        # run was a passport: a named INN with a wrong sum came out as one.
        named = _named_identifier(text, match.start())
        if (
            re.fullmatch(r"\d{10}", match.group())
            and _standalone_number(text, match.start())
            and named != "PASSPORT"
            and (named is not None or _inn_valid(match.group()))
        ):
            continue
        if free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "PASSPORT"))
            taken.append((match.start(), match.end()))

    for match in _MAC_RE.finditer(text):
        if free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "NUMBER"))
            taken.append((match.start(), match.end()))

    for match in _IPV4_RE.finditer(text):
        if _valid_ipv4(match.group()) and free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "IP_ADDRESS"))
            taken.append((match.start(), match.end()))

    for match in _IPV6_TOKEN_RE.finditer(text):
        if _ipv6(match.group()) and free(match.start(), match.end()):
            spans.append(_span(match.start(), match.end(), "IP_ADDRESS"))
            taken.append((match.start(), match.end()))

    # Grouped spellings. The checksum still has to hold: "110 116 101 114" is a
    # column of character codes, not a tax id. A name for the same document is
    # enough when the checksum fails, as it is for the digit runs below.
    for pattern, validator, label in (
        (_SPACED_INN_RE, _inn_valid, "INN"),
        (_SPACED_SNILS_RE, _snils_valid, "SNILS"),
    ):
        for match in pattern.finditer(text):
            digits = re.sub(r"\D", "", match.group())
            named = _named_identifier(text, match.start())
            if (validator(digits) or named == label) and free(match.start(), match.end()):
                spans.append(_span(match.start(), match.end(), label))
                taken.append((match.start(), match.end()))

    # Keyword-led numbers. The keyword is the only evidence, so the number must follow it closely.
    for match in _CVC_RE.finditer(text):
        start, end = match.span("number")
        if free(start, end):
            spans.append(_span(start, end, "CREDIT_CARD"))
            taken.append((start, end))
    for match in _SECRET_RE.finditer(text):
        start, end = match.span("number")
        token = match.group("number")
        # Letters and digits together: a long English word after "токен" is not a token.
        if len(token) >= 20 and re.search(r"\d", token) and re.search(r"[A-Za-z]", token) and free(start, end):
            spans.append(_span(start, end, "SECRET"))
            taken.append((start, end))
    for regex in (_OTP_RE, _OTP_CONFIRM_RE):
        for match in regex.finditer(text):
            start, end = match.span("number")
            if free(start, end):
                spans.append(_span(start, end, "SECRET"))
                taken.append((start, end))
    for match in _PASSPORT_NUMBER_RE.finditer(text):
        start, end = match.span("number")
        if _named_identifier(text, start) == "PASSPORT" and free(start, end):
            spans.append(_span(start, end, "PASSPORT"))
            taken.append((start, end))

    # A company's number named in its own words: the registration wording is the only evidence.
    for match in _REGISTRATION_NUMBER_RE.finditer(text):
        start, end = match.span("number")
        if free(start, end):
            spans.append(_span(start, end, "ORG_ID"))
            taken.append((start, end))
    for span in _card_code_spans(text):
        if free(span.start, span.end):
            spans.append(span)
            taken.append((span.start, span.end))
    for span in _company_number_spans(text):
        if free(span.start, span.end):
            spans.append(span)
            taken.append((span.start, span.end))
    # A bare code comes after the card rules, so a card sentence keeps its CREDIT_CARD label.
    for match in _GENERIC_CODE_RE.finditer(text):
        start, end = match.span("number")
        if free(start, end):
            spans.append(_span(start, end, "SECRET"))
            taken.append((start, end))

    for match in _DIGITS_RE.finditer(text):
        digits = match.group()
        if not free(match.start(), match.end()):
            continue
        named = _named_identifier(text, match.start()) if 9 <= len(digits) <= 19 else None
        # A name for another document decides over a tax-id sum that happens to hold.
        if len(digits) in (10, 12) and _inn_valid(digits) and named in (None, "INN"):
            if _standalone_number(text, match.start()):
                spans.append(_span(match.start(), match.end(), "INN"))
        elif named == "INN" and _standalone_number(text, match.start()):
            # The speaker named a tax id, so mask it even though the digits
            # fail their checksum: a wrong checksum here usually means the
            # recogniser miscounted a digit, not that the number is harmless.
            spans.append(_span(match.start(), match.end(), "INN"))
        elif len(digits) == 11 and _snils_valid(digits):
            spans.append(_span(match.start(), match.end(), "SNILS"))
        elif named == "OGRNIP" and _standalone_number(text, match.start()):
            # A sole proprietor's number has no checksum the rules could check, and it may pass Luhn.
            spans.append(_span(match.start(), match.end(), "OGRNIP"))
        elif named in _ORG_NAMES and _standalone_number(text, match.start()):
            # A name for a company's number decides its type before a checksum that may hold by chance.
            spans.append(_span(match.start(), match.end(), _ORG_NAMES[named]))
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            spans.append(_span(match.start(), match.end(), "CREDIT_CARD"))
        elif named in _NAMED_WITHOUT_CHECKSUM and _standalone_number(text, match.start()):
            # Another named document masks the digits too. Its number has no control
            # sum to check, so the name is what makes the run an identifier.
            spans.append(_span(match.start(), match.end(), named))
        elif len(digits) == 11 and digits[0] in "78" and _standalone_number(text, match.start()):
            # Eleven digits from 7 or 8 are a Russian phone number when no checksum or name says
            # otherwise. Left unmasked, such a number went out whole.
            spans.append(_span(match.start(), match.end(), "PHONE"))

    # Spoken numbers, in digit words or cardinal words. The digits of the run decide what
    # it is. A named identifier decides its label. Without a name, a checksum that holds
    # gives INN or SNILS, and any other run of ten or more digits is masked as a generic
    # NUMBER: a number spoken aloud is not safe to show, whatever it is.
    for match in _NUMBER_RUN_RE.finditer(text):
        start, end = match.start(), match.end()
        if not free(start, end) or not _standalone_number(text, start) or _amount_context(text, start, end):
            continue
        words = [word.group().lower() for word in _WORD_RE.finditer(match.group())]
        digits = _spoken_digits(words)
        if len(digits) < 9:
            continue
        named = _named_identifier(text, start)
        if named is not None and 9 <= len(digits) <= 19:
            label = _ORG_NAMES.get(named, named)
        elif len(digits) in (10, 12) and _inn_valid(digits):
            label = "INN"
        elif len(digits) == 11 and _snils_valid(digits):
            label = "SNILS"
        elif len(digits) >= 10:
            label = "NUMBER"
        else:
            continue
        spans.append(_span(start, end, label))
        taken.append((start, end))

    # Grouped readings, checked after the spaces are squeezed out. The checksum
    # is what keeps this from swallowing ordinary prose: "14 марта 2026 года"
    # and "4500 рублей" never add up to a valid card or tax id.
    for match in _GROUPED_NUMBER_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        digits = re.sub(r"\s", "", match.group())
        named = _named_identifier(text, match.start()) if 9 <= len(digits) <= 19 else None
        if len(digits) in (10, 12) and _inn_valid(digits):
            spans.append(_span(match.start(), match.end(), "INN"))
        elif named == "INN":
            spans.append(_span(match.start(), match.end(), "INN"))
        elif len(digits) == 11 and _snils_valid(digits):
            spans.append(_span(match.start(), match.end(), "SNILS"))
        elif 13 <= len(digits) <= 19 and _luhn(digits):
            spans.append(_span(match.start(), match.end(), "CREDIT_CARD"))
        elif named in _NAMED_WITHOUT_CHECKSUM:
            spans.append(_span(match.start(), match.end(), named))
        elif named in _ORG_NAMES:
            spans.append(_span(match.start(), match.end(), _ORG_NAMES[named]))
        elif len(digits) == 11 and digits[0] in "78":
            # The same eleven-digit phone rule as the contiguous digits, for a spaced spelling.
            spans.append(_span(match.start(), match.end(), "PHONE"))
    return spans


def relabel_by_name(text: str, model_spans: list[Span]) -> list[Span]:
    """Give a model span the identifier its name asks for, when the model guessed another one.

    The span keeps its place and its score, so the masked text does not change, only the
    label does. Only digit spans move, and only between identifier types: a phone or a card
    is never renamed, because a name in front of them is no evidence about what they are.
    """
    relabelled: list[Span] = []
    for span in model_spans:
        named = _named_identifier(text, span.start) if span.label in _IDENTIFIER_LABELS else None
        if (
            named in _IDENTIFIER_LABELS
            and named != span.label
            and _DIGIT_SPAN_RE.fullmatch(text[span.start : span.end])
        ):
            relabelled.append(Span(start=span.start, end=span.end, label=named, score=span.score))
        else:
            relabelled.append(span)
    return relabelled


def fill_gaps(text: str, model_spans: list, rule_spans: list[Span], keep=None) -> list[Span]:
    """Keep only the parts of each rule span the model did not already cover.

    A gap that holds no digits and no number words is dropped: it is the connector
    between two numbers -- the word "номер" between a passport series and its number
    -- and masking it would hide ordinary text while protecting nothing.
    """
    keep = keep or _holds_number
    result: list[Span] = []
    for rule in rule_spans:
        cursor = rule.start
        for start, end in sorted((s.start, s.end) for s in model_spans):
            if end <= cursor:
                continue
            if start >= rule.end:
                break
            if start > cursor:
                result.extend(_gaps(cursor, min(start, rule.end), rule.label, text, keep))
            cursor = max(cursor, end)
        if cursor < rule.end:
            result.extend(_gaps(cursor, rule.end, rule.label, text, keep))
    return result


def _gaps(start: int, end: int, label: str, text: str, keep) -> list[Span]:
    if keep(text[start:end]):
        return [_span(start, end, label)]
    return []


def _holds_number(segment: str) -> bool:
    """A digit, or a word that stands for one ("девять", "тридцать"): both are number material."""
    return any(char.isdigit() for char in segment) or any(
        word.group().lower() in _NUMBER_WORDS for word in _WORD_RE.finditer(segment)
    )


# Names and places written as ordinary words, which the digit rules cannot see.
_CAPITAL_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]+")
_STREET_ADJECTIVE_RE = re.compile(r"[А-ЯЁ][а-яё]*(?:ской|ская|скую|ский|ском)")
_PREPOSITIONS_BEFORE_STREET = {"на", "в", "по", "от", "к", "у"}
_PLACE_PREPOSITIONS = {"в", "во", "из", "на", "под", "от"}
# Initials before a surname: "В . М . Брадисе", "П. Петрова", "И.И. Иванов". One or two capital
# letters, each followed by a dot, then the surname. A lone initial names nobody and is left alone.
_INITIALS_RE = re.compile(r"(?<![А-Яа-яЁё])(?:[А-ЯЁ]\s?\.\s?){1,2}[А-ЯЁ][а-яё]+")


def find_word_candidates(text: str) -> list[Span]:
    """Surnames in an oblique case and street adjectives after a preposition.

    A capitalised surname that the model missed ("Ковалёвой нужно перезвонить") is a
    person, and a street adjective after a preposition ("офис на Тверской") is a place.
    Both rules are narrow: on pii_bench they add a token or two and cost about as much
    in ordinary text, so they are kept for the cases a real meeting produces.
    """
    spans: list[Span] = []
    initials: list[tuple[int, int]] = []
    for match in _INITIALS_RE.finditer(text):
        # The word after the initials must read as a name, not as an ordinary word:
        # "Н . А . Кадровый" is a heading, "М . В . Рассмотрены" is a verb.
        surname = re.search(r"[А-ЯЁ][а-яё]+$", match.group()).group()
        if not names.name_like(surname):
            continue
        # The initials are masked with the surname: together they name the person. The
        # benchmark labels some initials as not personal data, and real Russian text does not.
        spans.append(_span(match.start(), match.end(), "PERSON"))
        initials.append((match.start(), match.end()))
    for match in _SOLE_PROPRIETOR_SURNAME_RE.finditer(text):
        if names.surname_like(match.group("word")):
            spans.append(_span(match.start("word"), match.end("word"), "PERSON"))
    for match in _HYPHENATED_WORD_RE.finditer(text):
        if any(part[:1].isupper() and names.geo_word(part) for part in match.group().split("-")):
            spans.append(_span(match.start(), match.end(), "LOCATION"))
    for match in _CAPITAL_WORD_RE.finditer(text):
        if any(start <= match.start() < end for start, end in initials):
            continue
        word = match.group()
        before = re.search(r"([А-Яа-яЁё]+)\s*$", text[: match.start()])
        if names.oblique_surname(word):
            spans.append(_span(match.start(), match.end(), "PERSON"))
        elif _STREET_ADJECTIVE_RE.fullmatch(word):
            if before and before.group(1) in _PREPOSITIONS_BEFORE_STREET:
                spans.append(_span(match.start(), match.end(), "LOCATION"))
        elif names.geo_word(word):
            if before and before.group(1).lower() in _PLACE_PREPOSITIONS:
                spans.append(_span(match.start(), match.end(), "LOCATION"))
    spans.extend(_address_spans(text))
    return spans


# House, flat, building and entrance numbers. A number alone names no one, but beside a unit word
# or after a street it locates a home, so the number is masked as an address part.
_UNIT_RE = re.compile(
    r"(?<![а-яёa-z])(?:кв|квартира|д|дом|корп|корпус|стр|строение|офис|подъезд|подьезд)\.?\s*"
    r"(?P<number>\d{1,4}(?:[а-яё]\d{0,2})?)(?!\d)",
    re.IGNORECASE,
)
# "3 подъезд", "5 этаж": a number before its unit word. "этажей" is a count, not a floor, and the
# lookahead keeps it out.
_ENTRANCE_BEFORE_RE = re.compile(
    r"(?<![а-яёa-z\d])(?P<number>\d{1,3})\s*(?:подъезд|подьезд|этаж)(?![а-яё])", re.IGNORECASE
)
# Hyphenated names: "Санкт-Петербург" is one place, though only its second part reads as one.
_HYPHENATED_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё]+)+")
# A sole proprietor named in lowercase: "у ип сидоров". The capital letter is missing, so the word's
# grammar decides: a surname in some case, not an ordinary verb or noun.
_SOLE_PROPRIETOR_SURNAME_RE = re.compile(r"(?<![А-Яа-яЁё])(?i:ип)\s+(?P<word>[а-яё]{3,})(?![А-Яа-яЁё])")
# A street word, its name and the house number after it: "ул. Тверская 15". The name is part of the
# address as much as the number is, so both are masked. Only the keyword is case-insensitive.
_STREET_RE = re.compile(
    r"(?<![А-ЯЁа-яёA-Za-z])(?i:ул|улица|пр|просп|проспект|пер|переулок|наб|набережная|пл|площадь|б-р|бульвар|ш|шоссе)"
    r"\.?\s+(?P<name>[А-ЯЁ][А-ЯЁа-яё-]+(?:\s+[А-ЯЁ][А-ЯЁа-яё-]+)?)"
    r"(?:[\s,]+(?P<number>\d{1,4}(?:[а-яё]\d{0,2})?)(?!\d))?"
)


def _sentence_at(text: str, position: int) -> str:
    """The sentence around a position: the text between the nearest full stops, marks or breaks."""
    left = max(text.rfind(mark, 0, position) for mark in ".!?\n")
    rights = [index for index in (text.find(mark, position) for mark in ".!?\n") if index != -1]
    return text[left + 1 : min(rights, default=len(text))]


def _card_code_spans(text: str) -> list[Span]:
    """Three-digit codes on the back of a card, asked for right before the number in a sentence
    about a card or a payment."""
    spans: list[Span] = []
    for match in re.finditer(r"(?<!\d)\d{3}(?!\d)", text):
        before = text[max(0, match.start() - 80) : match.start()]
        if _CODE_ASK_RE.search(before) is None and _STRONG_CODE_ASK_RE.search(before) is None:
            continue
        if _AMOUNT_AFTER_RE.match(text, match.end()):
            continue
        # The card word may sit in the sentence before: "оператор просит CVC, это нормально? вот 012".
        if _CARD_WORD_RE.search(text[max(0, match.start() - 120) : match.end()]) is None:
            continue
        spans.append(_span(match.start(), match.end(), "CREDIT_CARD"))
    return spans


# Words that put a thirteen-digit number in a company's paperwork. The number has no keyword of its
# own in these sentences, so the sentence is the evidence: a legal entity's registration number.
_COMPANY_CONTEXT_RE = re.compile(
    r"контрагент|реквизит|поставщик|налогов|закупк|организац|компани|юрлиц|юридическ|сверки|"
    r"значится|указан|анкет|карточк|ООО|ЗАО|ПАО|\bАО\b",
    re.IGNORECASE,
)


def _company_number_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in re.finditer(r"(?<!\d)\d{13}(?!\d)", text):
        if not _standalone_number(text, match.start()):
            continue
        if _COMPANY_CONTEXT_RE.search(text[max(0, match.start() - 120) : match.end()]) is None:
            continue
        spans.append(_span(match.start(), match.end(), "ORG_ID"))
    return spans


def _address_spans(text: str) -> list[Span]:
    spans: list[Span] = []
    for pattern in (_UNIT_RE, _ENTRANCE_BEFORE_RE):
        for match in pattern.finditer(text):
            spans.append(_span(match.start("number"), match.end("number"), "LOCATION"))
    for match in _STREET_RE.finditer(text):
        spans.append(_span(match.start("name"), match.end("name"), "LOCATION"))
        if match.group("number") is not None:
            spans.append(_span(match.start("number"), match.end("number"), "LOCATION"))
    return spans


def fill_word_gaps(text: str, model_spans: list, word_spans: list[Span]) -> list[Span]:
    """As fill_gaps, for word spans: a name has no digits, so every uncovered part is kept."""
    return fill_gaps(text, model_spans, word_spans, keep=lambda segment: bool(segment.strip()))
