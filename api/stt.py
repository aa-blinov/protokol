"""Speech to text via GigaAM-v3 ONNX (``onnx-asr``).

Uses the ``e2e`` variant: unlike plain ``v3-ctc`` it adds punctuation *and*
normalises dictated digits ("восемь девятьсот..." -> "8 912..."), which is what
lets the PII model recognise phone, passport and INN numbers at all. With the
plain CTC model those numbers reach OpenRouter unmasked, so this choice is a
privacy requirement, not a quality preference.

Uploaded audio can be any container or codec, so it is decoded to 16 kHz mono
PCM with PyAV before inference — the model only accepts 16 kHz PCM. PyAV is used
instead of an external `ffmpeg` binary on purpose: its wheel embeds the FFmpeg
libraries, so the decoder ships inside the PyInstaller bundle. Calling a system
`ffmpeg` would break the app on any machine that has not installed one.

Decoded samples are written to a WAV and handed to ``recognize`` as a path, not
as an array: ``onnx_asr`` does not renormalise arrays, so passing samples would
mean reproducing its int16->float32 scaling exactly to avoid silently degrading
accuracy. Letting it read the WAV keeps that step in its hands.

Long audio is split first. GigaAM's ONNX graph is exported with a fixed
attention span: somewhere past ~200 s the encoder raises an ONNX broadcast
error instead of transcribing (measured: 180 s fine, 210 s fails), so a meeting
cannot be handed over in one call. Chunks are cut at the quietest frame near
the limit rather than on a fixed grid, so a cut rarely lands mid-word. The cap
stays well under the model limit to leave margin across quantizations.
"""

from __future__ import annotations

import io
import tempfile
import wave
from pathlib import Path

import av
import numpy as np
import onnx_asr
from av.error import FFmpegError

import config

MODEL_NAME = "gigaam-v3-e2e-ctc"
TARGET_SAMPLE_RATE = 16_000
MAX_AUDIO_SECONDS = 60 * 60  # one hour; a meeting, not a call centre

# The model's own ceiling is ~200 s (see the module docstring); 120 s keeps a
# wide margin and still gives each chunk plenty of context.
SEGMENT_MAX_SECONDS = 120.0
_FRAME_MS = 20
_HOP_MS = 10


class Stt:
    def __init__(self, model_dir: str | Path, threads: int = 4):
        self.model_dir = Path(model_dir)
        if not (self.model_dir / "config.json").is_file():
            raise FileNotFoundError(f"Missing model artifacts in {self.model_dir}")
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.model = onnx_asr.load_model(
            MODEL_NAME,
            path=self.model_dir,
            sess_options=options,
            providers=config.ort_providers(),
        )

    def transcribe(self, audio: bytes, suffix: str = ".wav") -> tuple[str, float]:
        """Return ``(text, duration_seconds)`` for raw audio bytes."""
        samples = self._decode(audio)
        duration = len(samples) / TARGET_SAMPLE_RATE
        if duration > MAX_AUDIO_SECONDS:
            raise ValueError(f"Audio is {duration:.0f}s, limit is {MAX_AUDIO_SECONDS}s")
        chunks = self._split_long(samples)
        texts: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for index, chunk in enumerate(chunks):
                wav_path = Path(tmp) / f"chunk{index}.wav"
                self._write_wav(chunk, wav_path)
                texts.append(self.model.recognize(str(wav_path)).strip())
        return " ".join(text for text in texts if text), duration

    @classmethod
    def _split_long(cls, samples: np.ndarray, max_seconds: float = SEGMENT_MAX_SECONDS) -> list[np.ndarray]:
        """Cut int16 mono samples into chunks of at most ``max_seconds``.

        Each cut lands on the quietest 10 ms frame in the last 40% before the
        limit (a VAD-lite split on frame energy), so a cut rarely splits a word.
        Audio that already fits, or is too short to hold a frame, is returned
        as a single chunk and never touched.
        """
        frame = int(TARGET_SAMPLE_RATE * _FRAME_MS / 1000)
        hop = int(TARGET_SAMPLE_RATE * _HOP_MS / 1000)
        max_len = int(max_seconds * TARGET_SAMPLE_RATE)
        if len(samples) <= max_len or len(samples) < frame:
            return [samples]

        frames = np.lib.stride_tricks.sliding_window_view(samples.astype(np.float32), frame)[::hop]
        energy = np.sqrt(np.mean(frames * frames, axis=1) + 1e-9)

        chunks: list[np.ndarray] = []
        start = 0
        while len(samples) - start > max_len:
            limit = start + max_len
            low = min(max(start + int(max_len * 0.6), 0) // hop, len(energy) - 1)
            high = min(limit // hop, len(energy))
            cut = (low + int(np.argmin(energy[low:high]))) * hop + frame // 2
            cut = min(max(cut, start + hop), limit)
            chunks.append(samples[start:cut])
            start = cut
        chunks.append(samples[start:])
        return [chunk for chunk in chunks if len(chunk)]

    @staticmethod
    def _decode(audio: bytes) -> np.ndarray:
        """Any container/codec -> mono 16 kHz int16 samples, in-process."""
        try:
            with av.open(io.BytesIO(audio)) as container:
                if not container.streams.audio:
                    raise ValueError("Cannot decode audio: no audio track in the file")
                resampler = av.AudioResampler(
                    format=av.AudioFormat("s16"), layout="mono", rate=TARGET_SAMPLE_RATE
                )
                chunks = []
                for frame in container.decode(container.streams.audio[0]):
                    for output in resampler.resample(frame):
                        chunks.append(output.to_ndarray().reshape(-1))
                for output in resampler.resample(None):  # flush the resampler tail
                    chunks.append(output.to_ndarray().reshape(-1))
        except FFmpegError as error:
            # main.py maps ValueError to a 400 with this message, so keep the type.
            raise ValueError(f"Cannot decode audio: {error}") from error

        if not chunks:
            raise ValueError("Cannot decode audio: no samples decoded")
        return np.concatenate(chunks).astype(np.int16, copy=False)

    @staticmethod
    def _write_wav(samples: np.ndarray, target: Path) -> None:
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)  # int16
            wav.setframerate(TARGET_SAMPLE_RATE)
            wav.writeframes(samples.tobytes())
