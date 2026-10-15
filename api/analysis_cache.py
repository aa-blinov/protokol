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
from storage import write_private

MAX_ENTRIES = 8

# Bump whenever recognition or diarization output changes for the same audio. The
# key covers the recording, the format and the model, but not the code: without a
# version an entry written by the previous code is returned as if it were current.
# 2: diarization folds slivers by seconds; 3: word-separator bonus on CTC;
# 4: GigaAM v3 e2e RNN-T head with 20 s chunks; 5: clustering threshold 0.46 and
# the speaker-turn join that keeps the later end.
PIPELINE_VERSION = 5


def key_for(audio: bytes, suffix: str) -> str:
    """Digest of the recording, the format, the ASR model and the pipeline version.

    All of them change the transcript on their own: the same bytes named .m4a and
    .mp3 can decode differently, a different model directory means a different
    transcript for the same audio, and a code change alters the output with no
    change to the audio at all. Truncated to 24 hex digits -- this identifies a
    cache file, it is not a security boundary.
    """
    digest = hashlib.sha256()
    digest.update(audio)
    digest.update(f"|{suffix}|{config.GIGAAM_DIR}|v{PIPELINE_VERSION}".encode())
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
    write_private(_path(key), json.dumps(payload, ensure_ascii=False))
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


def purge_except(keep: set[str]) -> int:
    """Delete every cache entry that no session refers to any more; returns the count.

    Removing a recording from the history must take its transcript off the disk
    as well, not wait for eight newer recordings to push it out.
    """
    removed = 0
    for entry in _path("").parent.glob("*.json"):
        if entry.stem not in keep:
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed
