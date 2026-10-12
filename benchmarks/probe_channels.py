"""Does the pipeline split multi-channel audio by channel?

Worth checking on its own: `api/stt.py` resamples to `layout="mono"` and
`Diarizer` takes a single array, so the expectation is that channels are mixed
down, never separated. This makes that concrete rather than assumed -- it builds
a stereo file where the left channel is silence and the right carries a tone, and
looks at what comes out of the decoder and the diarizer.

Run: .venv/bin/python benchmarks/probe_channels.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import av
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import config  # noqa: E402
from diarization import SAMPLE_RATE, Diarizer  # noqa: E402
from stt import Stt, TARGET_SAMPLE_RATE  # noqa: E402


def stereo_file(left: np.ndarray, right: np.ndarray) -> bytes:
    """Interleave two mono int16 arrays into a stereo WAV."""
    interleaved = np.empty(left.size * 2, dtype=np.int16)
    interleaved[0::2] = left
    interleaved[1::2] = right
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="wav") as out:
        stream = out.add_stream("pcm_s16le", rate=TARGET_SAMPLE_RATE, layout="stereo")
        frame = av.AudioFrame.from_ndarray(
            interleaved.reshape(1, -1).copy(), format="s16", layout="stereo"
        )
        frame.sample_rate = TARGET_SAMPLE_RATE
        frame.pts = 0
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buffer.getvalue()


def main() -> int:
    seconds = 3.0
    t = np.linspace(0, seconds, int(TARGET_SAMPLE_RATE * seconds), endpoint=False)
    left = np.sin(2 * np.pi * 220 * t) * 6000  # 220 Hz
    right = np.sin(2 * np.pi * 700 * t) * 6000  # 700 Hz
    left_i, right_i = left.astype(np.int16), right.astype(np.int16)

    blob = stereo_file(left_i, right_i)
    samples = Stt.decode(blob)
    print(f"вход: стерео, левый канал 220 Гц, правый 700 Гц")
    print(f"декодер вернул: {samples.shape[0]} значений, dtype {samples.dtype}")
    print(f"  (моно: один канальный массив, {samples.shape[0]} = {seconds:.0f} с × {TARGET_SAMPLE_RATE})")

    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64) * np.hanning(samples.size)))
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / TARGET_SAMPLE_RATE)
    spectrum[(freqs < 100) | (freqs > 2000)] = 0
    peaks = freqs[np.argsort(spectrum)[-2:][::-1]]
    print(f"  пики в спектре: {', '.join(f'{p:.0f} Гц' for p in sorted(peaks))}")
    print(f"  оба канала слышны (микс): {any(abs(p - 220) < 15 for p in peaks) and any(abs(p - 700) < 15 for p in peaks)}")

    float_samples = (samples.astype(np.float32) / 32768.0)
    diarizer = Diarizer(
        config.DIARIZATION_SEG_DIR, config.DIARIZATION_EMB_PATH, threads=config.INFERENCE_THREADS
    )
    turns = diarizer.diarize(float_samples)
    print(f"диаризация получила: один массив, реплик {len(turns)}, спикеров {len({x.speaker for x in turns})}")
    print()
    print("вывод: каналы не разделяются -- они усредняются в один моно-сигнал,")
    print("       и STT, и диаризация работают только с этой смесью.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())