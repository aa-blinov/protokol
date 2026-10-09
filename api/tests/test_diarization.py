"""Checks for diarization's pure parts: turn merging and clustering.

The model-dependent path (segmentation + embeddings) is exercised end to end
elsewhere; these pin the logic that decides where turns begin and which turns
share a speaker, which is easy to get subtly wrong without loading a model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diarization import (  # noqa: E402
    Diarizer,
    Turn,
    _borrow_short_turns,
    _cmn,
    cluster_embeddings,
    fold_small_clusters,
    merge_turns,
)


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


def _unit(angle: float) -> list[float]:
    return [float(np.cos(angle)), float(np.sin(angle))]


def test_fold_small_clusters_absorbs_a_sliver_into_its_nearest_neighbour():
    # A and B are real speakers (10 s each); C is a 0.2 s fragment closest to A.
    embeddings = np.array([_unit(0.0), _unit(0.1), _unit(1.2), _unit(1.3), _unit(0.05), _unit(0.15)])
    labels = [0, 0, 1, 1, 2, 2]
    weights = [10.0, 10.0, 10.0, 10.0, 0.1, 0.1]
    folded = fold_small_clusters(embeddings, labels, weights, min_share=0.03)
    assert len(set(folded)) == 2
    assert folded[4] == folded[0]  # the fragment joined the cluster it resembles
    assert folded[2] != folded[0]


def test_fold_small_clusters_leaves_real_speakers_alone():
    embeddings = np.array([_unit(0.0), _unit(0.1), _unit(1.2), _unit(1.3)])
    labels = [0, 0, 1, 1]
    assert fold_small_clusters(embeddings, labels, [8.0, 8.0, 8.0, 8.0], min_share=0.02) == labels


def test_fold_small_clusters_keeps_a_quiet_speaker_on_a_long_call():
    # A 110 s speaker out of 2 h is 1.5% of the speech: under the share gate,
    # but far above a fragment's few seconds, so it must survive.
    embeddings = np.array([_unit(0.0), _unit(0.1), _unit(1.2), _unit(1.3)])
    labels = [0, 0, 1, 1]
    weights = [3600.0, 3600.0, 55.0, 55.0]
    assert fold_small_clusters(embeddings, labels, weights, min_share=0.02) == labels


def test_diarizer_without_a_model_fails_loudly(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        Diarizer(tmp_path / "seg", tmp_path / "emb.onnx")


def test_cmn_centres_each_bin_over_time():
    features = np.random.default_rng(0).normal(size=(1, 50, 80)) + 5.0
    assert np.allclose(_cmn(features).mean(axis=1), 0.0)


@pytest.mark.parametrize("shape", [(50, 80), (1, 80, 50)])
def test_cmn_rejects_a_fbank_shape_it_would_silently_mis_normalise(shape):
    with pytest.raises(ValueError):
        _cmn(np.zeros(shape))


def test_short_turns_borrow_only_from_long_labelled_turns():
    anchors = [Turn(0.0, 10.0, 0), Turn(10.5, 30.0, 1)]
    # The first short turn sits by speaker 0. The second is closer to it than to
    # the anchors, but must still take speaker 1 from the nearer anchor, not 0 via
    # the first short turn.
    turns = [Turn(10.1, 10.3, 9), Turn(10.32, 10.38, 9)]
    borrowed = _borrow_short_turns(turns, anchors)
    assert [t.speaker for t in borrowed] == [0, 1]
