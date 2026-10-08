"""Speaker diarization on CPU: who spoke when.

CPU-only and ONNX, like the rest of the pipeline — no torch, no GPU:

* ``onnx-community/pyannote-segmentation-3.0`` marks where the speaker changes
  (its powerset head emits no-speech / speaker-1..3 / two-speaker frames);
* 3D-Speaker ``ERes2Net`` turns each speech turn into a voice embedding;
* single-linkage clustering over cosine similarity groups the turns into the
  recording's speakers.

The segmentation model's own speaker indices are local — up to three per 10 s
window, re-numbered window to window — so they only say *where* a turn begins
and ends. The embeddings decide *who* it is across the whole recording, which is
what makes the labels stable for a meeting longer than one window.

Embeddings need the same 80-dim Kaldi fbank the model was trained on; that
preprocessor is reused from ``onnx_asr`` rather than re-derived, so the features
match the ASR side of the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import numpy as np
import onnx_asr
import onnxruntime as ort
from onnx_asr.preprocessors.numpy_preprocessor import KaldiPreprocessorNumpy

import config

SAMPLE_RATE = 16_000

# pyannote segmentation frame geometry, mirroring the ONNX wrapper.
_RECEPTIVE_FIELD = 991
_STRIDE = 270
_OFFSET = 135
_WINDOW_SECONDS = 10.0
_OVERLAP_SECONDS = 5.0

# A turn shorter than this carries too little voice to embed reliably.
_MIN_EMBED_SECONDS = 0.4
# no-speech probability at or above this is silence.
_SPEECH_THRESHOLD = 0.5
# Average cosine similarity below which two clusters are different speakers.
_CLUSTER_THRESHOLD = 0.8
# A cluster this small (in turns) is noise, not a speaker; fold it into the
# nearest one instead of inventing a speaker for it.
_MIN_CLUSTER_TURNS = 2


@dataclass(frozen=True)
class Turn:
    """One speaker's continuous speech interval, ``end`` exclusive, in seconds."""

    start: float
    end: float
    speaker: int


def merge_turns(turns: list[Turn], gap: float = 0.5, max_seconds: float = 30.0) -> list[Turn]:
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


def cluster_embeddings(embeddings: np.ndarray, threshold: float = _CLUSTER_THRESHOLD) -> list[int]:
    """Agglomerative average-linkage clustering over cosine similarity.

    Merges the two closest clusters while their average similarity is at least
    ``threshold``; the number of speakers falls out of the data. Tiny clusters
    are folded into their most similar neighbour so a stray turn does not become
    a speaker of its own.
    """
    count = len(embeddings)
    if count == 0:
        return []
    normalized = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)
    similarity = normalized @ normalized.T
    clusters: list[list[int]] = [[i] for i in range(count)]

    def average(a: list[int], b: list[int]) -> float:
        return float(similarity[np.ix_(a, b)].mean())

    while len(clusters) > 1:
        best_pair = (-1, -1)
        best_score = -2.0
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                score = average(clusters[i], clusters[j])
                if score > best_score:
                    best_score, best_pair = score, (i, j)
        if best_score < threshold:
            break
        i, j = best_pair
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]

    # Fold noise clusters (< _MIN_CLUSTER_TURNS turns) into their best neighbour.
    while len(clusters) > 1:
        small = [k for k, c in enumerate(clusters) if len(c) < _MIN_CLUSTER_TURNS]
        if not small:
            break
        k = small[0]
        others = [m for m in range(len(clusters)) if m != k]
        target = max(others, key=lambda m: average(clusters[k], clusters[m]))
        clusters[target] = clusters[target] + clusters[k]
        del clusters[k]

    labels = [0] * count
    for speaker, members in enumerate(clusters):
        for index in members:
            labels[index] = speaker
    return labels


