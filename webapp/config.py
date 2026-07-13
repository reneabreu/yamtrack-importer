"""Persistent settings + data locations for the web app."""

from __future__ import annotations

import json
import os


def load_dotenv(path: str = ".env") -> None:
    """Seed os.environ from a .env file (does not override real env vars).

    Under Docker Compose these come in as real environment variables; when
    running the app directly (``python -m webapp.app``) this lets the Settings
    page pick up keys like TMDB_API_KEY / MAL_CLIENT_ID from .env too.
    """
    # look in the current dir first, then the project root (parent of webapp/)
    candidates = [path, os.path.join(os.path.dirname(os.path.dirname(__file__)), path)]
    for p in candidates:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


load_dotenv()

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
CACHE_PATH = os.path.join(DATA_DIR, "tmdb_cache.json")
OVERRIDES_PATH = os.path.join(DATA_DIR, "overrides.json")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.db")

# Fields stored in settings.json (env vars provide defaults).
_KEYS = {
    "tmdb_key": "TMDB_API_KEY",
    "mal_client_id": "MAL_CLIENT_ID",
}


def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_settings() -> dict:
    ensure_data_dir()
    settings = {k: os.environ.get(env, "") for k, env in _KEYS.items()}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as fh:
                stored = json.load(fh)
            for k in _KEYS:
                if stored.get(k):
                    settings[k] = stored[k]
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save_settings(new: dict) -> None:
    ensure_data_dir()
    current = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as fh:
                current = json.load(fh)
        except (json.JSONDecodeError, OSError):
            current = {}
    # Only overwrite a field when a non-empty value is submitted — password
    # fields render blank and would otherwise clear the stored key on save.
    # Blank = keep existing.
    for k in _KEYS:
        value = (new.get(k) or "").strip()
        if value:
            current[k] = value
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def masked(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "•" * len(value)
    return value[:3] + "•" * (len(value) - 6) + value[-3:]
