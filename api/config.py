"""Runtime settings, all overridable by environment."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def _load_env_file() -> None:
    """Fill os.environ from a .env file without overriding real environment.

    A desktop app launched by double-click gets no shell environment at all, so
    the OpenRouter key has to come from a file. STTSHKA_ENV_FILE picks which one
    (the Electron shell points it at userData/.env); otherwise the repo-root
    .env is used. Values already present in the environment always win, matching
    how MODELS_DIR and WEB_DIST_DIR behave.
    """
    path = Path(os.getenv("STTSHKA_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_env_file()

# The organisation's policy file, when there is one, wins over the user's own settings
# for the things it fixes. It is read here, before any of these values are taken.
import policy as _policy_file  # noqa: E402

POLICY = _policy_file.load()
if POLICY.base_url:
    os.environ["OPENROUTER_BASE_URL"] = POLICY.base_url


# models/ sits next to api/ in the repo and is mounted at /app/models in Docker.
MODELS_DIR = Path(os.getenv("MODELS_DIR", Path(__file__).resolve().parents[1] / "models"))
GIGAAM_DIR = MODELS_DIR / "gigaam"
PII_NER_DIR = MODELS_DIR / "rubert-pii"
# Speaker diarization: pyannote segmentation (turn boundaries) + a 3D-Speaker
# CAM++ embedding model (who each turn is), then cosine clustering. Small
# (~33 MB) next to the ASR/NER models. See api/diarization.py for why CAM++.
DIARIZATION_SEG_DIR = MODELS_DIR / "diarization" / "segmentation"
DIARIZATION_EMB_PATH = MODELS_DIR / "diarization" / "embedding.onnx"

# Built frontend served by FastAPI itself in the desktop app. Empty disables it
# (Docker serves the UI through nginx instead).
WEB_DIST_DIR = Path(os.getenv("WEB_DIST_DIR", Path(__file__).resolve().parents[1] / "web" / "dist"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4.1-flash")
# What the provider may do with the prompt. "deny" keeps requests away from
# providers that store prompts non-transiently or train on them. OpenRouter's own
# default is "allow", so the app asks for "deny" unless told otherwise.
LLM_DATA_COLLECTION = POLICY.data_collection or os.getenv("LLM_DATA_COLLECTION", "deny")
# Zero data retention: only endpoints with a ZDR policy. Off by default, because a
# model may have no such endpoint at all, and then the request fails loudly.
LLM_ZDR = POLICY.zdr if POLICY.zdr is not None else os.getenv("LLM_ZDR", "0") == "1"
# How hard the summary model reasons before it answers: "", "low", "medium", "high".
# Empty leaves the provider's default in place.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")

# Inference threads. Kept modest so the app stays responsive while a model runs.
INFERENCE_THREADS = int(os.getenv("INFERENCE_THREADS", "4"))

# Apple Silicon has a CoreML execution provider in onnxruntime. Measured on an
# M4 Pro and checked with onnxruntime's own
# tools.check_onnx_model_mobile_usability: all three of our models come back
# "not recommended". Our graphs split into 4-244 CoreML subgraphs, and the
# CPU<->CoreML crossings cost more than the accelerated ops gain -- diarization
# ran 11% slower with 13% more CPU time and 33% more RSS than plain CPU. ONNX
# Runtime's own deployment guide says to start from the CPU EP for a quantized
# model, which is exactly what gigaam int8 is. Kept behind a switch because
# CoreML does win on some models (fixed-shape CNNs); it just does not on these.
IS_MAC_ARM = platform.system() == "Darwin" and platform.machine() == "arm64"
USE_COREML = os.getenv("USE_COREML", "0") == "1"


def ort_providers() -> list[str]:
    """Providers for onnxruntime, best first; ORT falls back to CPU per node."""
    if USE_COREML and IS_MAC_ARM:
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def session_options(threads: int = INFERENCE_THREADS):
    """onnxruntime options for every model in the sidecar, so they share one policy.

    The thread count is set on each session. The diarizer's segmentation model used
    to be created without options, which left it on onnxruntime's default thread
    count and out of reach of INFERENCE_THREADS. Spinning is off: between the many
    small calls of the speech decoder an idle thread pool busy-waits, and on a
    20-minute recording that cost about a sixth of the CPU time with the same output.
    """
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return options
