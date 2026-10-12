"""Runtime settings the user can change from the app: the OpenRouter key and the
chat model.

Both live in the same file the desktop shell already pointed STTSHKA_ENV_FILE at
(userData/.env), because that is what `config._load_env_file` reads on start.
Keeping one file means an app that starts from the settings dialog and an app
that starts from a shell behave the same.

Saving takes effect without a restart: the values are written to the file *and*
pushed into os.environ and onto `config`, so `get_llm()` picks up a key that was
typed a second ago.

The key is never sent back to the browser. Callers get a hint -- first and last
few characters -- which is enough to tell two keys apart and useless if the
response is intercepted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

import config

KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "LLM_MODEL"
BASE_URL_ENV = "OPENROUTER_BASE_URL"
PRESET_ENV = "LLM_PRESET"
EXTRA_ENV = "LLM_EXTRA"

KEY_PAGE = "https://openrouter.ai/keys"
CREDITS_PAGE = "https://openrouter.ai/credits"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def settings_path() -> Path:
    """Where the key, the model and the API address live on disk."""
    return Path(os.getenv("STTSHKA_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))


def current_base_url() -> str:
    """API address in force. OpenRouter unless the user pointed it elsewhere."""
    return (os.getenv(BASE_URL_ENV) or config.OPENROUTER_BASE_URL or DEFAULT_BASE_URL).strip()


def is_openrouter(base_url: str | None = None) -> bool:
    """OpenRouter is the default provider; it is also the only one whose balance
    can be read, which is why the credits call is provider-specific."""
    return "openrouter.ai" in (base_url or current_base_url()).lower()


@dataclass(frozen=True)
class KeyHint:
    """Enough to recognise a key without disclosing it."""

    masked: str
    tail: str

    @classmethod
    def of(cls, key: str) -> "KeyHint":
        key = (key or "").strip()
        if not key:
            return cls("", "")
        head = key[: min(11, len(key) - 4)] if len(key) > 15 else key[:4]
        return cls(f"{head}…{key[-4:]}" if len(key) > 15 else key, key[-4:])


def current_key() -> str:
    """The key in force right now: the environment wins over the stored file."""
    return (os.getenv(KEY_ENV) or config.OPENROUTER_API_KEY or "").strip()


def current_model() -> str:
    return (os.getenv(MODEL_ENV) or config.DEFAULT_LLM_MODEL).strip()


def write_pair(
    key: str, model: str, base_url: str = "", preset: str = "", extra: str | None = None
) -> Path:
    """Persist the three values, leaving any other line in the file untouched.

    An empty argument means "keep what is stored", not "erase it". The dialog
    sends an empty key whenever the user only changes the model, and writing the
    file from the arguments alone would silently drop a key that is still valid.
    """
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    stored: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            name = stripped.partition("=")[0].strip()
            if name in (KEY_ENV, MODEL_ENV, BASE_URL_ENV, PRESET_ENV, EXTRA_ENV):
                stored[name] = stripped.partition("=")[2].strip().strip("'\"")
                continue
            kept.append(stripped)
    resolved = {
        KEY_ENV: key.strip() or stored.get(KEY_ENV, ""),
        MODEL_ENV: model.strip() or stored.get(MODEL_ENV, ""),
        BASE_URL_ENV: base_url.strip() or stored.get(BASE_URL_ENV, ""),
        PRESET_ENV: preset.strip() or stored.get(PRESET_ENV, ""),
        # `extra` is the one field where empty means "erase", not "keep": it is
        # a free-text box the user clears when the requirement no longer applies.
        # Everything else is a key or a value they are unlikely to blank.
        EXTRA_ENV: (extra or "").strip() if extra is not None else stored.get(EXTRA_ENV, ""),
    }
    for name, value in resolved.items():
        if value:
            kept.append(f"{name}={value}")
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return path


def apply(key: str, model: str, base_url: str = "", preset: str = "", extra: str | None = None) -> None:
    """Push the values into the live process so no restart is needed."""
    if key:
        os.environ[KEY_ENV] = key
        config.OPENROUTER_API_KEY = key
    if model:
        os.environ[MODEL_ENV] = model
        config.DEFAULT_LLM_MODEL = model
    if base_url:
        os.environ[BASE_URL_ENV] = base_url
        config.OPENROUTER_BASE_URL = base_url
    if preset:
        os.environ[PRESET_ENV] = preset
    if extra is not None:
        os.environ[EXTRA_ENV] = extra


def save(
    key: str, model: str, base_url: str = "", preset: str = "", extra: str | None = None
) -> None:
    write_pair(key, model, base_url, preset, extra)
    apply(key, model, base_url, preset, extra)


def current_preset() -> str:
    from llm import DEFAULT_PRESET

    return (os.getenv(PRESET_ENV) or DEFAULT_PRESET).strip()


def current_extra() -> str:
    return (os.getenv(EXTRA_ENV) or "").strip()


def verify(key: str, base_url: str = "") -> dict:
    """Check a key against whatever provider the user pointed us at.

    Every OpenAI-compatible provider answers ``GET /models`` and returns 401 for a
    bad key, so that is the check used everywhere. OpenRouter additionally
    exposes the balance, which makes for a more useful message, but it is not
    available elsewhere and is not required.
    """
    key = (key or "").strip()
    if not key:
        return {"ok": False, "detail": "Ключ пустой"}
    root = (base_url.strip() or current_base_url()).rstrip("/")
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = httpx.get(f"{root}/models", headers=headers, timeout=15.0)
    except httpx.HTTPError as error:
        return {"ok": False, "detail": f"Не удалось связаться с {root}: {error}"}
    if response.status_code == 401:
        return {"ok": False, "detail": "Ключ отклонён (401)"}
    if response.status_code == 403:
        return {"ok": False, "detail": "Ключ отклонён (403)"}
    if response.status_code != 200:
        return {"ok": False, "detail": f"Провайдер ответил {response.status_code}"}

    detail = "Ключ рабочий"
    if "openrouter.ai" in root.lower():
        try:
            credits = httpx.get(f"{root}/credits", headers=headers, timeout=15.0)
            if credits.status_code == 200:
                data = credits.json().get("data") or {}
                total, used = data.get("total_credits"), data.get("total_usage")
                if isinstance(total, (int, float)):
                    detail += f", осталось {total - (used or 0):.2f} из {total:.2f}"
        except (httpx.HTTPError, ValueError):
            pass
    return {"ok": True, "detail": detail}


def list_models(key: str, base_url: str = "") -> list[dict]:
    """The provider's catalogue, for the model picker.

    Requires the address to be in force: the list comes from the provider the
    user configured, not from a hardcoded host.
    """
    root = (base_url.strip() or current_base_url()).rstrip("/")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        response = httpx.get(f"{root}/models", headers=headers, timeout=20.0)
    except httpx.HTTPError as error:
        raise RuntimeError(f"Не удалось получить список моделей: {error}") from error
    if response.status_code != 200:
        raise RuntimeError(f"Провайдер ответил {response.status_code}")
    models = []
    for item in response.json().get("data") or []:
        identifier = item.get("id")
        if not identifier:
            continue
        pricing = item.get("pricing") or {}
        models.append(
            {
                "id": identifier,
                "name": item.get("name") or identifier,
                "context": item.get("context_length"),
                "prompt_price": _price(pricing.get("prompt")),
                "completion_price": _price(pricing.get("completion")),
            }
        )
    # Cheapest first, because that is what most people are after; models with no
    # quoted price go last rather than pretending to be free.
    return _sort_models(models)


def _sort_models(models: list[dict]) -> list[dict]:
    return sorted(models, key=lambda m: (m["prompt_price"] is None, m["prompt_price"] or 0.0, m["id"]))


def _price(value: object) -> float | None:
    """OpenRouter quotes USD per token; the UI shows USD per million.

    Free and variable-price models carry a negative sentinel instead of a real
    number. Treating that as a price would sort them to the front of the list as
    the cheapest things in the catalogue, so it becomes "unknown" and they sort
    last.
    """
    try:
        amount = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(amount * 1_000_000, 4) if amount >= 0 else None