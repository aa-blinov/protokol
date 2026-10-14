"""Speech to text via GigaAM-v3 ONNX (``onnx-asr``).

Uses the ``e2e`` RNN-T variant: unlike the plain v3 heads it adds punctuation *and*
normalises dictated digits ("восемь девятьсот..." -> "8 912..."), which is what
lets the PII model recognise phone, passport and INN numbers at all. With a plain
head those numbers reach OpenRouter unmasked, so this choice is a privacy
requirement, not a quality preference.

Uploaded audio can be any container or codec, so it is decoded to 16 kHz mono
PCM with PyAV before inference — the model only accepts 16 kHz PCM. PyAV is used
instead of an external `ffmpeg` binary on purpose: its wheel embeds the FFmpeg
libraries, so the decoder ships inside the PyInstaller bundle. Calling a system
`ffmpeg` would break the app on any machine that has not installed one.

Decoded samples are written to a WAV and handed to ``recognize`` as a path, not
as an array: ``onnx_asr`` does not renormalise arrays, so passing samples would
mean reproducing its int16->float32 scaling exactly to avoid silently degrading
accuracy. Letting it read the WAV keeps that step in its hands.

Long audio is split first, into chunks of at most ``SEGMENT_MAX_SECONDS``. The
RNN-T head is trained on short utterances; its model card limits it to about 25 s.
Measured on an 8-minute interview, 120 s chunks recognised 904 words where 20 s
and 25 s chunks recognised 1051 and 1053: the long chunks silently lose speech.
The CTC head lost words at 120 s as well (1011 against 1059 at 20 s), and on a
labelled dialogue its error rate went from 4.35% at 20 s to 5.83% at 120 s.
Chunks are cut at the quietest frame near the limit rather than on a fixed grid,
so a cut rarely lands mid-word.
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
from dialogue import Word, words_from_timed_text

MODEL_NAME = "gigaam-v3-e2e-rnnt"
# int8 weights: on our tests the same accuracy as fp32 (0% WER clean, +0.8 pp at
# 0 dB noise — one word in 122), but the model loads ~0.5 GB lighter (225 MB on
# disk vs 845 MB) and the bundle shrinks with it. On a 16 GB laptop that matters.
QUANTIZATION = "int8"
TARGET_SAMPLE_RATE = 16_000

# Chunk ceiling for either head. The RNN-T model card limits it to about 25 s, and
# 120 s chunks lost about 14% of the words on a real interview (see the module
# docstring). 20 s keeps a margin under that limit; 25 s and 20 s scored the same
# within noise.
SEGMENT_MAX_SECONDS = 20.0
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
            quantization=QUANTIZATION,
        )
        # Same weights, but returning time per token — used to attribute words to
        # speaker turns instead of transcribing each turn blind.
        self._timestamps = self.model.with_timestamps()


    def transcribe(self, audio: bytes, suffix: str = ".wav") -> tuple[str, float]:
        """Return ``(text, duration_seconds)`` for raw audio bytes.

        No cap on length: the previous one-hour limit was a product decision, not
        a property of the models. What bounds a request now is memory -- the
        upload is read whole and decoded whole before anything is checked, so a
        long recording is accepted and paid for in RAM.
        """
        samples = self._decode(audio)
        duration = len(samples) / TARGET_SAMPLE_RATE
        return self.transcribe_samples(samples), duration

    @staticmethod
    def decode(audio: bytes) -> np.ndarray:
        """Raw audio bytes -> 16 kHz mono int16 samples (public wrapper)."""
        return Stt._decode(audio)

    def transcribe_samples(self, samples: np.ndarray) -> str:
        """Recognize already-decoded 16 kHz mono samples, splitting long audio."""
        chunks = self._split_long(samples)
        texts: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for index, chunk in enumerate(chunks):
                wav_path = Path(tmp) / f"chunk{index}.wav"
                self._write_wav(chunk, wav_path)
                texts.append(self.model.recognize(str(wav_path)).strip())
        return " ".join(text for text in texts if text)

    def transcribe_words(self, samples: np.ndarray) -> list[Word]:
        """Recognize the whole audio once and return words with their times.

        One pass keeps the model's own context across speaker turns; the caller
        then assigns each word to the speaker turn it falls in. Long audio is
        still split at quiet frames, and each chunk's times are shifted to the
        whole recording.
        """
        words: list[Word] = []
        offset = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            for index, chunk in enumerate(self._split_long(samples)):
                wav_path = Path(tmp) / f"words{index}.wav"
                self._write_wav(chunk, wav_path)
                result = self._timestamps.recognize(str(wav_path))
                times = self._char_times(result.tokens, result.timestamps, result.text)
                words.extend(
                    Word(word.text, word.start + offset, word.end + offset)
                    for word in words_from_timed_text(result.text, times)
                )
                offset += len(chunk) / TARGET_SAMPLE_RATE
        return words

    @staticmethod
    def _char_times(tokens: list[str], timestamps: list[float] | None, text: str) -> list[float]:
        """The time of every character in ``text``.

        ``onnx_asr`` builds its text from the tokens with a whitespace cleanup,
        so text and tokens are not index-aligned. The cleanup only drops or
        collapses whitespace, which keeps the other characters in order — so
        walking the text and taking the next matching character in the raw token
        stream recovers each character's time without re-implementing it.
        """
        if not timestamps:
            return [0.0] * len(text)
        raw = "".join(tokens)
        raw_time = [time for token, time in zip(tokens, timestamps) for _ in token]
        times: list[float] = []
        index = 0
        for char in text:
            while index < len(raw) and raw[index] != char:
                index += 1
            times.append(raw_time[index] if index < len(raw) else (times[-1] if times else 0.0))
            index += 1
        return times

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