class Diarizer:
    """Recognize speaker turns. Construct once and reuse; ``diarize`` is thread-safe."""

    def __init__(
        self,
        segmentation_dir: str | Path,
        embedding_path: str | Path,
        threads: int = 4,
        cluster_threshold: float = _CLUSTER_THRESHOLD,
    ):
        self.segmentation_dir = Path(segmentation_dir)
        self.embedding_path = Path(embedding_path)
        if not (self.segmentation_dir / "config.json").is_file() or not (
            self.segmentation_dir / "model.onnx"
        ).is_file():
            raise FileNotFoundError(f"Missing diarization segmentation model in {self.segmentation_dir}")
        if not self.embedding_path.is_file():
            raise FileNotFoundError(f"Missing diarization embedding model: {self.embedding_path}")

        self.cluster_threshold = cluster_threshold
        providers = config.ort_providers()
        # pyannote segmentation: loaded through onnx_asr so its powerset decoding
        # (and the window re-ordering that keeps local speaker order stable) is
        # the same code the library ships and tests.
        self._vad = onnx_asr.load_vad(
            "onnx-community/pyannote-segmentation-3.0", path=self.segmentation_dir, providers=providers
        )
        self._fbank = KaldiPreprocessorNumpy("wespeaker")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self._embedding = ort.InferenceSession(str(self.embedding_path), options, providers=providers)
        self._lock = Lock()

    def _frames(self, samples: np.ndarray) -> list[tuple[int, int]]:
        """Per-frame (sample position, local speaker) — ``-1`` for silence."""
        waveform = samples[None, :].astype(np.float32)
        window = int(_WINDOW_SECONDS * SAMPLE_RATE)
        overlap = int(_OVERLAP_SECONDS * SAMPLE_RATE)
        encoded = self._vad._encode(waveform, window, overlap)
        frames: list[tuple[int, int]] = []
        for begin, block in self._vad._decode((batch[0] for batch in encoded), window, overlap):
            for index, row in enumerate(block):
                position = begin + (index - 1) * _STRIDE + _RECEPTIVE_FIELD + _OFFSET
                speaker = -1 if row[0] >= _SPEECH_THRESHOLD else int(np.argmax(row[1:4]))
                frames.append((position, speaker))
        return frames

    def _turns(self, samples: np.ndarray) -> list[Turn]:
        turns: list[Turn] = []
        for position, speaker in self._frames(samples):
            if turns and turns[-1].speaker == speaker:
                turns[-1] = Turn(turns[-1].start, position / SAMPLE_RATE, speaker)
            else:
                turns.append(Turn(position / SAMPLE_RATE, position / SAMPLE_RATE, speaker))
        return [t for t in turns if t.speaker >= 0 and t.end > t.start]

    def _embed(self, chunk: np.ndarray) -> np.ndarray:
        waveform = chunk[None, :].astype(np.float32)
        features, _ = self._fbank(waveform, np.array([waveform.shape[1]], dtype=np.int64))
        return self._embedding.run(["embedding"], {"x": features})[0][0]

    def diarize(self, samples: np.ndarray) -> list[Turn]:
        """Return the speaker turns of a 16 kHz mono recording, or ``[]`` when
        there is no speech."""
        if len(samples) < _RECEPTIVE_FIELD:
            return []
        with self._lock:
            turns = self._turns(samples)
            long_enough = [t for t in turns if (t.end - t.start) >= _MIN_EMBED_SECONDS]
            if not long_enough:
                return []
            embeddings = np.asarray(
                [self._embed(samples[int(t.start * SAMPLE_RATE) : int(t.end * SAMPLE_RATE)]) for t in long_enough]
            )
            labels = cluster_embeddings(embeddings, self.cluster_threshold)
            labelled = [Turn(t.start, t.end, label) for t, label in zip(long_enough, labels)]
            # Short turns borrow the speaker of the nearest labelled turn in time.
            for turn in turns:
                if (turn.end - turn.start) >= _MIN_EMBED_SECONDS:
                    continue
                if not labelled:
                    continue
                nearest = min(labelled, key=lambda l: min(abs(l.start - turn.end), abs(turn.start - l.end)))
                labelled.append(Turn(turn.start, turn.end, nearest.speaker))
        return merge_turns(sorted(labelled, key=lambda t: t.start))
