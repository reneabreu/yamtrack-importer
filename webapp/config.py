"""Persistent settings + data locations for the web app."""

from __future__ import annotations

import json
import os

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
CACHE_PATH = os.path.join(DATA_DIR, "tmdb_cache.json")
OVERRIDES_PATH = os.path.join(DATA_DIR, "overrides.json")

# Fields stored in settings.json (env vars provide defaults).
_KEYS = {
    "tmdb_key": "TMDB_API_KEY",
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
