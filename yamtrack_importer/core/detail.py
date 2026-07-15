"""Rich per-title metadata for the content page.

The library stores only the canonical ``MediaItem`` (status, progress, watched
episodes). The content page needs artwork, synopsis, the original-language
title, a season/episode breakdown, and related titles — all of which live in
TMDB (screen media) and MyAnimeList/Jikan (anime).

This module is the seam: provider-specific ``normalize_*`` functions turn raw
API JSON into one neutral shape, and ``get_detail`` / ``get_season_episodes``
pick the right provider for a given item. The normalizers are pure (raw JSON +
``MediaItem`` in, dict out) so they test without any network.
"""

from __future__ import annotations

from .model import MediaItem, MediaType

TMDB_IMG = "https://image.tmdb.org/t/p/w500"


def _tmdb_img(path: str | None) -> str | None:
    return f"{TMDB_IMG}{path}" if path else None


def _year(datestr: str | None) -> int | None:
    if datestr and len(datestr) >= 4 and datestr[:4].isdigit():
        return int(datestr[:4])
    return None


# ---- normalizers (pure) ---------------------------------------------------

def normalize_tv(raw: dict, item: MediaItem | None) -> dict:
    recs = ((raw.get("recommendations") or {}).get("results")) or []
    seasons = []
    for s in raw.get("seasons") or []:
        n = s.get("season_number")
        if n is None:
            continue
        seasons.append({
            "number": n,
            "name": s.get("name") or (f"Season {n}" if n else "Specials"),
            "episode_count": s.get("episode_count") or 0,
            "watched": item.episodes_in_season(n) if item else 0,
        })
    return {
        "kind": "tv",
        "provider": "tmdb",
        "cover": _tmdb_img(raw.get("poster_path")),
        "name": raw.get("name") or (item.title if item else ""),
        "original_name": raw.get("original_name"),
        "description": raw.get("overview") or "",
        "year": _year(raw.get("first_air_date")),
        "provider_url": f"https://www.themoviedb.org/tv/{raw.get('id')}",
        "seasons": seasons,
        "episodes_total": raw.get("number_of_episodes"),
        "watched_total": item.watched_episodes if item else 0,
        "related": [
            {"name": r.get("name"), "cover": _tmdb_img(r.get("poster_path")),
             "url": f"https://www.themoviedb.org/tv/{r.get('id')}"}
            for r in recs[:12] if r.get("name")
        ],
    }


def normalize_movie(raw: dict, item: MediaItem | None) -> dict:
    recs = ((raw.get("recommendations") or {}).get("results")) or []
    return {
        "kind": "movie",
        "provider": "tmdb",
        "cover": _tmdb_img(raw.get("poster_path")),
        "name": raw.get("title") or (item.title if item else ""),
        "original_name": raw.get("original_title"),
        "description": raw.get("overview") or "",
        "year": _year(raw.get("release_date")),
        "provider_url": f"https://www.themoviedb.org/movie/{raw.get('id')}",
        "seasons": [],
        "episodes_total": None,
        "watched_total": 0,
        "related": [
            {"name": r.get("title"), "cover": _tmdb_img(r.get("poster_path")),
             "url": f"https://www.themoviedb.org/movie/{r.get('id')}"}
            for r in recs[:12] if r.get("title")
        ],
    }


def normalize_anime(raw: dict, recs: list, item: MediaItem | None) -> dict:
    total = raw.get("episodes")
    watched = 0
    if item:
        watched = item.watched_episodes if item.episodes else (item.progress or 0)
    imgs = (raw.get("images") or {}).get("jpg") or {}
    seasons = []
    if total:
        seasons = [{
            "number": 1, "name": "Episodes",
            "episode_count": total, "watched": min(watched, total),
        }]
    return {
        "kind": "anime",
        "provider": "mal",
        "cover": imgs.get("large_image_url") or imgs.get("image_url"),
        "name": raw.get("title") or (item.title if item else ""),
        "original_name": raw.get("title_japanese"),
        "description": raw.get("synopsis") or "",
        "year": raw.get("year") or _year((raw.get("aired") or {}).get("from")),
        "provider_url": raw.get("url") or f"https://myanimelist.net/anime/{raw.get('mal_id')}",
        "seasons": seasons,
        "episodes_total": total,
        "watched_total": watched,
        "related": [
            {"name": (r.get("entry") or {}).get("title"),
             "cover": (((r.get("entry") or {}).get("images") or {}).get("jpg") or {}).get("image_url"),
             "url": (r.get("entry") or {}).get("url")}
            for r in (recs or [])[:12] if (r.get("entry") or {}).get("title")
        ],
    }


def watched_numbers(item: MediaItem, season: int) -> set[int]:
    """Episode numbers the user has watched in a season.

    Falls back to a 1..progress range for flat anime that track only progress.
    """
    nums = {e.number for e in item.episodes if e.season == season}
    if not nums and item.media_type == MediaType.ANIME and item.progress:
        nums = set(range(1, item.progress + 1))
    return nums


# ---- orchestration (picks a provider) -------------------------------------

def get_detail(item: MediaItem, providers: dict):
    """Return (normalized_detail, error). Exactly one is non-None."""
    ids = item.ids
    if item.media_type == MediaType.ANIME and ids.get("mal"):
        mal = providers.get("mal")
        if not mal:
            return None, "MyAnimeList lookups are unavailable."
        raw = mal.anime_detail(int(ids["mal"]))
        if not raw:
            return None, "Couldn't load details from MyAnimeList right now — try again shortly."
        recs = mal.anime_recommendations(int(ids["mal"]))
        return normalize_anime(raw, recs, item), None

    if item.media_type in (MediaType.TV, MediaType.ANIME) and ids.get("tmdb"):
        tmdb = providers.get("tmdb")
        if not tmdb:
            return None, "Add a TMDB API key on the Settings page to load details for this title."
        raw = tmdb.tv_detail(int(ids["tmdb"]))
        if not raw:
            return None, "Couldn't load details from TMDB."
        return normalize_tv(raw, item), None

    if item.media_type == MediaType.MOVIE and ids.get("tmdb"):
        tmdb = providers.get("tmdb")
        if not tmdb:
            return None, "Add a TMDB API key on the Settings page to load details for this title."
        raw = tmdb.movie_detail(int(ids["tmdb"]))
        if not raw:
            return None, "Couldn't load details from TMDB."
        return normalize_movie(raw, item), None

    return None, "This title has no TMDB or MyAnimeList id yet, so there's nothing to look up."


def get_season_episodes(item: MediaItem, providers: dict, season: int) -> list:
    """Full episode list for one season, each flagged watched or not (lazy)."""
    ids = item.ids
    watched = watched_numbers(item, season)

    if item.media_type == MediaType.ANIME and ids.get("mal"):
        mal = providers.get("mal")
        eps = mal.anime_episodes(int(ids["mal"])) if mal else []
        return [
            {"number": e.get("mal_id"), "title": e.get("title"),
             "aired": (e.get("aired") or "")[:10],
             "watched": e.get("mal_id") in watched}
            for e in eps
        ]

    tmdb = providers.get("tmdb")
    if tmdb and ids.get("tmdb"):
        data = tmdb.tv_season(int(ids["tmdb"]), season) or {}
        return [
            {"number": e.get("episode_number"), "title": e.get("name"),
             "aired": e.get("air_date") or "",
             "watched": e.get("episode_number") in watched}
            for e in (data.get("episodes") or [])
        ]

    return []
