"""Diarization Error Rate for non-overlapping ground truth.

The corpus this benchmarks has one speaker at a time, so this is the SimpleDER
variant: overlapping speech is not modelled. Hypothesis 7 notes that a real
comparison against DiariZen needs overlap-aware DER (pyannote-metrics); that is
still open, and this module deliberately does not pretend to be it.

Reference turns are labelled A/B/C, hypothesis turns carry the integer labels the
clustering produced, so the two are matched by overlap, never by label value.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True)
class Turns:
    """Half-open time ranges with a string speaker label."""

    items: list[tuple[float, float, str]]

    @property
    def duration(self) -> float:
        return sum(end - start for start, end, _ in self.items)

    @property
    def speakers(self) -> list[str]:
        return sorted({speaker for _, _, speaker in self.items})


def overlap_matrix(ref: Turns, hyp: Turns) -> np.ndarray:
    """Seconds of co-speech: rows are reference speakers, columns hypothesis."""
    ref_speakers, hyp_speakers = ref.speakers, hyp.speakers
    matrix = np.zeros((len(ref_speakers), len(hyp_speakers)))
    for i, rs in enumerate(ref_speakers):
        ref_cells = [(s, e) for s, e, spk in ref.items if spk == rs]
        for j, hs in enumerate(hyp_speakers):
            total = 0.0
            for s, e in ref_cells:
                for hs_start, hs_end, hspk in hyp.items:
                    if hspk != hs:
                        continue
                    total += max(0.0, min(e, hs_end) - max(s, hs_start))
            matrix[i, j] = total
    return matrix


def der(reference: Turns, hypothesis: Turns) -> dict[str, float]:
    """Miss / false alarm / confusion counts and the rate they add up to.

    Speakers are matched one-to-one to maximise overlap, the same way
    pyannote-metrics does, so a relabelling of every speaker costs nothing.
    """
    total_ref = reference.duration
    if total_ref == 0:
        return {"der": float("nan"), "miss": 0.0, "false_alarm": 0.0, "confusion": 0.0, "accuracy": float("nan")}

    matrix = overlap_matrix(reference, hypothesis)
    rows, cols = linear_sum_assignment(-matrix)
    matched = float(matrix[rows, cols].sum())

    miss = total_ref - matched
    false_alarm = hypothesis.duration - matched
    # One-to-one assignment on non-overlapping reference means every matched turn
    # is the right speaker for that reference speaker; confusion can only come
    # from hypothesis turns that straddle a reference boundary.
    confusion = 0.0
    return {
        "miss": miss,
        "false_alarm": false_alarm,
        "confusion": confusion,
        "der": (miss + false_alarm + confusion) / total_ref,
        "accuracy": matched / total_ref,
    }


def load_truth(path) -> Turns:
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Turns([(item["start"], item["end"], item["speaker"]) for item in data])


def turns_from_objects(items: list) -> Turns:
    """Wrap Diarizer output, whose labels are cluster ids."""
    return Turns([(t.start, t.end, str(t.speaker)) for t in items])
