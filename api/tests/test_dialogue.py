"""Checks for the meeting transcript format and the long-meeting split.

The model must see who spoke and when, so the transcript it gets is labelled —
and it is the labelled text that is masked, so these pure helpers are what keeps
speaker structure and privacy from fighting each other.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialogue import build_dialogue, format_clock  # noqa: E402
from llm import (  # noqa: E402
    DEFAULT_MODEL,
    LlmResult,
    MEETING_MAP_CHARS,
    SYSTEM_PROMPT,
    OpenRouterClient,
    SYSTEM_PROMPT,
    split_masked_text,
)


def test_format_clock():
    assert format_clock(0) == "0:00"
    assert format_clock(3.5) == "0:03"
    assert format_clock(75) == "1:15"
    assert format_clock(3600) == "60:00"


def test_build_dialogue_labels_each_turn_and_keeps_offsets():
    text, offsets = build_dialogue([(0, 0.0, "Привет, меня зовут Иван."), (1, 3.5, "Слушаю.")])
    assert text == "Спикер 1 [0:00]: Привет, меня зовут Иван.\nСпикер 2 [0:03]: Слушаю."
    # Each offset points at that turn's own text, past the label.
    assert text[offsets[0] : offsets[0] + 24] == "Привет, меня зовут Иван."
    assert text[offsets[1] : offsets[1] + 7] == "Слушаю."


def test_build_dialogue_is_empty_for_no_turns():
    assert build_dialogue([]) == ("", [])


def test_split_masked_text_keeps_every_line_and_respects_the_limit():
    lines = [f"Спикер 1 [0:{i:02d}]: короткая реплика номер {i}" for i in range(60)]
    text = "\n".join(lines)
    chunks = split_masked_text(text, max_chars=200)
    assert all(len(chunk) <= 200 for chunk in chunks)
    # No line is lost or split: rejoining the chunks restores every line.
    assert [line for chunk in chunks for line in chunk.splitlines()] == lines
    assert len(chunks) > 1


def test_split_masked_text_returns_one_chunk_when_short():
    assert split_masked_text("одна короткая строка", max_chars=200) == ["одна короткая строка"]


def _client_with_fake_complete() -> tuple[OpenRouterClient, list[tuple[str, str]]]:
    client = OpenRouterClient("test-key")
    calls: list[tuple[str, str]] = []

    def fake(masked_text: str, model: str = DEFAULT_MODEL, prompt: str | None = None, system: str = SYSTEM_PROMPT):
        calls.append((system, masked_text))
        return LlmResult(reply=f"part-{len(masked_text)}", model=model, tokens_in=None, tokens_out=None)

    client.complete = fake  # type: ignore[method-assign]
    return client, calls


def test_short_meeting_is_one_protocol_call():
    client, calls = _client_with_fake_complete()
    client.complete_meeting("Спикер 1 [0:00]: короткая реплика")
    assert len(calls) == 1
    assert calls[0][0] == SYSTEM_PROMPT


def test_long_meeting_is_summarised_in_parts_then_composed():
    client, calls = _client_with_fake_complete()
    long_text = "\n".join(f"Спикер 1 [0:{i % 60:02d}]: " + "текст " * 30 for i in range(200))
    assert len(long_text) > MEETING_MAP_CHARS
    client.complete_meeting(long_text)
    # One call per part, then a final call that composes the protocol from them.
    assert len(calls) == len(split_masked_text(long_text)) + 1
    assert calls[-1][0] == SYSTEM_PROMPT
    assert all(call[0] != SYSTEM_PROMPT for call in calls[:-1])

