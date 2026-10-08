"""Format a diarized transcript for the model.

A meeting is not a wall of text: who spoke and when is part of what the model
must reason about. So the transcript the model sees is built as speaker turns —
``Спикер 2 [12:34]: …`` — and it is this labelled text that gets masked, so the
privacy rule is unchanged: only masked text ever leaves for the LLM.
"""

from __future__ import annotations

SPEAKER_LABEL = "Спикер"


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
