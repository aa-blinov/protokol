"""The participant count the person may give.

Empty means the clustering decides, as before. A count keeps the same merges, then folds the
smallest voice into its nearest neighbour until that many remain; it never invents a speaker
the turns do not hold. The API accepts one to ten; the cache keeps the two kinds of answer apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analysis_cache  # noqa: E402
import main  # noqa: E402
from diarization import cluster_embeddings  # noqa: E402


def _three_speakers(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centres = np.eye(4)[:3]
    return np.vstack([centre + 0.02 * rng.standard_normal((6, 4)) for centre in centres])


@pytest.mark.parametrize("named", [2, 3])
def test_a_named_count_is_the_count_that_comes_out(named):
    # A threshold this high would split the groups apart on its own; the named count wins.
    labels = cluster_embeddings(_three_speakers(7), threshold=0.99, speakers=named)
    assert len(set(labels)) == named


def test_a_named_count_cannot_invent_speakers_the_turns_do_not_hold():
    labels = cluster_embeddings(np.eye(2), speakers=5)
    assert len(set(labels)) == 2


def test_empty_count_keeps_the_automatic_clustering():
    embeddings = _three_speakers(7)
    assert cluster_embeddings(embeddings, threshold=0.99) == cluster_embeddings(embeddings, threshold=0.99, speakers=None)


def test_a_named_count_does_not_join_two_real_speakers_to_reach_it():
    # Two speakers sit 0.4 apart, below the threshold, so they stay two; the stray turn that
    # resembles nobody is the one that should move. Merging to the count without the threshold
    # joined the two speakers instead and kept the stray as a speaker of its own.
    rng = np.random.default_rng(3)
    centres = np.zeros((4, 8))
    centres[0, 0] = 1.0
    centres[1] = [0.4, np.sqrt(1 - 0.4**2), 0, 0, 0, 0, 0, 0]
    centres[2, 2] = 1.0
    centres[3, 3] = 1.0
    stray = np.array([1, -1, 1, -1, 1, -1, 1, -1]) / np.sqrt(8)
    turns = [centre + 0.02 * rng.standard_normal((6, 8)) for centre in centres]
    embeddings = np.vstack([*turns, stray])
    labels = cluster_embeddings(embeddings, speakers=4, seconds=[2.0] * 24 + [0.5])
    speakers = [labels[i * 6 : (i + 1) * 6] for i in range(4)]
    assert all(len(set(group)) == 1 for group in speakers)
    assert len({group[0] for group in speakers}) == 4
    assert len(set(labels)) == 4


def test_a_recording_analysed_with_a_count_is_cached_apart():
    audio = b"same recording"
    automatic = analysis_cache.key_for(audio, ".wav")
    assert analysis_cache.key_for(audio, ".wav", 4) != automatic
    assert analysis_cache.key_for(audio, ".wav", 4) != analysis_cache.key_for(audio, ".wav", 3)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STTSHKA_ENV_FILE", str(tmp_path / "settings.env"))
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.mark.parametrize("value", ["0", "11"])
def test_the_api_refuses_a_count_outside_one_to_ten(client, value):
    response = client.post(
        "/api/analyse", files={"file": ("call.wav", b"RIFF", "audio/wav")}, data={"speakers": value}
    )
    assert response.status_code == 400


def test_the_api_refuses_a_count_that_is_not_a_number(client):
    response = client.post(
        "/api/analyse", files={"file": ("call.wav", b"RIFF", "audio/wav")}, data={"speakers": "many"}
    )
    assert response.status_code == 422
