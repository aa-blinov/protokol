"""Cache of analysed recordings, so the summary can be re-run without re-listening.

Transcribing is the expensive half: about 30 s per twenty minutes on CPU, all of
it spent before the prompt is even relevant. The summary prompt, on the other
hand, changes every time the user tweaks the preset or the extra instruction.

Splitting the two lets the second be free. Entries are keyed by the digest of
the audio bytes plus the model directory, so a different file or a different STT
never returns a stale transcript. The cache is bounded and lives beside the
settings file, which means it also survives a restart -- the same reason the
history moved out of localStorage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import config
import settings

MAX_ENTRIES = 8


def key_for(audio: bytes, suffix: str) -> str:
    """Digest of the recording, the format and the ASR model.

    All three, because each of them changes the transcript on its own: the same
    bytes named .m4a and .mp3 can decode differently, and a different model
    directory means a different transcript for the same audio. Truncated to 24
    hex digits -- this identifies a cache file, it is not a security boundary.
    """
    digest = hashlib.sha256()
    digest.update(audio)
    digest.update(f"|{suffix}|{config.GIGAAM_DIR}".encode())
    return digest.hexdigest()[:24]


def _path(key: str) -> Path:
    return settings.settings_path().parent / "cache" / f"{key}.json"


def get(key: str) -> dict[str, Any] | None:
    path = _path(key)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def put(key: str, payload: dict[str, Any]) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    _trim()


def _trim() -> None:
    """Keep the newest few recordings; audio of a long call fills the disk."""
    entries = sorted(
        _path("").parent.glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale in entries[MAX_ENTRIES:]:
        try:
            stale.unlink()
        except OSError:
            pass
