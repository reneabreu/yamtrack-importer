"""Turn resolved shows/movies into flat Yamtrack rows (shared by CSV + API).

A Yamtrack row is a dict with the native import column names:

    media_id, source, media_type, title, image, season_number, episode_number,
    score, progress, status, start_date, end_date, notes, progressed_at, repeats

The same rows feed both the CSV writer and the API pusher.
"""

from __future__ import annotations

from datetime import datetime

from .models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PLANNING,
    AnimeRecord,
    MovieRecord,
    ShowRecord,
)

SOURCE_TMDB = "tmdb"


def _fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _fmt_ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def _season_status(watched: int, total: int | None) -> str:
    if total and watched >= total:
        return STATUS_COMPLETED
    return STATUS_IN_PROGRESS


def _show_status(show: ShowRecord) -> str:
    if show.total_episodes and show.watched_episode_count >= show.total_episodes:
        return STATUS_COMPLETED
    return STATUS_IN_PROGRESS


def _row(**kw) -> dict:
    base = {
        "media_id": "",
        "source": SOURCE_TMDB,
        "media_type": "",
        "title": "",
        "image": "",
        "season_number": "",
        "episode_number": "",
        "score": "",
        "progress": "",
        "status": "",
        "start_date": "",
        "end_date": "",
        "notes": "",
        "progressed_at": "",
        "repeats": "",
    }
    base.update(kw)
    return base


def rows_for_show(show: ShowRecord) -> list[dict]:
    """Emit tv + season + episode rows for a resolved, watched show."""
    if not show.tmdb_id or not show.episodes:
        return []

    rows: list[dict] = []
    mid = str(show.tmdb_id)
    title = show.tmdb_title or show.name

    # Parent TV row (carries the show score / overall status).
    rows.append(
        _row(
            media_id=mid,
            media_type="tv",
            title=title,
            status=_show_status(show),
            score=show.score if show.score is not None else "",
        )
    )

    # Season rows.
    watch_dates = [ep.last_watched for ep in show.episodes.values() if ep.last_watched]
    for season in show.watched_seasons:
        watched = show.watched_in_season(season)
        total = show.season_episode_counts.get(season)
        rows.append(
            _row(
                media_id=mid,
                media_type="season",
                title=title,
                season_number=season,
                progress=watched,
                status=_season_status(watched, total),
            )
        )

    # Episode rows.
    for (season, episode), ep in sorted(show.episodes.items()):
        rows.append(
            _row(
                media_id=mid,
                media_type="episode",
                title=title,
                season_number=season,
                episode_number=episode,
                end_date=_fmt_date(ep.last_watched),
                progressed_at=_fmt_ts(ep.last_watched),
                repeats=ep.repeats or "",
            )
        )
    return rows


def rows_for_show_watchlist(show: ShowRecord) -> list[dict]:
    """A followed/for-later show with no watch history -> Planning."""
    if not show.tmdb_id:
        return []
    return [
        _row(
            media_id=str(show.tmdb_id),
            media_type="tv",
            title=show.tmdb_title or show.name,
            status=STATUS_PLANNING,
            score=show.score if show.score is not None else "",
        )
    ]


def rows_for_show_bare(show: ShowRecord) -> list[dict]:
    """A watched show whose episodes couldn't be mapped to TMDB numbering.

    Emit just the parent TV row (In progress) so the show still lands in the
    library, without episode rows that would 404 against TMDB.
    """
    if not show.tmdb_id:
        return []
    return [
        _row(
            media_id=str(show.tmdb_id),
            media_type="tv",
            title=show.tmdb_title or show.name,
            status=STATUS_IN_PROGRESS,
            score=show.score if show.score is not None else "",
        )
    ]


def rows_for_movie(movie: MovieRecord) -> list[dict]:
    if not movie.tmdb_id:
        return []
    if movie.watched:
        return [
            _row(
                media_id=str(movie.tmdb_id),
                media_type="movie",
                title=movie.tmdb_title or movie.name,
                status=STATUS_COMPLETED,
                progress=1,
                score=movie.score if movie.score is not None else "",
                end_date=_fmt_date(movie.last_watched),
                progressed_at=_fmt_ts(movie.last_watched),
                repeats=movie.repeats or "",
            )
        ]
    if movie.watchlist:
        return [
            _row(
                media_id=str(movie.tmdb_id),
                media_type="movie",
                title=movie.tmdb_title or movie.name,
                status=STATUS_PLANNING,
                score=movie.score if movie.score is not None else "",
            )
        ]
    return []


def rows_for_anime(anime: AnimeRecord) -> list[dict]:
    """One 'anime' row (source mal). If unresolved, leave media_id blank and let
    Yamtrack match by title on import."""
    return [
        _row(
            media_id=str(anime.mal_id) if anime.mal_id else "",
            source="mal",
            media_type="anime",
            title=anime.mal_title or anime.title,
            status=anime.status,
            progress=anime.progress or "",
            score=anime.score if anime.score is not None else "",
            start_date=_fmt_date(anime.start_date),
            end_date=_fmt_date(anime.end_date),
            progressed_at=_fmt_ts(anime.end_date or anime.start_date),
        )
    ]


CSV_COLUMNS = [
    "media_id",
    "source",
    "media_type",
    "title",
    "image",
    "season_number",
    "episode_number",
    "score",
    "progress",
    "status",
    "start_date",
    "end_date",
    "notes",
    "progressed_at",
]
