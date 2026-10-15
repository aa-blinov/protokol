"""Files the app keeps on the user's Mac, and the one disk-level fact it can check.

The settings file holds the provider key, the history holds transcripts and the
names they contain, and the analysis cache holds transcripts too. All of them are
written owner-only (0600), so another account on the same Mac cannot read them.

The app cannot encrypt the disk for the user. It can say whether FileVault is on:
with it off, a stolen laptop gives away everything above in clear text.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_UNCHECKED = object()
_filevault_state: object = _UNCHECKED


def write_private(path: Path, text: str) -> None:
    """Replace the file atomically, readable and writable by the owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    # O_CREAT only sets the mode on a new file; a leftover .tmp keeps its old mode.
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def parse_filevault(output: str) -> bool | None:
    """`fdesetup status` answers 'FileVault is On.' or 'FileVault is Off.'."""
    text = output.lower()
    if "filevault is on" in text:
        return True
    if "filevault is off" in text:
        return False
    return None


def filevault_enabled() -> bool | None:
    """Whether FileVault is on. None where it cannot be asked (not macOS, or no answer).

    The answer is cached for the life of the process: it does not change while the
    app runs, and the health check that asks it runs often.
    """
    global _filevault_state
    if _filevault_state is _UNCHECKED:
        try:
            result = subprocess.run(
                ["fdesetup", "status"], capture_output=True, text=True, timeout=5, check=False
            )
            _filevault_state = parse_filevault(result.stdout + result.stderr)
        except (OSError, subprocess.SubprocessError):
            _filevault_state = None
    return _filevault_state  # type: ignore[return-value]
