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

import json
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

import config
from storage import write_private

KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "LLM_MODEL"
BASE_URL_ENV = "OPENROUTER_BASE_URL"
PRESET_ENV = "LLM_PRESET"
EXTRA_ENV = "LLM_EXTRA"
KEYS_ENV = "LLM_PROVIDER_KEYS"

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


def provider_keys() -> dict[str, str]:
    """Keys kept per address, so switching service and back costs nothing.

    One JSON line rather than a file per provider: the settings file already
    exists, already ships with the app, and is already the thing someone may
    edit by hand.
    """
    raw = (os.getenv(KEYS_ENV) or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(address).strip().rstrip("/"): str(key).strip()
        for address, key in data.items()
        if isinstance(key, str) and key.strip()
    }


def key_for(base_url: str = "") -> str:
    """The key saved for this address, if there is one.

    Falls back to the key in force when the address is the one already in force.
    That is what makes a settings file written before this map existed keep
    working: the single key belongs to whatever address is configured, and only
    the map needs filling in from the next save onwards.
    """
    address = (base_url.strip() or current_base_url()).rstrip("/")
    saved = provider_keys()
    if address in saved:
        return saved[address]
    return current_key() if address == current_base_url().rstrip("/") else ""


def current_model() -> str:
    return (os.getenv(MODEL_ENV) or config.DEFAULT_LLM_MODEL).strip()


def write_pair(
    key: str,
    model: str,
    base_url: str = "",
    preset: str = "",
    extra: str | None = None,
    keys_json: str = "",
    keep_key: bool = True,
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
            if name in (KEY_ENV, MODEL_ENV, BASE_URL_ENV, PRESET_ENV, EXTRA_ENV, KEYS_ENV):
                stored[name] = stripped.partition("=")[2].strip().strip("'\"")
                continue
            kept.append(stripped)
    resolved = {
        KEY_ENV: (key.strip() or stored.get(KEY_ENV, "")) if keep_key else "",
        MODEL_ENV: model.strip() or stored.get(MODEL_ENV, ""),
        BASE_URL_ENV: base_url.strip() or stored.get(BASE_URL_ENV, ""),
        PRESET_ENV: preset.strip() or stored.get(PRESET_ENV, ""),
        KEYS_ENV: keys_json.strip() or stored.get(KEYS_ENV, ""),
        # `extra` is the one field where empty means "erase", not "keep": it is
        # a free-text box the user clears when the requirement no longer applies.
        # Everything else is a key or a value they are unlikely to blank.
        EXTRA_ENV: (extra or "").strip() if extra is not None else stored.get(EXTRA_ENV, ""),
    }
    for name, value in resolved.items():
        if value:
            kept.append(f"{name}={value}")
    write_private(path, "\n".join(kept) + "\n")
    return path


def apply(
    key: str,
    model: str,
    base_url: str = "",
    preset: str = "",
    extra: str | None = None,
    keys_json: str = "",
    keep_key: bool = True,
) -> None:
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
    if keys_json:
        os.environ[KEYS_ENV] = keys_json
    if not keep_key:
        os.environ.pop(KEY_ENV, None)
        config.OPENROUTER_API_KEY = ""


def save(
    key: str,
    model: str,
    base_url: str = "",
    preset: str = "",
    extra: str | None = None,
) -> None:
    address = (base_url.strip() or current_base_url()).rstrip("/")
    switching = address != current_base_url().rstrip("/")

    # The key in force belongs to the address in force. When the address changes
    # and nothing was typed, what belongs in force is that address's own key --
    # including none at all, rather than the previous service's key offered to a
    # service it was never issued by. Every key stays in the map either way, so
    # coming back is a matter of picking the service again.
    active = key.strip() or (key_for(address) if switching else "")
    keep = not switching or bool(active)

    merged = dict(provider_keys())
    # File the key in force under the address in force *before* the address
    # changes. A settings file written before this map existed holds one key and
    # no map, and moving away from its service would drop that key for good,
    # with nothing left to come back to.
    current_address = current_base_url().rstrip("/")
    if current_key() and current_address not in merged:
        merged[current_address] = current_key()
    if active:
        merged[address] = active
    keys_json = json.dumps(merged, ensure_ascii=False, sort_keys=True) if merged else ""

    write_pair(active, model, base_url, preset, extra, keys_json, keep_key=keep)
    apply(active, model, base_url, preset, extra, keys_json, keep_key=keep)


def current_preset() -> str:
    from llm import DEFAULT_PRESET

    return (os.getenv(PRESET_ENV) or DEFAULT_PRESET).strip()


def current_extra() -> str:
    return (os.getenv(EXTRA_ENV) or "").strip()


RETENTION_ENV = "RETENTION_DAYS"


def retention_days() -> int:
    """Days of history to keep. The organisation's number wins; then the user's own; 0 keeps all."""
    if config.POLICY.retention_days:
        return config.POLICY.retention_days
    try:
        return max(0, int(os.getenv(RETENTION_ENV, "0") or 0))
    except ValueError:
        return 0


def save_retention(days: int) -> None:
    """Keep the user's own retention in the settings file. Zero keeps everything."""
    path = settings_path()
    kept: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and stripped.partition("=")[0].strip() != RETENTION_ENV:
                kept.append(stripped)
    if days > 0:
        kept.append(f"{RETENTION_ENV}={days}")
        os.environ[RETENTION_ENV] = str(days)
    else:
        os.environ.pop(RETENTION_ENV, None)
    write_private(path, "\n".join(kept) + "\n")


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