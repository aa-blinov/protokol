"""H6: does CoreML change anything beyond speed?

config.ort_providers() prefers CoreML on Apple Silicon and falls back to CPU, so
the honest check is not what was requested but what onnxruntime actually loaded.
Run this twice and diff the two outputs:

  USE_COREML=1 .venv/bin/python benchmarks/run_coreml_check.py
  USE_COREML=0 .venv/bin/python benchmarks/run_coreml_check.py

It prints the providers each session really got, how long diarize took, and a
digest of the speaker turns so a silent behavioural difference cannot hide behind
a matching score.
"""

from __future__ import annotations

import hashlib
import json
import argparse
import resource
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from diarization import SAMPLE_RATE, Diarizer  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", default="short", choices=["short", "long"])
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    name = "call_2spk.npy" if args.audio == "short" else "call_long.npy"
    path = CORPUS / name
    if not path.is_file():
        raise SystemExit(
            f"нет {path}\nсначала соберите корпус: .venv/bin/python benchmarks/make_corpus.py"
        )
    audio = np.load(path)
    diarizer = Diarizer(
        config.DIARIZATION_SEG_DIR,
        config.DIARIZATION_EMB_PATH,
        threads=config.INFERENCE_THREADS,
    )
    # The first call pays CoreML model compilation, so it is timed and dropped.
    diarizer.diarize(audio)
    timings = []
    turns = []
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    for _ in range(args.repeat):
        started = time.perf_counter()
        turns = diarizer.diarize(audio)
        timings.append(time.perf_counter() - started)
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    # CPU seconds, not watts: no root needed. If CoreML really moved work off the
    # CPU this falls even when wall-clock does not.
    cpu_seconds = (cpu_after.ru_utime - cpu_before.ru_utime) + (
        cpu_after.ru_stime - cpu_before.ru_stime
    )

    # onnxruntime silently drops a provider it cannot build, so ask the sessions.
    segmentation = list(diarizer._vad._model.get_providers())
    embedding = list(diarizer._embedding.get_providers())
    digest = [
        [round(t.start, 2), round(t.end, 2), t.speaker] for t in turns
    ]
    audio_seconds = audio.size / SAMPLE_RATE
    wall = min(timings) * args.repeat

    report = {
        "USE_COREML": config.USE_COREML,
        "requested": config.ort_providers(),
        "segmentation_providers": segmentation,
        "embedding_providers": embedding,
        "seconds_best": round(min(timings), 2),
        "seconds_median": round(sorted(timings)[len(timings) // 2], 2),
        "runs": [round(t, 2) for t in timings],
        "cpu_seconds_total": round(cpu_seconds, 2),
        "cpu_per_wall": round(cpu_seconds / wall, 3) if wall else None,
        "peak_rss_mb": round(cpu_after.ru_maxrss / 1024 / 1024, 1),
        "audio_minutes": round(audio_seconds / 60, 1),
        "realtime_factor": round(min(timings) / audio_seconds, 4),
        "turns": len(turns),
        "speakers": sorted({t.speaker for t in turns}),
        "digest_sha": hashlib.sha256(json.dumps(digest).encode()).hexdigest()[:16],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())