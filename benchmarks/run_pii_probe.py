"""What the masking layer actually catches on realistic Russian PII.

The first pass through this used formats that do not occur in speech -- a
15-digit INN, a passport split by the word "номер" -- and both were correctly
rejected by the rules. That is a useful result in itself: the checksum rules
refuse invalid numbers instead of masking anything that looks numeric.

This checks the formats that do occur, including the ones where the rules are
expected to give up and the NER model has to carry the load.

Run: .venv/bin/python benchmarks/run_pii_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
from masking import mask  # noqa: E402
from ner import PiiNer  # noqa: E402


def valid_inn(length: int) -> str:
    """A number the checksum accepts. An INN that fails its checksum is not an
    INN, and the rules correctly refuse to call it one -- so a probe built from
    made-up digits measures nothing."""
    if length == 12:
        weights = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        base = "1000000000"
    else:
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        base = "900000000"
    check = sum(int(base[i]) * weights[i] for i in range(len(base))) % 11 % 10
    partial = base + str(check)
    if length == 10:
        return partial
    weights12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    check12 = sum(int(partial[i]) * weights12[i] for i in range(11)) % 11 % 10
    return partial + str(check12)


def valid_card() -> str:
    body = "427638001234567"
    total = 0
    for index, char in enumerate(reversed(body)):
        value = int(char)
        if index % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return body + str((10 - total % 10) % 10)


def valid_snils() -> str:
    base = "112334556"
    total = sum(int(base[i]) * (9 - i) for i in range(9))
    check = total if total < 100 else (0 if total in (100, 101) else total % 101)
    return base + f"{check:02d}"


INN_10, INN_12 = valid_inn(10), valid_inn(12)
CARD, SNILS = valid_card(), valid_snils()

# Each case: what a person actually says on a call, and whether the value has to
# disappear. "rule" = caught by regex+checksum, "model" = only the NER catches it.
CASES = [
    ("телефон мобильный", "+7 916 448 22 09", True, "rule"),
    ("телефон с кодом", "8 (912) 345-67-89", True, "rule"),
    ("почта", "svetlana.kuznetsova@yandex.ru", True, "model"),
    ("ФИО", "Светлана Николаевна Кузнецова", True, "model"),
    ("адрес", "Москва, улица Тверская, дом 12, квартира 34", True, "model"),
    ("карта (проходит Луна)", CARD, True, "rule"),
    ("ИНН физлица (10)", INN_10, True, "rule"),
    ("ИНН ИП (12)", INN_12, True, "rule"),
    ("СНИЛС (11)", SNILS, True, "rule"),
    ("паспорт слитно", "серия 4508 номер 123456", True, "model"),
    ("паспорт через слово", "серия 45 08 номер 123456", True, "model"),
    ("паспорт слитно с пробелом", "серия 4508 123456", True, "rule"),
    ("IP", "192.168.10.55", True, "rule"),
    ("заказ номер", "заказ номер 4471", False, "—"),
    ("сумма", "переплата 4500 рублей", False, "—"),
    ("дата", "договор от 14 марта 2026 года", False, "—"),
]


def main() -> int:
    ner = PiiNer(config.PII_NER_DIR, threads=config.INFERENCE_THREADS)
    print(f"провайдеры: {config.ort_providers()}")
    print()
    print(f"{'случай':26s} {'ожид.':7s} {'NER':9s} {'итог':7s}")
    print("-" * 52)

    failures = []
    for name, value, must_mask, expected_by in CASES:
        text = f"Меня зовут Анна, говорю {value} по поводу обращения."
        rule_labels: list[str] = []
        model_labels = [span.label for span in ner.predict(text)]
        result = mask(text, spans + ner.predict(text))
        masked = value not in result.masked_text
        ok = masked == must_mask
        if not ok:
            failures.append((name, value, must_mask, masked))
        print(
            f"{name:26s} {'скрыть' if must_mask else 'не трогать':7s} "
            f"{','.join(model_labels) or '-':9s} "
            f"{'ок' if ok else 'ПРОВАЛ':7s}"
        )

    print()
    if failures:
        print("расхождения с ожиданием:")
        for name, value, must, got in failures:
            print(f"  {name}: {value!r} — {'надо скрыть' if must else 'не надо'}, скрыто={got}")
    else:
        print("все случаи сходятся с ожиданием")

    print()
    print("проверка на утечку целиком, текст звонка:")
    call = (
        f"Здравствуйте, Светлана Николаевна Кузнецова, телефон +7 916 448 22 09, "
        f"почта svetlana.kuznetsova@yandex.ru, ИИН {INN_12}, "
        f"карта {CARD}, СНИЛС {SNILS}, адрес Москва, улица Тверская, дом 12."
    )
    merged = ner.predict(call)
    result = mask(call, merged)
    print(result.masked_text)
    print()
    print(f"сущностей: {len(result.entities)}")
    for entity in result.entities:
        print(f"  {entity.label:14s} {entity.text!r}")
    leaks = [entity.text for entity in result.entities if entity.text in result.masked_text]
    print(f"утечки: {leaks if leaks else 'нет'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())