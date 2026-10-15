"""Pilot evaluation: how well the app masks personal data in a client's own recordings.

run_pii_bench_ru.py scores the masking on public data. This script scores it on the recordings
of a pilot client, whose team has labelled the personal data by hand: one JSON gold file per
recording (format in benchmarks/pilot/README.md).

The masking is the app's own, exactly as in run_pii_bench_ru.py: main._spans, then
masking.hidden_spans, which is what mask() hides. Coverage counts the \\w characters of a gold
span (letters, digits and underscore), so spaces and punctuation around a span do not count.

PRIVACY. The gold files are client data. --report and --json hold counts and recording ids
only: no span text, no examples, no asr_text, no offsets. Messages name a file and an index,
never a value. The one place that shows span text is --examples, which prints to stdout and
writes nothing.

Run: api/.venv/bin/python benchmarks/pilot_eval.py <folder of *.json> [--report PATH] [--json PATH] [--examples]
Exit codes: 0 every file accepted, 1 some files rejected, 2 no file accepted.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(ROOT / "api"))

import main as pipeline  # noqa: E402
from masking import hidden_spans  # noqa: E402

# The display types a gold span may carry: the types the app's UI shows.
TYPES = (
    "PERSON", "ADDRESS", "PHONE", "EMAIL", "URL", "IP", "PASSPORT", "INN", "SNILS", "OMS",
    "DRIVER_LICENSE", "MILITARY_ID", "BIRTH_CERTIFICATE", "CARD", "SECRET", "OGRNIP", "ORG_ID",
    "NUMBER",
)
TOP_LEVEL = {"recording", "asr_text", "spans", "asr_missed"}
COUNTED = re.compile(r"\w+")  # the characters coverage counts, as in run_pii_bench_ru.py
LETTER_OR_DIGIT = re.compile(r"[^\W_]")  # a gold span needs at least one of these
TIMESTAMP = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")  # speaker turns: "Спикер 1 [0:12]: ..."
WARNING = (
    "Внимание: --report и --json содержат только счётчики и id записей, без текста, примеров "
    "и смещений. Текст пропусков печатает только --examples, и только в терминал."
)
HEADER = ("тип", "фрагм.", "покрытие букв", "полностью", "пропущено", "ASR не дал", "лишние маски, симв.")


class Rejected(Exception):
    """A file that cannot be scored. The text names the place, never a value from the file."""

    def __init__(self, reason: str, recording: str | None = None):
        super().__init__(reason)
        self.recording = recording


@dataclass
class Gold:
    recording: str
    text: str
    spans: list[tuple[int, int, str]]  # (start, end, type)
    asr_missed: list[tuple[str, str]]  # (type, time)


@dataclass
class Tally:
    """Counts for one type. A total is the sum of the types."""

    gold_spans: int = 0
    gold_chars: int = 0  # counted characters of the gold spans
    covered_chars: int = 0  # of those, the ones inside a masked span
    fully_masked: int = 0  # gold spans whose every counted character is masked
    asr_missed: int = 0  # entries the recognition did not produce; not part of coverage
    over_masked_chars: int = 0  # masked characters that no gold span covers

    def add(self, other: Tally) -> None:
        for item in fields(self):
            setattr(self, item.name, getattr(self, item.name) + getattr(other, item.name))

    @property
    def missed_spans(self) -> int:
        return self.gold_spans - self.fully_masked

    @property
    def recall(self) -> float | None:
        return self.covered_chars / self.gold_chars if self.gold_chars else None


@dataclass
class Miss:
    """A gold span that is not fully masked. Its text is shown by --examples only."""

    type: str
    text: str
    share: float  # share of its counted characters that are masked
    time: str  # timestamp of the speaker turn it sits in, "" if there is none before it


@dataclass
class Result:
    recording: str
    tallies: dict[str, Tally]
    misses: list[Miss]
    asr_missed: list[tuple[str, str]]


def read_gold(path: Path) -> Gold:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise Rejected(f"файл не читается: {type(error).__name__}") from None
    except UnicodeDecodeError:
        raise Rejected("файл не в UTF-8") from None
    except json.JSONDecodeError as error:
        raise Rejected(f"не читается как JSON, строка {error.lineno}") from None
    if not isinstance(data, dict):
        raise Rejected("верхний уровень должен быть объектом {...}")
    recording = data.get("recording")
    if not isinstance(recording, str) or not recording.strip():
        raise Rejected("нет поля recording (непустая строка)")
    try:
        return check_gold(data, recording)
    except Rejected as error:
        error.recording = recording
        raise


def check_gold(data: dict, recording: str) -> Gold:
    # An unknown top-level field is refused: a misspelt "asr_missed" would silently zero a bucket.
    if set(data) - TOP_LEVEL:
        raise Rejected("лишние поля верхнего уровня (допустимы recording, asr_text, spans, asr_missed)")
    text = data.get("asr_text")
    if not isinstance(text, str):
        raise Rejected("поле asr_text: нужна строка")
    raw_spans = data.get("spans")
    if not isinstance(raw_spans, list):
        raise Rejected("поле spans: нужен список")
    raw_missed = data.get("asr_missed", [])
    if not isinstance(raw_missed, list):
        raise Rejected("поле asr_missed: нужен список или поля нет")
    spans = [check_span(raw, index, text) for index, raw in enumerate(raw_spans)]
    check_overlaps(spans)
    missed = [check_missed(raw, index) for index, raw in enumerate(raw_missed)]
    return Gold(recording, text, spans, missed)


def check_span(raw: object, index: int, text: str) -> tuple[int, int, str]:
    name = f"spans[{index}]"
    if not isinstance(raw, dict):
        raise Rejected(f"{name}: нужен объект")
    start, end = raw.get("start"), raw.get("end")
    if type(start) is not int or type(end) is not int:
        raise Rejected(f"{name}: start и end нужны целыми числами")
    if raw.get("type") not in TYPES:
        raise Rejected(f"{name}: неизвестный тип метки, допустимы: {', '.join(TYPES)}")
    if not 0 <= start < end <= len(text):
        raise Rejected(f"{name}: смещения вне asr_text (нужно 0 <= start < end <= длина)")
    if not LETTER_OR_DIGIT.search(text, start, end):
        raise Rejected(f"{name}: во фрагменте нет букв и цифр")
    return start, end, raw["type"]


def check_overlaps(spans: list[tuple[int, int, str]]) -> None:
    """Two gold spans may not share a character: each character is counted once."""
    order = sorted(range(len(spans)), key=lambda index: spans[index][:2])
    for before, after in zip(order, order[1:]):
        if spans[after][0] < spans[before][1]:
            raise Rejected(f"spans[{before}] и spans[{after}] пересекаются")


def check_missed(raw: object, index: int) -> tuple[str, str]:
    name = f"asr_missed[{index}]"
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        raise Rejected(f"{name}: неизвестный тип метки, допустимы: {', '.join(TYPES)}")
    time = raw.get("time", "")
    if not isinstance(time, str):
        raise Rejected(f"{name}: time нужна строкой")
    return raw["type"], time


def speaker_time(text: str, position: int) -> str:
    """Timestamp of the speaker turn that holds ``position``, to find the place in the audio."""
    found = TIMESTAMP.findall(text, 0, position)
    return found[-1] if found else ""


def score(gold: Gold, masked: list) -> Result:
    text = gold.text
    # The type of the masked span that covers each character, None where nothing is masked.
    covered_by: list[str | None] = [None] * len(text)
    for span in masked:
        for index in range(span.start, min(span.end, len(text))):
            covered_by[index] = span.display_type
    in_gold = [False] * len(text)
    for start, end, _ in gold.spans:
        for index in range(start, end):
            in_gold[index] = True

    tallies: dict[str, Tally] = defaultdict(Tally)
    misses: list[Miss] = []
    for start, end, kind in gold.spans:
        counted = [i for match in COUNTED.finditer(text, start, end) for i in range(match.start(), match.end())]
        hit = sum(covered_by[i] is not None for i in counted)
        tally = tallies[kind]
        tally.gold_spans += 1
        tally.gold_chars += len(counted)
        tally.covered_chars += hit
        if hit == len(counted):
            tally.fully_masked += 1
        else:
            misses.append(Miss(kind, text[start:end], hit / len(counted), speaker_time(text, start)))
    for kind, _ in gold.asr_missed:
        tallies[kind].asr_missed += 1
    for index, kind in enumerate(covered_by):
        if kind is not None and not in_gold[index]:
            tallies[kind].over_masked_chars += 1
    return Result(gold.recording, dict(tallies), misses, gold.asr_missed)


def score_file(path: Path, seen: set[str]) -> Result:
    gold = read_gold(path)
    if gold.recording in seen:
        raise Rejected("такой recording уже есть в другом файле", gold.recording)
    try:
        masked = hidden_spans(gold.text, pipeline._spans(gold.text))
    except Exception as error:  # one broken recording must not stop the run; only the class name is shown
        raise Rejected(f"ошибка маскирования: {type(error).__name__}", gold.recording) from None
    seen.add(gold.recording)
    return score(gold, masked)


def describe(tally: Tally) -> dict:
    """The counts of one type, as the report and the JSON write them."""
    return {
        "gold_spans": tally.gold_spans,
        "gold_chars": tally.gold_chars,
        "covered_chars": tally.covered_chars,
        "recall_chars": None if tally.recall is None else round(tally.recall, 4),
        "fully_masked": tally.fully_masked,
        "missed_spans": tally.missed_spans,
        "asr_missed": tally.asr_missed,
        "over_masked_chars": tally.over_masked_chars,
    }


def total_of(tallies) -> Tally:
    total = Tally()
    for tally in tallies:
        total.add(tally)
    return total


def summary(results: list[Result], rejected: list[dict]) -> dict:
    by_type: dict[str, Tally] = defaultdict(Tally)
    for result in results:
        for kind, tally in result.tallies.items():
            by_type[kind].add(tally)
    order = sorted(by_type, key=lambda kind: (-by_type[kind].gold_spans, kind))
    return {
        "date": datetime.date.today().isoformat(),
        "files": {"accepted": len(results), "rejected": len(rejected)},
        "types": {kind: describe(by_type[kind]) for kind in order},
        "totals": describe(total_of(by_type.values())),
        "recordings": [
            {"recording": result.recording, **describe(total_of(result.tallies.values()))} for result in results
        ],
        "rejected": rejected,
    }


def table_rows(data: dict) -> list[list[str]]:
    rows = []
    for kind, counts in [*data["types"].items(), ("ИТОГО", data["totals"])]:
        recall = "—" if counts["recall_chars"] is None else f"{counts['recall_chars']:.1%}"
        rows.append([
            kind, str(counts["gold_spans"]), recall, str(counts["fully_masked"]),
            str(counts["missed_spans"]), str(counts["asr_missed"]), str(counts["over_masked_chars"]),
        ])
    return rows


def print_table(data: dict) -> None:
    rows = [list(HEADER), *table_rows(data)]
    widths = [max(len(row[column]) for row in rows) for column in range(len(HEADER))]
    for index, row in enumerate(rows):
        if index == len(rows) - 1:
            print("  ".join("-" * width for width in widths))
        print("  ".join(text.ljust(width) if column == 0 else text.rjust(width)
                        for column, (text, width) in enumerate(zip(row, widths))))


def print_examples(results: list[Result]) -> None:
    print("\nПропущенные фрагменты (текст только здесь, в файлы не пишется):")
    lines = []
    for result in results:
        for miss in result.misses:
            where = f"реплика {miss.time}" if miss.time else "без времени"
            text = miss.text.replace("\n", " ")
            lines.append(f"  {result.recording}, {where}, {miss.type}, покрыто {miss.share:.0%}: «{text}»")
        for kind, time in result.asr_missed:
            lines.append(f"  {result.recording}, время {time or '—'}, {kind}: ASR не дал фрагмент, текста нет")
    print("\n".join(lines) if lines else "  нет")


def cell(value: object) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "/").replace("\n", " ")


def markdown(data: dict) -> str:
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines = [
        "# Пилотная оценка маскирования",
        "",
        f"Дата: {data['date']}. Принято записей: {data['files']['accepted']}, "
        f"отклонено файлов: {data['files']['rejected']}.",
        "",
        "Отчёт содержит только счётчики и id записей: без текста, примеров и смещений.",
        "",
        "## По типам",
        "",
        line(list(HEADER)),
        line(["---", *["---:"] * (len(HEADER) - 1)]),
        *(line(row) for row in table_rows(data)),
        "",
        "Покрытие букв: доля букв, цифр и подчёркиваний эталонных фрагментов, попавших в маску. "
        "ASR не дал: записи asr_missed, в покрытие не входят. "
        "Лишние маски: символы, замаскированные вне всех эталонных фрагментов. "
        "Тип метки приложения не сверяется: фрагмент считается скрытым, чем бы он ни был помечен.",
        "",
        "## По записям",
        "",
        line(["запись", "фрагм.", "полностью", "пропущено", "ASR не дал", "лишние маски, симв."]),
        line(["---", *["---:"] * 5]),
    ]
    for record in data["recordings"]:
        lines.append(line([
            cell(record["recording"]), str(record["gold_spans"]), str(record["fully_masked"]),
            str(record["missed_spans"]), str(record["asr_missed"]), str(record["over_masked_chars"]),
        ]))
    lines += ["", "## Отклонённые файлы", ""]
    if data["rejected"]:
        lines += [line(["№ файла", "запись", "причина"]), line(["---", "---", "---"])]
        lines += [
            line([str(item["file_number"]), cell(item["recording"]), cell(item["reason"])])
            for item in data["rejected"]
        ]
    else:
        lines.append("Нет.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Оценка маскирования на записях клиента по gold-файлам.")
    parser.add_argument("folder", type=Path, help="папка с gold-файлами *.json")
    parser.add_argument("--report", type=Path, help="markdown-отчёт: только счётчики и id записей")
    parser.add_argument("--json", type=Path, help="то же в JSON: только счётчики и id записей")
    parser.add_argument("--examples", action="store_true",
                        help="напечатать пропущенные фрагменты с текстом (только в терминал)")
    args = parser.parse_args()
    print(WARNING)

    if not args.folder.is_dir():
        print(f"нет папки {args.folder}", file=sys.stderr)
        return 2
    # Outputs written into the gold folder are not inputs, or the next run would reject them.
    outputs = {path.resolve() for path in (args.json, args.report) if path}
    paths = [path for path in sorted(args.folder.glob("*.json")) if path.resolve() not in outputs]
    if not paths:
        print(f"в {args.folder} нет файлов *.json для проверки", file=sys.stderr)
        return 2
    try:
        pipeline.get_ner()  # loaded once, up front: without the model no file can be masked
    except Exception as error:
        print(f"модель маскирования не загрузилась: {error}", file=sys.stderr)
        return 2

    results: list[Result] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for number, path in enumerate(paths, start=1):
        try:
            result = score_file(path, seen)
        except Rejected as error:
            rejected.append({"file_number": number, "recording": error.recording, "reason": str(error)})
            print(f"ОТКЛОНЁН {path.name}: {error}")
            continue
        results.append(result)
        print(f"принят {path.name}: запись {result.recording}")

    data = summary(results, rejected)
    if results:
        print(f"\nПринято записей: {len(results)}, отклонено файлов: {len(rejected)}\n")
        print_table(data)
    else:
        print("\nНи один файл не принят: счётчиков нет.")
    if args.examples and results:
        print_examples(results)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(data), encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not results:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
