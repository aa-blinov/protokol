"""Checks for the audio decoder.

This is the piece that used to shell out to a system `ffmpeg`; it now decodes
in-process with PyAV so the packaged app needs no external binary. It is easy to
break silently (a wrong sample rate or scale still yields *some* transcript), so
it keeps its own tests.

No fixtures on disk: WAVs are generated with the stdlib, mp3/m4a with PyAV's own
encoders — skipping those two when the encoder is unavailable.
"""

from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stt import SEGMENT_MAX_SECONDS, TARGET_SAMPLE_RATE, Stt  # noqa: E402


def make_wav_bytes(*, seconds: float = 0.5, rate: int = 16000, channels: int = 1) -> bytes:
    """A plain sine tone as a PCM16 WAV, built with stdlib only."""
    import io

    frames = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        samples = bytearray()
        for i in range(frames):
            value = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            for _ in range(channels):
                samples += struct.pack("<h", value)
        wav.writeframes(bytes(samples))
    return buf.getvalue()


def test_decodes_wav_to_16k_mono():
    audio = make_wav_bytes(seconds=0.5, rate=16000)
    samples = Stt._decode(audio)
    assert samples.dtype.kind == "i"
    assert len(samples) == int(0.5 * TARGET_SAMPLE_RATE)


def test_resamples_a_stereo_44k1_input_to_target_rate():
    # The real user files are rarely 16 kHz mono; this is the path that would
    # silently produce a wrong duration if the resampler were misconfigured.
    audio = make_wav_bytes(seconds=1.0, rate=44100, channels=2)
    samples = Stt._decode(audio)
    assert len(samples) == TARGET_SAMPLE_RATE  # one second stays one second


def test_writes_a_wav_that_reads_back_the_same_length():
    import tempfile

    samples = Stt._decode(make_wav_bytes(seconds=0.25))
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "out.wav"
        Stt._write_wav(samples, target)
        with wave.open(str(target), "rb") as wav:
            assert wav.getframerate() == TARGET_SAMPLE_RATE
            assert wav.getnchannels() == 1
            assert wav.getnframes() == len(samples)


def test_garbage_is_a_value_error_not_a_crash():
    with pytest.raises(ValueError, match="Cannot decode audio"):
        Stt._decode(b"this is definitely not audio" * 100)


def test_empty_input_is_a_value_error():
    with pytest.raises(ValueError, match="Cannot decode audio"):
        Stt._decode(b"")


def _encode_with_av(container: str, codec: str) -> bytes | None:
    """Re-encode the sine into another container. None if this build lacks it."""
    import io

    import av
    import numpy as np

    source = Stt._decode(make_wav_bytes(seconds=0.5))
    buf = io.BytesIO()
    try:
        with av.open(buf, mode="w", format=container) as out:
            stream = out.add_stream(codec, rate=TARGET_SAMPLE_RATE)
            frame = av.AudioFrame.from_ndarray(
                source.astype(np.int16).reshape(1, -1), format="s16", layout="mono"
            )
            frame.rate = TARGET_SAMPLE_RATE
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
    except Exception:  # noqa: BLE001 - encoder simply absent in some builds
        return None
    return buf.getvalue()


@pytest.mark.parametrize("container,codec", [("mp3", "libmp3lame"), ("mp4", "aac")])
def test_decodes_other_containers(container, codec):
    audio = _encode_with_av(container, codec)
    if audio is None:
        pytest.skip(f"no {codec} encoder in this PyAV build")
    samples = Stt._decode(audio)
    # Lossy codecs shift length by a frame or two; assert the second, not frames.
    assert abs(len(samples) / TARGET_SAMPLE_RATE - 0.5) < 0.1


def test_split_long_leaves_audio_that_fits_untouched():
    samples = np.full(int(30 * TARGET_SAMPLE_RATE), 5000, dtype=np.int16)
    chunks = Stt._split_long(samples)
    assert len(chunks) == 1
    assert chunks[0] is samples


def test_split_long_covers_every_sample_and_respects_the_cap():
    # 5 minutes -> at least ceil(300 / 120) = 3 chunks.
    total = int(300 * TARGET_SAMPLE_RATE)
    samples = np.full(total, 5000, dtype=np.int16)
    chunks = Stt._split_long(samples)
    assert len(chunks) >= 3
    assert sum(len(chunk) for chunk in chunks) == total
    assert all(len(chunk) <= int(SEGMENT_MAX_SECONDS * TARGET_SAMPLE_RATE) + 1 for chunk in chunks)


def test_split_long_cuts_on_the_quietest_frame_near_the_limit():
    # A tone with one clear silence inside the search window of the first
    # chunk (the last 40% before 120 s). The cut must land in that silence,
    # not at a fixed 120 s grid line.
    total = int(300 * TARGET_SAMPLE_RATE)
    samples = np.full(total, 5000, dtype=np.int16)
    silence_start, silence_end = 100 * TARGET_SAMPLE_RATE, 101 * TARGET_SAMPLE_RATE
    samples[silence_start:silence_end] = 0

    chunks = Stt._split_long(samples)
    assert silence_start <= len(chunks[0]) <= silence_end + 1
