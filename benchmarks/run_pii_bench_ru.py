"""Measure the masking stack against PII-Bench (ru), an external Russian benchmark.

hivetrace/pii-bench (Apache-2.0) is span-level and fully synthetic: 1,810 Russian texts with 13
entity types, in two splits. The data is not in the repository. Download the two parquet files
into one folder:

  https://huggingface.co/datasets/hivetrace/pii-bench/resolve/main/data/domain-00000-of-00001.parquet
  https://huggingface.co/datasets/hivetrace/pii-bench/resolve/main/data/entity-00000-of-00001.parquet

Reading them needs pyarrow, a dependency of this benchmark only (pip install pyarrow); the app
does not use it.

The headline token F1 hides what matters for privacy, so each type is also reported by coverage
of its gold span, in characters:
  буквы 100%    every letter and digit of the entity is inside a masked span;
  буквы >=80%   the same, with a tolerance of one word;
  цифры 100%    every digit is masked: a number cannot be recovered from what is left;
  идент. 100%   every digit and capitalised word is masked: the parts that name a person,
                a place or a number. Keyword words such as "ул" or "кв" are left out;
  токены        share of gold tokens touched by a masked span (lenient, for comparison);
  F1 метки      token-level F1 on the app's own labels, with the gold types mapped to them.

Run: api/.venv/bin/python benchmarks/run_pii_bench_ru.py <folder with the two parquet files>
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(HERE))

import main as pipeline  # noqa: E402
import run_pii_benchmark as bench  # noqa: E402
from masking import hidden_spans  # noqa: E402

# The two splits, found by their prefix, so a renamed download works too.
SPLITS = ("domain", "entity")
# The app's label for each gold type. KPP and OGRN are a company's numbers, masked as ORG_ID.
GOLD = {
    "NAME": "PERSON",
    "ADDRESS": "LOCATION",
    "PHONE_NUMBER": "PHONE",
    "BANK_CARD_NUMBER": "CREDIT_CARD",
    "PASSPORT_NUMBER": "PASSPORT",
    "CVC": "CREDIT_CARD",
    "OGRNIP": "OGRNIP",
    "TOKEN": "SECRET",
    "KPP": "ORG_ID",
    "OGRN": "ORG_ID",
}
TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def load(folder: Path, limit: int) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("нужен pyarrow: api/.venv/bin/python -m pip install pyarrow")
    items = []
    for split in SPLITS:
        matches = sorted(folder.glob(f"{split}*.parquet"))
        if len(matches) != 1:
            raise SystemExit(
                f"в {folder} нужен один файл {split}*.parquet, найдено {len(matches)}: "
                "скачайте его с huggingface.co/datasets/hivetrace/pii-bench (data/)"
            )
        for row in pq.read_table(matches[0]).to_pylist():
            entities = [
                {"type": e["type"], "start": int(e["start"]), "end": int(e["end"]), "text": e["text"]}
                for e in row["entities"]
            ]
            items.append({"text": row["text"], "entities": entities, "split": split})
    return items[:limit] if limit else items


def tokens_of(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def gold_types(entities: list[dict], tokens: list[tuple[int, int]]) -> list[str | None]:
    types: list[str | None] = [None] * len(tokens)
    for entity in entities:
        for index, (start, end) in enumerate(tokens):
            if types[index] is None and min(entity["end"], end) > max(entity["start"], start):
                types[index] = entity["type"]
    return types


def entity_positions(entity: dict) -> tuple[list[int], list[int], list[int]]:
    """Absolute offsets inside a gold entity: every letter and digit, the digits alone, and the
    identifying parts (digits and capitalised words)."""
    alnum, digits, identifying = [], [], []
    for match in re.finditer(r"\w+", entity["text"]):
        word = match.group()
        offsets = [entity["start"] + match.start() + k for k in range(len(word))]
        alnum.extend(offsets)
        digits.extend(offset for offset, char in zip(offsets, word) if char.isdigit())
        if word[0].isupper() or word.isdigit():
            identifying.extend(offsets)
    return alnum, digits, identifying


def share(positions: list[int], spans: list) -> float | None:
    """Share of the positions that a masked span covers; None when there are none."""
    if not positions:
        return None
    hit = sum(1 for position in positions if any(s.start <= position < s.end for s in spans))
    return hit / len(positions)


def overlaps(span, start: int, end: int) -> bool:
    return min(span.end, end) > max(span.start, start)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path, help="папка с двумя parquet-файлами PII-Bench")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--examples", type=int, default=0, help="сколько пропусков показать на тип")
    args = parser.parse_args()

    items = load(args.folder, args.limit)
    rows, types_all = [], []
    for item in items:
        tokens = tokens_of(item["text"])
        types = gold_types(item["entities"], tokens)
        rows.append((item["text"], tokens, [GOLD.get(kind, kind) if kind else "O" for kind in types]))
        types_all.append(types)
    print(f"текстов: {len(items)}, сущностей: {sum(len(i['entities']) for i in items)}")

    started = time.perf_counter()
    spans_all = [pipeline._spans(item["text"]) for item in items]
    print(f"время: {time.perf_counter() - started:.1f} с")

    preds = [[(s.start, s.end, bench.FOLD.get(s.label, s.label)) for s in spans] for spans in spans_all]
    result = bench.score(rows, preds)
    precision, recall, f1 = result["prf"](result["total"])
    print(f"токен-F1 {f1 * 100:.1f}  точность {precision * 100:.1f}  полнота {recall * 100:.1f}\n")

    entity_total = collections.Counter()
    full_all, within_80 = collections.Counter(), collections.Counter()
    with_digits, full_digits = collections.Counter(), collections.Counter()
    with_ident, full_ident = collections.Counter(), collections.Counter()
    token_total, token_hit = collections.Counter(), collections.Counter()
    over = collections.Counter()
    misses = collections.defaultdict(list)
    for item, spans, types, (_, tokens, _) in zip(items, spans_all, types_all, rows):
        # Coverage is measured on what mask() hides, not on the raw spans.
        hidden = hidden_spans(item["text"], spans)
        for entity in item["entities"]:
            kind = entity["type"]
            alnum, digits, identifying = entity_positions(entity)
            entity_total[kind] += 1
            letters = share(alnum, hidden) or 0.0
            full_all[kind] += letters >= 0.999
            within_80[kind] += letters >= 0.8
            if letters < 0.8 and len(misses[kind]) < args.examples:
                before = item["text"][max(0, entity["start"] - 30) : entity["start"]]
                misses[kind].append(f"{letters:.0%}  …{before}[[{entity['text']}]]")
            digit_share = share(digits, hidden)
            if digit_share is not None:
                with_digits[kind] += 1
                full_digits[kind] += digit_share >= 0.999
            ident_share = share(identifying, hidden)
            if ident_share is not None:
                with_ident[kind] += 1
                full_ident[kind] += ident_share >= 0.999
        for (start, end), kind in zip(tokens, types):
            if kind is not None:
                token_total[kind] += 1
                token_hit[kind] += any(overlaps(span, start, end) for span in hidden)
            elif item["split"] == "domain":
                for span in spans:
                    if overlaps(span, start, end):
                        over[bench.FOLD.get(span.label, span.label)] += 1
                        break

    def pct(part: int, whole: int) -> str:
        return f"{part / whole:.1%}" if whole else "—"

    print(
        f"{'тип':16s} {'сущн.':>5} {'буквы 100%':>10} {'буквы ≥80%':>10} {'цифры 100%':>10}"
        f" {'идент. 100%':>11} {'токены':>7} {'F1 метки':>9}"
    )
    for kind in sorted(entity_total, key=lambda k: -entity_total[k]):
        label_f1 = result["prf"](result["per_label"].get(GOLD.get(kind, kind), [0, 0, 0]))[2]
        print(
            f"{kind:16s} {entity_total[kind]:5d} {pct(full_all[kind], entity_total[kind]):>10}"
            f" {pct(within_80[kind], entity_total[kind]):>10} {pct(full_digits[kind], with_digits[kind]):>10}"
            f" {pct(full_ident[kind], with_ident[kind]):>11} {pct(token_hit[kind], token_total[kind]):>7}"
            f" {label_f1 * 100:8.1f}%"
        )
    print(f"\nлишние маски в примерах без ПДн (токены по метке): {over.most_common(8)}")
    for kind, examples in misses.items():
        if examples:
            print(f"\nпропуски {kind} (буквы):")
            for example in examples:
                print(f"  {example}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
