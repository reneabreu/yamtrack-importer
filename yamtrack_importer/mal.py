"""Resolve anime titles to MyAnimeList ids via the free Jikan API.

Yamtrack tracks anime by MAL id (source ``mal``). Crunchyroll (and most anime
services) only give a title, so we match the title to a MAL entry. No API key
is needed. Only successful matches are cached; misses are retried next run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from difflib import SequenceMatcher

import requests

logger = logging.getLogger(__name__)

JIKAN_BASE = "https://api.jikan.moe/v4"


class MALResolver:
    def __init__(
        self,
        cache_path: str = "mal_cache.json",
        overrides_path: str | None = "overrides.json",
        request_delay: float = 0.4,  # Jikan allows ~3 req/s
    ):
        self.cache_path = cache_path
        self.request_delay = request_delay
        self.cache = self._load(cache_path)
        self.overrides = self._load(overrides_path) if overrides_path else {}
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"

    @staticmethod
    def _load(path: str | None) -> dict:
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def save_cache(self) -> None:
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.cache, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cache_path)

    def _get(self, path: str, params: dict) -> dict | None:
        for attempt in range(4):
            try:
                resp = self.session.get(f"{JIKAN_BASE}{path}", params=params, timeout=30)
            except requests.RequestException:
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", "2")) + 1)
                continue
            if resp.ok:
                time.sleep(self.request_delay)
                return resp.json()
            time.sleep(1.0)
        return None

    def resolve_anime_by_title(self, title: str) -> dict | None:
        """Resolve an anime title to MAL data. Returns {mal_id, title, episodes,
        note} (episodes filled even for bare-id overrides) or a miss dict."""
        override = self.overrides.get(f"anime:{title.lower()}")
        cache_key = f"anime:{title.lower()}"
        data = override or self.cache.get(cache_key)
        if not (data and data.get("mal_id")):
            if override:
                data = override
            else:
                data = self._lookup(title)
                if data and data.get("mal_id"):
                    self.cache[cache_key] = data
                else:
                    self.cache.pop(cache_key, None)
        if data and data.get("mal_id") and "episodes" not in data:
            data = {**data, **self._by_id(int(data["mal_id"]))}
        return data

    def _by_id(self, mal_id: int) -> dict:
        got = self._get(f"/anime/{mal_id}", {})
        info = (got or {}).get("data") or {}
        return {"title": info.get("title"), "episodes": info.get("episodes")}

    def _lookup(self, title: str) -> dict | None:
        search = self._get("/anime", {"q": title, "limit": 5})
        results = (search or {}).get("data") or []
        best = _best_anime_match(title, results)
        if not best:
            return {"mal_id": None, "note": "not found"}
        return {
            "mal_id": best["mal_id"],
            "title": best.get("title") or title,
            "episodes": best.get("episodes"),
            "note": "matched by title",
        }


def _candidate_titles(item: dict) -> list[str]:
    names = [item.get("title"), item.get("title_english"), item.get("title_japanese")]
    for t in item.get("titles") or []:
        names.append(t.get("title"))
    return [n.strip().lower() for n in names if n]


def _best_anime_match(title: str, results: list[dict]):
    if not results:
        return None
    target = title.strip().lower()

    def ratio(item: dict) -> float:
        return max((SequenceMatcher(None, target, n).ratio() for n in _candidate_titles(item)),
                   default=0.0)

    best = max(results, key=ratio)
    return best if ratio(best) >= 0.6 else None
