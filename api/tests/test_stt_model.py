"""The recognition model and its chunking: values measured on real audio, kept from drifting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stt  # noqa: E402


def test_model_is_the_e2e_rnnt_head():
    # The e2e variant normalises digits, which the PII model needs. On 300 FLEURS
    # clips with audio scaled to [-1, 1]: RNN-T 3.84% word errors, CTC 4.09%. On a
    # labelled dialogue at 20 s chunks: RNN-T 4.00%, CTC 4.35%.
    assert stt.MODEL_NAME == "gigaam-v3-e2e-rnnt"


def test_chunks_stay_under_the_rnnt_length_limit():
    # The model card limits RNN-T to about 25 s; longer chunks lose words.
    assert 0 < stt.SEGMENT_MAX_SECONDS <= 25
