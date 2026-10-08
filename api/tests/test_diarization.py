"""Checks for diarization's pure parts: turn merging and clustering.

The model-dependent path (segmentation + embeddings) is exercised end to end
elsewhere; these pin the logic that decides where turns begin and which turns
share a speaker, which is easy to get subtly wrong without loading a model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diarization import Turn, cluster_embeddings, merge_turns  # noqa: E402


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


def test_cluster_embeddings_separates_two_groups():
    embeddings = np.array(
        [[1.0, 0.0, 0.0], [0.98, 0.02, 0.0], [0.97, 0.03, 0.0], [0.0, 1.0, 0.0], [0.02, 0.98, 0.0]]
    )
    labels = cluster_embeddings(embeddings, threshold=0.8)
    assert labels[:3] == [labels[0]] * 3
    assert labels[3:] == [labels[3]] * 2
    assert labels[0] != labels[3]


def test_cluster_embeddings_keeps_one_speaker_together():
    embeddings = np.array([[1.0, 0.0], [0.99, 0.01], [0.98, 0.02]])
    assert len(set(cluster_embeddings(embeddings, threshold=0.8))) == 1


def test_cluster_embeddings_empty():
    assert cluster_embeddings(np.zeros((0, 3))) == []
