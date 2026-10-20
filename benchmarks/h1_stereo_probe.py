"""H1: does the decoder really drop every audio stream but the first?

HYPOTHESES.md leaves one line open: "в файле с несколькими аудиодорожками берётся
только первая". This builds a container with two *separate* audio streams (not two
channels of one stereo stream) and decodes it through the real Stt._decode.

Run: .venv/bin/python h1_stereo_probe.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from stt import Stt, TARGET_SAMPLE_RATE  # noqa: E402

RATE = TARGET_SAMPLE_RATE
SECONDS = 1.0


def tone(freq: float, seconds: float = SECONDS, rate: int = RATE) -> np.ndarray:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * 8000).astype(np.int16)


def two_channel_file() -> bytes:
    """One stereo stream: left 0.5, right silent. Peak must land at half of left."""
    left = (tone(440).astype(np.int32) * 1) // 2
    right = np.zeros_like(left)
    interleaved = np.empty(left.size * 2, dtype=np.int16)
    interleaved[0::2] = left
    interleaved[1::2] = right
    buf = io.BytesIO()
    with av.open(buf, "w", format="wav") as out:
        stream = out.add_stream("pcm_s16le", rate=RATE, layout="stereo")
        frame = av.AudioFrame.from_ndarray(
            interleaved.reshape(1, -1).astype(np.int16), format="s16", layout="stereo"
        )
        frame.sample_rate = RATE
        frame.pts = 0
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def two_stream_file() -> bytes:
    """Two independent mono audio streams in one container.

    Stream 0 is a 440 Hz tone; stream 1 is a 900 Hz tone. If only the first is
    decoded, the output must contain energy at 440 Hz and essentially none at 900.

    Both streams have to be registered before any packet is encoded: adding the
    second stream mid-file trips PyAV's Matroska time rebasing. AAC rather than
    PCM because a two-track PCM Matroska is not something recorders produce.
    """
    buf = io.BytesIO()
    with av.open(buf, "w", format="matroska") as out:
        streams = [out.add_stream("aac", rate=RATE, layout="mono") for _ in (440.0, 900.0)]
        for stream, freq in zip(streams, (440.0, 900.0)):
            frame = av.AudioFrame.from_ndarray(
                tone(freq).reshape(1, -1).copy(), format="s16", layout="mono"
            )
            frame.sample_rate = RATE
            frame.pts = 0
            for packet in stream.encode(frame):
                out.mux(packet)
        for stream in streams:
            for packet in stream.encode(None):
                out.mux(packet)
    return buf.getvalue()


def spectrum_peak(data: bytes) -> float:
    samples = Stt._decode(data).astype(np.float64)
    if samples.size == 0:
        return 0.0
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(samples.size)))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / RATE)
    spectrum[(freqs < 100) | (freqs > 4000)] = 0  # ignore DC and noise floor
    return float(freqs[int(np.argmax(spectrum))])


def main() -> int:
    print(f"частота дискретизации: {RATE}")
    print()

    stereo = two_channel_file()
    samples = Stt._decode(stereo)
    peak = int(np.max(np.abs(samples.astype(np.int32))))
    left_peak = int(np.max(np.abs(tone(440).astype(np.int32)))) // 2
    expected = left_peak // 2
    print("1) stereo-файл, левый канал 0.5 амплитуды, правый тишина")
    print(f"   пик левого канала: {left_peak}")
    print(f"   пик на выходе: {peak}")
    print(f"   ожидание при усреднении (половина левого): {expected}")
    print(f"   каналы усреднены: {peak == expected}")

    blob = two_stream_file()
    with av.open(io.BytesIO(blob)) as container:
        count = len(container.streams.audio)
    print()
    print("2) файл с двумя отдельными аудиопотоками (0: 440 Гц, 1: 900 Гц)")
    print(f"   аудиопотоков в контейнере: {count}")
    peak_freq = spectrum_peak(blob)
    print(f"   пик спектра после декодирования: {peak_freq:.1f} Гц")
    print(f"   взят только первый поток: {abs(peak_freq - 440.0) < 5.0 and abs(peak_freq - 900.0) > 100.0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
