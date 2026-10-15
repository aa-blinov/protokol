"""Organisation policy: settings a company fixes on every Mac it deploys the app to.

An administrator, or an MDM profile, puts a JSON file at
/Library/Application Support/Protokol/policy.json. The app reads it once, when it
starts; a change takes effect after a restart. PROTOKOL_POLICY_FILE points
somewhere else, for tests and for trying a policy.

Every key is optional and a key left out is not enforced. A bad value is reported
in the app and skipped, so the rest of the policy still applies. Nothing in the
file is a secret: it sets rules, it does not carry keys.

    {
      "base_url": "https://llm.example.ru/v1",
      "lock_settings": true,
      "retention_days": 30,
      "allow_export": false,
      "zdr": true,
      "data_collection": "deny"
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path("/Library/Application Support/Protokol/policy.json")
KNOWN_KEYS = frozenset(
    {"base_url", "lock_settings", "retention_days", "allow_export", "zdr", "data_collection"}
)
MAX_RETENTION_DAYS = 3650


@dataclass(frozen=True)
class Policy:
    """What the policy file says, after validation. Defaults mean "not enforced"."""

    present: bool = False
    base_url: str | None = None
    lock_settings: bool = False
    retention_days: int | None = None
    allow_export: bool = True
    zdr: bool | None = None
    data_collection: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)


def path() -> Path:
    return Path(os.getenv("PROTOKOL_POLICY_FILE") or DEFAULT_PATH)


def load(file: Path | None = None) -> Policy:
    """Read and validate the policy file. A missing file is simply no policy."""
    file = file or path()
    if not file.is_file():
        return Policy()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return Policy(present=True, errors=(f"файл политики не читается: {error}",))
    if not isinstance(data, dict):
        return Policy(present=True, errors=("файл политики должен быть объектом JSON",))

    errors = [f"неизвестный ключ «{name}»" for name in sorted(set(data) - KNOWN_KEYS)]
    values: dict[str, Any] = {}
    checks = {
        "base_url": _check_url,
        "lock_settings": _check_bool,
        "retention_days": _check_days,
        "allow_export": _check_bool,
        "zdr": _check_bool,
        "data_collection": _check_collection,
    }
    for name, check in checks.items():
        if name not in data:
            continue
        value, problem = check(data[name])
        if problem:
            errors.append(f"«{name}»: {problem}")
        else:
            values[name] = value
    return Policy(present=True, errors=tuple(errors), **values)


def _check_url(value: object) -> tuple[Any, str]:
    if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
        return value.strip().rstrip("/"), ""
    return None, "нужен адрес, начинающийся с http:// или https://"


def _check_bool(value: object) -> tuple[Any, str]:
    if isinstance(value, bool):
        return value, ""
    return None, "нужно true или false"


def _check_days(value: object) -> tuple[Any, str]:
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_RETENTION_DAYS:
        return value, ""
    return None, f"нужно целое число дней от 1 до {MAX_RETENTION_DAYS}"


def _check_collection(value: object) -> tuple[Any, str]:
    if value in ("allow", "deny"):
        return value, ""
    return None, "нужно «allow» или «deny»"
