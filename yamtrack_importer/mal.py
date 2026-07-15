"""Resolve anime titles to MyAnimeList ids.

Yamtrack tracks anime by MAL id (source ``mal``). Crunchyroll (and most anime
services) only give a title, so we match the title to a MAL entry.

Two backends:

* **Official MAL API** (``api.myanimelist.net``) when a **Client ID** is set —
  higher-quality results and generous rate limits. Register an app at
  <https://myanimelist.net/apiconfig> to get a Client ID (no OAuth needed for
  search).
* **Jikan** (``api.jikan.moe``), the free, keyless MAL mirror, used as a
  fallback when no Client ID is configured or the official call comes back empty.

Only successful matches are cached; misses are retried next run.
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
MAL_BASE = "https://api.myanimelist.net/v2"
_MAL_FIELDS = "alternative_titles,num_episodes"


class MALResolver:
    def __init__(
        self,
        cache_path: str = "mal_cache.json",
        overrides_path: str | None = "overrides.json",
        request_delay: float = 0.4,  # Jikan allows ~3 req/s
        client_id: str = "",         # official MAL API Client ID (optional)
    ):
        self.cache_path = cache_path
        self.request_delay = request_delay
        self.client_id = (client_id or "").strip()
        self.cache = self._load(cache_path)
        self.overrides = self._load(overrides_path) if overrides_path else {}
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"

    @property
    def provider(self) -> str:
        return "mal" if self.client_id else "jikan"

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

    # ---- public ----
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

    # ---- lookup (official MAL first, Jikan fallback) ----
    def _lookup(self, title: str) -> dict | None:
        candidates = []
        if self.client_id:
            candidates = self._mal_search(title)
        if not candidates:
            candidates = self._jikan_search(title)
        best = _best_anime_match(title, candidates)
        if not best:
            return {"mal_id": None, "note": "not found"}
        return {
            "mal_id": best["mal_id"],
            "title": best.get("title") or title,
            "episodes": best.get("episodes"),
            "note": "matched by title",
        }

    def _by_id(self, mal_id: int) -> dict:
        if self.client_id:
            got = self._mal_get(f"/anime/{mal_id}", {"fields": "num_episodes"})
            if got:
                return {"title": got.get("title"), "episodes": got.get("num_episodes")}
        got = self._jikan_get(f"/anime/{mal_id}", {})
        info = (got or {}).get("data") or {}
        return {"title": info.get("title"), "episodes": info.get("episodes")}

    # ---- full detail (for the content page) --------------------------
    # Jikan is used even when a Client ID is set: its public payload carries the
    # artwork, synopsis, japanese title and relations the content page needs.
    # Cached under "detail:" keys; the resolution path only reads "anime:" keys.
    def _cached(self, cache_key: str, fetch):
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        data = fetch()
        # Only cache truthy results: an empty list/None means the lookup failed
        # or was rate-limited (Jikan 504s a lot), and we want to retry next time
        # rather than pin a permanent "nothing here".
        if data:
            self.cache[cache_key] = data
            self.save_cache()
        return data

    def anime_detail(self, mal_id: int) -> dict | None:
        return self._cached(
            f"detail:anime:{mal_id}",
            lambda: (self._jikan_get(f"/anime/{mal_id}", {}) or {}).get("data"),
        )

    def anime_recommendations(self, mal_id: int) -> list:
        return self._cached(
            f"detail:anime:{mal_id}:recs",
            lambda: (self._jikan_get(f"/anime/{mal_id}/recommendations", {}) or {}).get("data") or [],
        ) or []

    def anime_episodes(self, mal_id: int) -> list:
        # Jikan paginates episodes; page 1 (up to 100) is enough for the vast
        # majority of anime. Cached so expanding a season is instant next time.
        return self._cached(
            f"detail:anime:{mal_id}:eps",
            lambda: (self._jikan_get(f"/anime/{mal_id}/episodes", {}) or {}).get("data") or [],
        ) or []

    # ---- official MAL API ----
    def _mal_get(self, path: str, params: dict) -> dict | None:
        headers = {"X-MAL-CLIENT-ID": self.client_id}
        for attempt in range(4):
            try:
                resp = self.session.get(f"{MAL_BASE}{path}", params=params,
                                        headers=headers, timeout=30)
            except requests.RequestException:
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", "2")) + 1)
                continue
            if resp.ok:
                time.sleep(self.request_delay)
                return resp.json()
            if resp.status_code in (401, 403):
                logger.warning("MAL API rejected the Client ID (%s); falling back to Jikan.",
                               resp.status_code)
                return None
            time.sleep(0.8)
        return None

    def _mal_search(self, title: str) -> list[dict]:
        q = title.strip()[:64]
        if len(q) < 3:               # MAL search requires >= 3 chars
            return []
        got = self._mal_get("/anime", {"q": q, "limit": 8, "fields": _MAL_FIELDS})
        out = []
        for entry in (got or {}).get("data") or []:
            node = entry.get("node") or {}
            alt = node.get("alternative_titles") or {}
            names = [node.get("title"), alt.get("en"), alt.get("ja")]
            names += alt.get("synonyms") or []
            out.append({
                "mal_id": node.get("id"),
                "title": node.get("title"),
                "episodes": node.get("num_episodes"),
                "titles": [n.strip().lower() for n in names if n],
            })
        return out

    # ---- Jikan ----
    def _jikan_get(self, path: str, params: dict) -> dict | None:
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

    def _jikan_search(self, title: str) -> list[dict]:
        got = self._jikan_get("/anime", {"q": title, "limit": 5})
        out = []
        for item in (got or {}).get("data") or []:
            names = [item.get("title"), item.get("title_english"), item.get("title_japanese")]
            for t in item.get("titles") or []:
                names.append(t.get("title"))
            out.append({
                "mal_id": item.get("mal_id"),
                "title": item.get("title"),
                "episodes": item.get("episodes"),
                "titles": [n.strip().lower() for n in names if n],
            })
        return out


def _best_anime_match(title: str, candidates: list[dict]):
    """Pick the best candidate (normalized {mal_id,title,episodes,titles})."""
    candidates = [c for c in candidates if c.get("mal_id")]
    if not candidates:
        return None
    target = title.strip().lower()

    def ratio(c: dict) -> float:
        return max((SequenceMatcher(None, target, n).ratio() for n in c.get("titles") or []),
                   default=0.0)

    best = max(candidates, key=ratio)
    return best if ratio(best) >= 0.6 else None
