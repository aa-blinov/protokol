"""Speaker diarization: who spoke when, via NVIDIA Sortformer (ONNX, CPU-only).

The pipeline used to segment speaker changes with pyannote, embed every turn
with a 3D-Speaker ERes2Net model and cluster those embeddings by cosine
similarity. On clean two- and three-speaker audio that worked, but on real
recordings (a phone call, in-the-wild VoxConverse) a fixed threshold picked the
wrong number of speakers — one voice fragmented into a dozen labels, or distinct
voices merged — and no post-hoc fix (folding small clusters, silhouette,
eigengap) was robust: tuning for one recording broke another.

Sortformer replaces that whole stack with a single end-to-end model: a streaming
transformer that predicts per-frame speaker activity for up to four speakers,
including overlapping speech, and needs no clustering threshold at all. It runs
on onnxruntime with no PyTorch/NeMo — see the vendored ``sortformer`` module.

This file is the adapter the pipeline talks to: it feeds the model 16 kHz mono
audio and converts its ``(start, end, speaker)`` segments into ``Turn`` objects,
then merges/splits them for the ASR. Speaker labels are ordered by first arrival
and capped at four.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np

from sortformer import Sortformer

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Turn:
    """One speaker's continuous speech interval, ``end`` exclusive, in seconds."""

    start: float
    end: float
    speaker: int


def merge_turns(turns: list[Turn], gap: float = 0.5, max_seconds: float = 120.0) -> list[Turn]:
    """Join adjacent turns of the same speaker across short gaps, and split any
    turn longer than ``max_seconds`` so the ASR never sees one long block."""
    merged: list[Turn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker and turn.start - merged[-1].end <= gap:
            previous = merged[-1]
            merged[-1] = Turn(previous.start, turn.end, turn.speaker)
        else:
            merged.append(turn)
    split: list[Turn] = []
    for turn in merged:
        start = turn.start
        while turn.end - start > max_seconds:
            split.append(Turn(start, start + max_seconds, turn.speaker))
            start += max_seconds
        split.append(Turn(start, turn.end, turn.speaker))
    return [t for t in split if t.end > t.start]


class Diarizer:
    """Recognize speaker turns with Sortformer. Construct once and reuse;
    ``diarize`` is thread-safe."""

    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Missing diarization model: {self.model_path}")
        # CPU is the only provider this app ships with; the model's streaming
        # state is mutable, so a single instance is guarded by a lock.
        self._model = Sortformer(str(self.model_path), provider="CPUExecutionProvider")
        self._lock = Lock()

    def diarize(self, samples: np.ndarray) -> list[Turn]:
        """Return the speaker turns of a 16 kHz mono recording, or ``[]`` when
        there is no speech."""
        if len(samples) == 0:
            return []
        # int16 samples -> the float [-1, 1] waveform the model expects.
        audio = (samples.astype(np.float32) / 32768.0).tolist()
        with self._lock:
            segments = self._model.diarize(audio, SAMPLE_RATE, 1)
        turns = [
            Turn(float(segment.start), float(segment.end), int(segment.speaker_id))
            for segment in segments
            if segment.end > segment.start
        ]
        return merge_turns(sorted(turns, key=lambda turn: turn.start))
