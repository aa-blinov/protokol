"""Checks for diarization's pure parts.

Sortformer itself is a vendored ONNX model plus streaming state (exercised end
to end elsewhere); these pin the adapter around it — turn merging/splitting for
the ASR, and that a missing model fails loudly instead of silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diarization import Diarizer, Turn, merge_turns  # noqa: E402


def test_merge_turns_joins_same_speaker_across_a_short_gap():
    turns = [Turn(0.0, 3.0, 0), Turn(3.2, 6.0, 0)]
    assert merge_turns(turns) == [Turn(0.0, 6.0, 0)]


def test_merge_turns_keeps_a_real_pause():
    turns = [Turn(0.0, 3.0, 0), Turn(5.0, 8.0, 0)]
    assert merge_turns(turns) == [Turn(0.0, 3.0, 0), Turn(5.0, 8.0, 0)]


def test_merge_turns_never_joins_different_speakers():
    turns = [Turn(0.0, 3.0, 0), Turn(3.1, 6.0, 1)]
    assert merge_turns(turns) == [Turn(0.0, 3.0, 0), Turn(3.1, 6.0, 1)]


def test_merge_turns_splits_a_long_turn_for_the_asr():
    merged = merge_turns([Turn(0.0, 70.0, 0)], max_seconds=30.0)
    assert [(t.start, t.end) for t in merged] == [(0.0, 30.0), (30.0, 60.0), (60.0, 70.0)]
    assert all(t.speaker == 0 for t in merged)


def test_diarizer_without_a_model_fails_loudly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Diarizer(tmp_path / "absent.onnx")
