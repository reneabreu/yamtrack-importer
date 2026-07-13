"""Identity + smart auto-merge for the local library.

Two runs (say TV Time and Crunchyroll) can describe the same title. ``identity``
gives each item a stable key so those land on the same library row, and
``merge_items`` folds an incoming item into the one already stored without ever
losing watch data — union of episodes, highest progress/score, widest date
range, and the union of provenance sources.
"""

from __future__ import annotations

import re

from .model import EpisodeWatch, MediaItem, MediaType, Status

# Which id uniquely identifies a title, per media type, best-first. The library
# is destination-agnostic, so we key on the canonical provider ids that
# resolution fills in (TMDB for screen media, MAL for anime).
_ID_PRIORITY: dict[MediaType, list[str]] = {
    MediaType.ANIME: ["mal", "tmdb", "tvdb"],
    MediaType.TV: ["tmdb", "tvdb"],
    MediaType.MOVIE: ["tmdb"],
    MediaType.MANGA: ["mal", "anilist"],
    MediaType.GAME: ["igdb"],
    MediaType.BOOK: ["openlibrary", "isbn"],
}

# Higher wins when two sources disagree on status.
_STATUS_RANK = {
    Status.COMPLETED: 5,
    Status.IN_PROGRESS: 4,
    Status.PAUSED: 3,
    Status.DROPPED: 2,
    Status.PLANNING: 1,
}


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def identity(item: MediaItem) -> str:
    """Stable dedup key. Prefers a canonical external id; falls back to title."""
    mt = item.media_type
    for provider in _ID_PRIORITY.get(mt, []):
        val = item.ids.get(provider)
        if val:
            return f"{mt.value}:{provider}:{val}"
    year = item.year or ""
    return f"{mt.value}:title:{_norm_title(item.title)}|{year}"


def _pick_status(a: Status, b: Status) -> Status:
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


def _min_dt(a, b):
    vals = [d for d in (a, b) if d]
    return min(vals) if vals else None


def _max_dt(a, b):
    vals = [d for d in (a, b) if d]
    return max(vals) if vals else None


def _merge_episodes(a: list[EpisodeWatch], b: list[EpisodeWatch]) -> list[EpisodeWatch]:
    by_key: dict[tuple[int, int], EpisodeWatch] = {}
    for e in a + b:
        key = (e.season, e.number)
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = EpisodeWatch(e.season, e.number, e.watched_at, e.repeats)
        else:
            # keep the earliest first-watch date and the higher rewatch count
            cur.watched_at = _min_dt(cur.watched_at, e.watched_at)
            cur.repeats = max(cur.repeats, e.repeats)
    return [by_key[k] for k in sorted(by_key)]


def merge_items(existing: MediaItem, incoming: MediaItem) -> MediaItem:
    """Fold ``incoming`` into ``existing`` in place and return it.

    Never discards watch history: episodes are unioned, progress/score/dates are
    widened, and ids/sources are combined. ``existing`` is treated as the row
    already in the library.
    """
    # ids: keep everything known from either side (existing wins on conflict).
    for k, v in incoming.ids.items():
        existing.ids.setdefault(k, v)

    existing.episodes = _merge_episodes(existing.episodes, incoming.episodes)

    # flat progress / totals
    progs = [p for p in (existing.progress, incoming.progress) if p is not None]
    existing.progress = max(progs) if progs else None
    if incoming.total and (not existing.total or incoming.total > existing.total):
        existing.total = incoming.total
    existing.repeats = max(existing.repeats, incoming.repeats)

    # scores: prefer a real score; if both, keep the higher
    scores = [s for s in (existing.score, incoming.score) if s is not None]
    existing.score = max(scores) if scores else None

    existing.status = _pick_status(existing.status, incoming.status)
    existing.started_at = _min_dt(existing.started_at, incoming.started_at)
    existing.completed_at = _max_dt(existing.completed_at, incoming.completed_at)
    existing.last_activity = _max_dt(existing.last_activity, incoming.last_activity)
    existing.favorite = existing.favorite or incoming.favorite
    existing.notes = existing.notes or incoming.notes

    if incoming.season_totals:
        merged = dict(existing.season_totals)
        merged.update(incoming.season_totals)
        existing.season_totals = merged
    if not existing.title and incoming.title:
        existing.title = incoming.title
    if not existing.year and incoming.year:
        existing.year = incoming.year
    existing.resolved = existing.resolved or incoming.resolved

    # provenance: union of source ids the data came from
    existing.sources = sorted(set(existing.sources) | set(incoming.sources))
    return existing
