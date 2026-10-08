"""Format a diarized transcript for the model.

A meeting is not a wall of text: who spoke and when is part of what the model
must reason about. So the transcript the model sees is built as speaker turns —
``Спикер 2 [12:34]: …`` — and it is this labelled text that gets masked, so the
privacy rule is unchanged: only masked text ever leaves for the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

SPEAKER_LABEL = "Спикер"


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


def words_from_timed_text(text: str, times: list[float]) -> list[Word]:
    """Split ``text`` into words, each carrying the time of its first and next char."""
    words: list[Word] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index].isspace():
            index += 1
            continue
        end = index
        while end < length and not text[end].isspace():
            end += 1
        start_time = times[index] if index < len(times) else 0.0
        end_time = times[end] if end < len(times) else (times[-1] if times else start_time)
        words.append(Word(text[index:end], start_time, max(start_time, end_time)))
        index = end
    return words


def assign_words_to_turns(
    words: list[Word], turns: list[tuple[int, float, float]]
) -> list[tuple[int, float, float, str]]:
    """Assign each word to the speaker turn its midpoint falls in.

    ``turns`` is ``(speaker, start, end)`` sorted by start. A word in a gap is
    kept with the turn it follows, so no word is dropped; adjacent words of one
    speaker merge into one turn. Returns ``(speaker, start, end, text)``.
    """
    if not words or not turns:
        return []
    result: list[tuple[int, float, float, str]] = []
    turn_index = 0
    for word in words:
        # By the word's *start*: diarization boundaries and ASR word times come
        # from different models and jitter by a few tens of ms, so a word that
        # straddles a boundary must stay with the speaker it began in — midpoint
        # assignment moves the last word of a turn to the next speaker.
        while turn_index + 1 < len(turns) and turns[turn_index][2] < word.start:
            turn_index += 1
        speaker, turn_start, turn_end = turns[turn_index]
        if result and result[-1][0] == speaker:
            previous = result[-1]
            result[-1] = (speaker, previous[1], max(previous[2], turn_end), f"{previous[3]} {word.text}".strip())
        else:
            result.append((speaker, turn_start, turn_end, word.text))
    return result


def format_clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def speaker_line_prefix(speaker: int, start: float) -> str:
    return f"{SPEAKER_LABEL} {speaker + 1} [{format_clock(start)}]: "


def build_dialogue(turns: list[tuple[int, float, str]]) -> tuple[str, list[int]]:
    """Join ``(speaker, start_seconds, text)`` turns into one labelled transcript.

    Returns the transcript and, for each turn, the character offset at which its
    own text begins inside it (after the label) — the UI slices entities by that
    offset, so per-turn highlighting keeps working on the labelled text.
    """
    lines: list[str] = []
    offsets: list[int] = []
    cursor = 0
    for speaker, start, text in turns:
        prefix = speaker_line_prefix(speaker, start)
        offsets.append(cursor + len(prefix))
        line = prefix + text
        lines.append(line)
        cursor += len(line) + 1  # the joining "\n"
    return "\n".join(lines), offsets
