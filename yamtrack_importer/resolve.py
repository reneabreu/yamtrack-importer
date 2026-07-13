"""Resolve TV Time items to TMDB ids (the source Yamtrack uses for TV/movies).

Shows carry a TheTVDB series id, which maps cleanly to TMDB via the ``/find``
endpoint. Movies carry only a title (and often a year), so they are matched by
a title+year search.

Everything is cached to a JSON file so re-runs are fast and free, and any item
can be pinned or corrected through a manual-overrides file.
"""

from __future__ import annotations

import json
import logging
import os
import time
from difflib import SequenceMatcher

import requests

from .models import MovieRecord, ShowRecord

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"


class TMDBResolver:
    def __init__(
        self,
        api_key: str,
        cache_path: str = "tmdb_cache.json",
        overrides_path: str | None = "overrides.json",
        request_delay: float = 0.25,
    ):
        if not api_key:
            raise ValueError("A TMDB API key (v3) or read access token (v4) is required.")
        self.api_key = api_key
        self.cache_path = cache_path
        self.overrides_path = overrides_path
        self.request_delay = request_delay
        self.cache: dict = self._load_json(cache_path)
        self.overrides: dict = self._load_json(overrides_path) if overrides_path else {}
        self.session = requests.Session()
        # A v4 token is a long JWT-like string; a v3 key is 32 hex chars.
        if len(api_key) > 40:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
            self._auth_params: dict = {}
        else:
            self._auth_params = {"api_key": api_key}

    # ---- persistence -------------------------------------------------
    @staticmethod
    def _load_json(path: str | None) -> dict:
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                logger.warning("Could not read %s; starting fresh", path)
        return {}

    def save_cache(self) -> None:
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.cache, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cache_path)

    # ---- HTTP --------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict | None:
        url = f"{TMDB_BASE}{path}"
        merged = dict(self._auth_params)
        if params:
            merged.update(params)
        for attempt in range(4):
            try:
                resp = self.session.get(url, params=merged, timeout=30)
            except requests.RequestException as exc:
                logger.warning("Network error on %s: %s", path, exc)
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 429:  # rate limited
                wait = int(resp.headers.get("Retry-After", "2"))
                time.sleep(wait + 1)
                continue
            if resp.status_code == 401:
                raise RuntimeError("TMDB rejected the API key (HTTP 401).")
            if resp.status_code == 404:
                return None
            if resp.ok:
                time.sleep(self.request_delay)
                return resp.json()
            logger.warning("TMDB %s -> HTTP %s", path, resp.status_code)
            time.sleep(1.0)
        return None

    def _resolve(self, cache_key, override, lookup, needs_refresh=None):
        """Return match data. Only *successful* matches are cached; misses are
        re-attempted on every run so improvements/new TMDB entries get picked up.
        A user override always wins and never triggers a lookup. ``needs_refresh``
        can force a re-lookup of an otherwise-valid cached hit (e.g. to enrich
        older cache entries that predate a new field).
        """
        if override:
            return override
        cached = self.cache.get(cache_key)
        if cached and cached.get("tmdb_id") and not (needs_refresh and needs_refresh(cached)):
            return cached
        data = lookup()
        if data and data.get("tmdb_id"):
            self.cache[cache_key] = data          # persist hits only
        else:
            self.cache.pop(cache_key, None)        # drop any stale cached miss
        return data

    # ---- shows (primitive) -------------------------------------------
    def resolve_tv(self, tvdb_id, name: str) -> dict | None:
        """Resolve a TV title to TMDB data by TheTVDB id (or title). Returns the
        enriched dict {tmdb_id, title, total_episodes, season_episode_counts,
        is_anime, note} or a miss dict."""
        override = self.overrides.get(f"tv:{tvdb_id}") or self.overrides.get(
            f"tvname:{name.lower()}"
        )
        cache_key = f"tv:{tvdb_id or name.lower()}"
        data = self._resolve(
            cache_key, override, lambda: self._lookup_tv(tvdb_id, name),
            needs_refresh=lambda d: "is_anime" not in d,  # enrich pre-anime cache
        )
        # A manual override may only carry an id — enrich it with real TMDB data.
        if data and data.get("tmdb_id") and "season_episode_counts" not in data:
            enriched = self._tv_details(int(data["tmdb_id"]), data.get("title") or name,
                                        "manual override")
            if data.get("title"):
                enriched["title"] = data["title"]
            data = enriched
        return data

    def resolve_show(self, show: ShowRecord) -> None:
        data = self.resolve_tv(show.tvdb_id, show.name)
        if not data or not data.get("tmdb_id"):
            show.resolve_note = (data or {}).get("note", "not found")
            return
        show.tmdb_id = int(data["tmdb_id"])
        show.tmdb_title = data.get("title")
        show.total_episodes = data.get("total_episodes")
        show.is_anime = bool(data.get("is_anime", False))
        show.season_episode_counts = {
            int(k): int(v) for k, v in (data.get("season_episode_counts") or {}).items()
        }
        show.resolve_note = data.get("note", "")

    def _lookup_tv(self, tvdb_id, name: str) -> dict | None:
        tmdb_id = None
        note = ""
        if tvdb_id:
            found = self._get(f"/find/{tvdb_id}", {"external_source": "tvdb_id"})
            results = (found or {}).get("tv_results") or []
            if results:
                tmdb_id = results[0]["id"]
                note = "matched by tvdb_id"
        if tmdb_id is None:
            search = self._get("/search/tv", {"query": name})
            results = (search or {}).get("results") or []
            best = _best_title_match(name, results, "name", "original_name")
            if best:
                tmdb_id = best["id"]
                note = "matched by title search"
        if tmdb_id is None:
            return {"tmdb_id": None, "note": "not found"}
        return self._tv_details(tmdb_id, name, note)

    def _tv_details(self, tmdb_id: int, fallback_title: str, note: str) -> dict:
        """Fetch a TMDB show's season structure + anime flag by id."""
        details = self._get(f"/tv/{tmdb_id}") or {}
        season_counts = {
            str(s["season_number"]): s.get("episode_count", 0)
            for s in details.get("seasons", [])
        }
        genre_ids = {g.get("id") for g in details.get("genres", [])}
        origin = set(details.get("origin_country") or [])
        is_anime = (16 in genre_ids) and (
            details.get("original_language") == "ja" or "JP" in origin
        )
        return {
            "tmdb_id": tmdb_id,
            "title": details.get("name") or fallback_title,
            "total_episodes": details.get("number_of_episodes"),
            "season_episode_counts": season_counts,
            "is_anime": is_anime,
            "note": note,
        }

    # ---- movies (primitive) ------------------------------------------
    def resolve_movie_by_title(self, title: str, year) -> dict | None:
        """Resolve a movie to TMDB data by title (+ year). Returns
        {tmdb_id, title, note} or a miss dict."""
        override = self.overrides.get(f"movie:{title.lower()}|{year or ''}")
        cache_key = f"movie:{title.lower()}|{year or ''}"
        return self._resolve(cache_key, override, lambda: self._lookup_movie_by(title, year))

    def resolve_movie(self, movie: MovieRecord) -> None:
        data = self.resolve_movie_by_title(movie.name, movie.year)
        if not data or not data.get("tmdb_id"):
            movie.resolve_note = (data or {}).get("note", "not found")
            return
        movie.tmdb_id = int(data["tmdb_id"])
        movie.tmdb_title = data.get("title")
        movie.resolve_note = data.get("note", "")

    def _lookup_movie_by(self, title: str, year) -> dict | None:
        params = {"query": title}
        if year:
            params["year"] = year
        search = self._get("/search/movie", params)
        results = (search or {}).get("results") or []
        if not results and year:
            search = self._get("/search/movie", {"query": title})
            results = (search or {}).get("results") or []
        best = _best_title_match(title, results, "title", "original_title", year=year)
        if not best:
            return {"tmdb_id": None, "note": "not found"}
        return {
            "tmdb_id": best["id"],
            "title": best.get("title") or title,
            "note": "matched by title search",
        }


def _best_title_match(
    name: str, results: list[dict], key: str, alt_key: str, year: int | None = None
):
    """Pick the closest result.

    Compares the query against both the localized title (``key``) and the
    original-language title (``alt_key``) — crucial for foreign films, where
    TV Time stores the native title but TMDB's primary title is translated.
    A candidate is accepted when its best title similarity is high, or when the
    release year matches (TMDB already fuzzy-matched the query, so a year match
    is a strong confirmation).
    """
    if not results:
        return None
    target = name.strip().lower()

    def ratio(item: dict) -> float:
        best = 0.0
        for field in (key, alt_key):
            value = (item.get(field) or "").strip().lower()
            if value:
                best = max(best, SequenceMatcher(None, target, value).ratio())
        return best

    def year_match(item: dict) -> bool:
        if not year:
            return False
        date = item.get("release_date") or item.get("first_air_date") or ""
        return date.startswith(str(year))

    def sort_key(item: dict) -> tuple:
        return (year_match(item), round(ratio(item), 3), item.get("popularity", 0))

    best = max(results, key=sort_key)
    if ratio(best) >= 0.6 or (year and year_match(best)):
        return best
    return None
