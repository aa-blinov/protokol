"""Runtime settings, all overridable by environment."""

from __future__ import annotations

import os
import platform
from pathlib import Path

# models/ sits next to api/ in the repo and is mounted at /app/models in Docker.
MODELS_DIR = Path(os.getenv("MODELS_DIR", Path(__file__).resolve().parents[1] / "models"))
GIGAAM_DIR = MODELS_DIR / "gigaam"
PII_NER_DIR = MODELS_DIR / "rubert-pii"

# Built frontend served by FastAPI itself in the desktop app. Empty disables it
# (Docker serves the UI through nginx instead).
WEB_DIST_DIR = Path(os.getenv("WEB_DIST_DIR", Path(__file__).resolve().parents[1] / "web" / "dist"))

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")

# Inference threads. Kept modest so the app stays responsive while a model runs.
INFERENCE_THREADS = int(os.getenv("INFERENCE_THREADS", "4"))

# Apple Silicon has a CoreML execution provider in onnxruntime, which is the
# whole reason to run natively instead of under Docker/rosetta. Disable with
# USE_COREML=0 if it ever misbehaves: the CPU path is the tested baseline.
IS_MAC_ARM = platform.system() == "Darwin" and platform.machine() == "arm64"
USE_COREML = os.getenv("USE_COREML", "1" if IS_MAC_ARM else "0") == "1"


def ort_providers() -> list[str]:
    """Providers for onnxruntime, best first; ORT falls back to CPU per node."""
    if USE_COREML and IS_MAC_ARM:
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]
