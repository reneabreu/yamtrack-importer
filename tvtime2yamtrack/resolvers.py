"""Resolver factory keyed by Yamtrack metadata provider.

Only TMDB is implemented today (covers TV Time). Game sources will need an IGDB
resolver, manga/book sources an Open Library / MangaUpdates resolver, etc.
"""

from __future__ import annotations

import os

from .mal import MALResolver
from .resolve import TMDBResolver


def get_resolver(provider: str, settings: dict, cache_path: str, overrides_path: str):
    if provider == "tmdb":
        key = settings.get("tmdb_key", "")
        if not key:
            raise ValueError("A TMDB API key is required. Set it on the Settings page.")
        return TMDBResolver(
            api_key=key, cache_path=cache_path, overrides_path=overrides_path
        )
    if provider == "mal":
        # Jikan needs no key. Keep a separate cache file next to the TMDB one.
        mal_cache = os.path.join(os.path.dirname(cache_path) or ".", "mal_cache.json")
        return MALResolver(cache_path=mal_cache, overrides_path=overrides_path)
    raise NotImplementedError(
        f"No resolver for provider '{provider}' yet. "
        "This source is on the roadmap."
    )
