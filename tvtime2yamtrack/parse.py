"""Parse a TV Time GDPR export into normalized records.

The GDPR export is a directory of CSV files. The files we use:

* ``tracking-prod-records-v2.csv`` – per-episode watch history. ``s_id`` is the
  TheTVDB series id, plus ``season_number`` / ``episode_number`` and a
  ``created_at`` timestamp per watch. Rows whose ``key`` starts with
  ``rewatch-episode`` are additional watches of an already-seen episode.
* ``tracking-prod-records.csv`` – legacy records, the only place movies appear.
  ``entity_type == "movie"`` rows carry ``movie_name`` + ``release_date`` and a
  ``type`` of ``watch`` / ``rewatch`` (seen) or ``towatch`` (watchlist). Movies
  have **no** external id, so they are matched to TMDB by title + year.
* ``followed_tv_show.csv`` – shows the user follows (TheTVDB ids).
* ``user_show_special_status.csv`` – ``for_later`` = show-level watchlist.
* ``tv_show_rate.csv`` – show ratings on a 1-5 scale.

Movie "ratings" in the export are TV Time emotion votes (an emotion id, not a
numeric score) and are intentionally not imported.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime

from .models import EpisodeWatch, MovieRecord, ShowRecord

logger = logging.getLogger(__name__)

# Allow very large fields (some export rows embed big blobs).
csv.field_size_limit(10_000_000)

TRUE_VALUES = {"true", "1", "t", "yes"}


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        logger.warning("Missing export file: %s", os.path.basename(path))
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def _parse_dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _release_year(value: str | None) -> int | None:
    dt = _parse_dt(value)
    if dt and dt.year > 1900:  # TV Time uses 0001-01-01 as "unknown".
        return dt.year
    return None


def parse_shows(export_dir: str) -> dict[str, ShowRecord]:
    """Return shows keyed by a stable id (TheTVDB id when available)."""
    shows: dict[str, ShowRecord] = {}

    def get_show(tvdb_id: str | None, name: str) -> ShowRecord:
        key = (tvdb_id or "").strip() or f"name:{name.strip().lower()}"
        rec = shows.get(key)
        if rec is None:
            rec = ShowRecord(tvdb_id=(tvdb_id or "").strip() or None, name=name.strip())
            shows[key] = rec
        elif name and not rec.name:
            rec.name = name.strip()
        return rec

    # --- Episode watch history (main source) ---
    for row in _read(os.path.join(export_dir, "tracking-prod-records-v2.csv")):
        series_name = (row.get("series_name") or "").strip()
        if not series_name:
            continue  # "user" follow rows and misc entries have no series_name
        season = _parse_int(row.get("season_number"))
        episode = _parse_int(row.get("episode_number"))
        rec = get_show(row.get("s_id"), series_name)

        if _truthy(row.get("is_followed")):
            rec.followed = True
        if _truthy(row.get("is_archived")):
            rec.archived = True
        if _truthy(row.get("is_for_later")):
            rec.for_later = True

        if season is None or episode is None:
            continue

        watched_at = _parse_dt(row.get("created_at"))
        ep_key = (season, episode)
        ep = rec.episodes.get(ep_key)
        if ep is None:
            ep = EpisodeWatch(season_number=season, episode_number=episode)
            rec.episodes[ep_key] = ep
        # Track most-recent watch time.
        if watched_at and (ep.last_watched is None or watched_at > ep.last_watched):
            ep.last_watched = watched_at
        # Count total watch rows; convert to "repeats" (extra watches) later.
        ep.repeats += 1

    # Convert raw watch counts into "extra watches beyond the first".
    for rec in shows.values():
        for ep in rec.episodes.values():
            ep.repeats = max(0, ep.repeats - 1)

    # --- Followed shows (adds shows even if not in episode history) ---
    for row in _read(os.path.join(export_dir, "followed_tv_show.csv")):
        name = (row.get("tv_show_name") or "").strip()
        if not name:
            continue
        rec = get_show(row.get("tv_show_id"), name)
        rec.followed = True
        if _truthy(row.get("archived")):
            rec.archived = True

    # --- Show-level watchlist (for_later) ---
    for row in _read(os.path.join(export_dir, "user_show_special_status.csv")):
        name = (row.get("tv_show_name") or "").strip()
        if not name:
            continue
        rec = get_show(row.get("tv_show_id"), name)
        if (row.get("status") or "").strip().lower() == "for_later":
            rec.for_later = True

    # --- Show ratings (1-5 -> 0-10) ---
    for row in _read(os.path.join(export_dir, "tv_show_rate.csv")):
        name = (row.get("tv_show_name") or "").strip()
        rating = _parse_int(row.get("rating"))
        if not name or rating is None:
            continue
        rec = get_show(row.get("tv_show_id"), name)
        rec.score = round(min(10.0, rating * 2.0), 1)

    logger.info("Parsed %d shows", len(shows))
    return shows


def parse_movies(export_dir: str) -> dict[str, MovieRecord]:
    """Return movies keyed by normalized name.

    Movies are keyed by name only, not name+year: TV Time's ``follow`` rows
    frequently carry a placeholder release date (``0001-01-01``) while the
    matching ``watch`` row has the real one, so keying on year would split a
    single movie into duplicates. The best (non-placeholder) year seen wins.
    """
    movies: dict[str, MovieRecord] = {}

    for row in _read(os.path.join(export_dir, "tracking-prod-records.csv")):
        if (row.get("entity_type") or "").strip() != "movie":
            continue
        name = (row.get("movie_name") or "").strip()
        if not name:
            continue
        year = _release_year(row.get("release_date"))
        key = name.lower()
        rec = movies.get(key)
        if rec is None:
            rec = MovieRecord(name=name, year=year)
            movies[key] = rec
        elif year and not rec.year:
            rec.year = year

        rtype = (row.get("type") or "").strip().lower()
        watched_at = _parse_dt(row.get("updated_at")) or _parse_dt(row.get("created_at"))
        runtime = _parse_int(row.get("runtime"))
        if runtime:
            rec.runtime_seconds = runtime

        if rtype in ("watch", "rewatch"):
            rec.watched = True
            if rtype == "rewatch":
                rec.repeats += 1
            if watched_at and (rec.last_watched is None or watched_at > rec.last_watched):
                rec.last_watched = watched_at
        elif rtype == "towatch":
            rec.watchlist = True
        # "follow" rows are metadata only; ignore.

    logger.info("Parsed %d movies", len(movies))
    return movies
