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
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "audio.wav"
            self._write_wav(samples, wav_path)
            text = self.model.recognize(str(wav_path))
        return text, duration

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
