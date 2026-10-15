"""Licence check: a 14-day trial, then a signed licence file that works offline.

A licence is a JSON payload with a detached Ed25519 signature, issued by the
vendor's tools/license_tool.py. The app holds only the public key, so it can check
a licence but cannot make one. The licence file and the trial marker sit next to
the settings file.

When the trial is over and no valid licence is installed, the app stops
transcribing and summarising. The history stays readable, and nothing is deleted.

What this does not do: stop someone who edits the app itself. A licence protects
the terms between the vendor and the customer, not the binary.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import ed25519
import settings
from storage import write_private

TRIAL_DAYS = 14
# Public half of the vendor's signing key. The private seed stays with the vendor
# (see tools/license_tool.py); it is never in this repository.
PUBLIC_KEY_HEX = "ce2a10573a187be5bce901ea747c471f86c033f3c9fef6aea1342346404e4526"
PUBLIC_KEY = bytes.fromhex(PUBLIC_KEY_HEX)
REQUIRED_FIELDS = ("customer", "edition", "seats", "issued")
BAD_SIGNATURE = "Подпись лицензии не проверяется: файл изменён или выдан не нами"


class LicenceError(Exception):
    """Carries a sentence the user can read in the app."""


def _folder() -> Path:
    return settings.settings_path().parent


def _trial_path() -> Path:
    return _folder() / "trial.json"


def _licence_path() -> Path:
    return _folder() / "license.json"


def _trial_started(today: dt.date) -> dt.date:
    """The first day the app ran. Written once, on first use.

    A damaged marker starts the trial again rather than locking the app: a broken
    file is more likely a disk problem than a customer's attempt to gain time.
    """
    marker = _trial_path()
    if marker.is_file():
        try:
            return dt.date.fromisoformat(json.loads(marker.read_text(encoding="utf-8"))["started"])
        except (ValueError, KeyError, TypeError, OSError):
            pass
    write_private(marker, json.dumps({"started": today.isoformat()}))
    return today


def _verified(text: str) -> tuple[dict[str, Any], str, bytes]:
    """Parse a licence document and check its signature. Raises LicenceError."""
    try:
        document = json.loads(text)
        payload_text = document["payload"]
        signature_hex = document["signature"]
        if not isinstance(payload_text, str) or not isinstance(signature_hex, str):
            raise TypeError("payload and signature must be strings")
        signature = bytes.fromhex(signature_hex)
    except (ValueError, KeyError, TypeError) as error:
        raise LicenceError("Это не файл лицензии") from error
    if not ed25519.verify(PUBLIC_KEY, payload_text.encode("utf-8"), signature):
        raise LicenceError(BAD_SIGNATURE)
    try:
        payload = json.loads(payload_text)
    except ValueError as error:
        raise LicenceError("Файл лицензии повреждён") from error
    if not isinstance(payload, dict) or any(field not in payload for field in REQUIRED_FIELDS):
        raise LicenceError("В лицензии не хватает обязательных полей")
    return payload, payload_text, signature


def _installed() -> tuple[dict[str, Any] | None, str]:
    """(payload, problem). The payload is None when no valid licence is installed."""
    path = _licence_path()
    if not path.is_file():
        return None, ""
    try:
        payload, _, _ = _verified(path.read_text(encoding="utf-8"))
    except (LicenceError, OSError) as error:
        return None, str(error) if isinstance(error, LicenceError) else "Файл лицензии не читается"
    return payload, ""


def status(today: dt.date | None = None) -> dict[str, Any]:
    """What the app shows: trial, licensed or expired, and what is left of it."""
    today = today or dt.date.today()
    payload, problem = _installed()
    if payload is not None:
        expires = payload.get("expires")
        base = {
            "customer": payload.get("customer"),
            "edition": payload.get("edition"),
            "seats": payload.get("seats"),
            "expires": expires,
            "problem": "",
        }
        if expires is None:
            return {"state": "licensed", "days_left": None, **base}
        end = dt.date.fromisoformat(expires)
        if end >= today:
            return {"state": "licensed", "days_left": (end - today).days, **base}
        return {"state": "expired", "days_left": 0, **base, "problem": "Срок лицензии истёк"}
    left = TRIAL_DAYS - (today - _trial_started(today)).days
    if left > 0:
        return {"state": "trial", "days_left": left, "customer": None, "edition": None,
                "seats": None, "expires": None, "problem": problem}
    return {"state": "expired", "days_left": 0, "customer": None, "edition": None,
            "seats": None, "expires": None, "problem": problem or "Пробный период закончился"}


def require_active(today: dt.date | None = None) -> None:
    """Raise LicenceError when transcription and summaries must stop."""
    current = status(today)
    if current["state"] == "expired":
        raise LicenceError(current["problem"] or "Лицензия не действует")


def activate(text: str, today: dt.date | None = None) -> dict[str, Any]:
    """Install a licence document. Nothing is stored unless the signature holds."""
    today = today or dt.date.today()
    payload, payload_text, _ = _verified(text)
    expires = payload.get("expires")
    if expires is not None:
        try:
            end = dt.date.fromisoformat(expires)
        except (TypeError, ValueError) as error:
            raise LicenceError("Срок в лицензии не распознан") from error
        if end < today:
            raise LicenceError("Срок этой лицензии уже истёк")
    document = {"payload": payload_text, "signature": json.loads(text)["signature"]}
    write_private(_licence_path(), json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return status(today)
