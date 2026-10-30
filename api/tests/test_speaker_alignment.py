"""Speaker order between segmentation windows is matched before the windows are averaged.

The model numbers the speakers of each window arbitrarily. Averaging the shared frames without
matching them mixes two people at every seam, so one of them can vanish for a few seconds.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from diarization import _SPEAKER_ORDERS, _marginals, _stitch  # noqa: E402

FRAMES = 20
OVERLAP = 8
STEP = FRAMES - OVERLAP


def _labels(total: int) -> np.ndarray:
    """The speaker of each frame, changing every two frames so any shared run holds all three."""
    return (np.arange(total) // 2) % 3


def _windows(labels: np.ndarray, orders: list[list[int]]) -> list[np.ndarray]:
    """Each window as the model reports it: the same speakers, numbered in that window's order."""
    windows = []
    for number, order in enumerate(orders):
        chunk = labels[number * STEP : number * STEP + FRAMES]
        powerset = np.zeros((FRAMES, 7), dtype=np.float32)
        local = np.array([order.index(label) for label in chunk]) + 1
        powerset[np.arange(FRAMES), local] = 1.0
        windows.append(_marginals(powerset))
    return windows


def _speakers(pieces: list[np.ndarray]) -> np.ndarray:
    return np.argmax(np.concatenate(pieces)[:, 1:4], axis=1)


def test_matched_windows_give_back_each_speaker_as_it_was_heard():
    labels = _labels(5 * STEP + FRAMES)
    orders = [[0, 1, 2], [1, 2, 0], [2, 0, 1], [0, 2, 1], [1, 0, 2], [2, 1, 0]]
    assert np.array_equal(_speakers(_stitch(_windows(labels, orders), OVERLAP)), labels)


def test_averaging_without_matching_would_mix_speakers_at_the_seam():
    labels = _labels(STEP + FRAMES)
    first, second = _windows(labels, [[0, 1, 2], [1, 2, 0]])
    naive_overlap = (first[STEP:] + second[:OVERLAP]) / 2
    naive = np.concatenate([first[:STEP], naive_overlap, second[OVERLAP:]])
    assert not np.array_equal(np.argmax(naive[:, 1:4], axis=1), labels)


def test_a_single_window_is_kept_whole():
    window = _marginals(np.eye(7, dtype=np.float32)[np.arange(FRAMES) % 7])
    pieces = _stitch([window], OVERLAP)
    assert len(pieces) == 1
    assert np.array_equal(pieces[0], window)


def test_a_pair_of_speakers_counts_as_activity_for_both():
    powerset = np.zeros((1, 7), dtype=np.float32)
    powerset[0, 4] = 0.6  # speakers 1 and 2 talk together
    assert np.allclose(_marginals(powerset)[0], [0.0, 0.6, 0.6, 0.0])


def test_every_order_of_three_speakers_is_a_candidate():
    assert len(_SPEAKER_ORDERS) == 6
