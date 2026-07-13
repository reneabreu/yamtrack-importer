"""Yamtrack export destination: canonical MediaItems -> Yamtrack import CSV.

Yamtrack has no media-create REST API; its bulk-import path is the CSV upload
(Settings → Import), which is also the only one that preserves progress,
status, score, rewatches, and real dates. So this is a file-only destination.
"""

from __future__ import annotations

from ..core.model import MediaItem, MediaType, Status
from ..core.resolve_service import status_label
from ._rows import fmt_date as _fmt_date
from ._rows import fmt_ts as _fmt_ts
from ._rows import row as _row
from ._rows import summarize_rows, write_csv
from .base import Exporter, ExporterInfo


class YamtrackExporter(Exporter):
    info = ExporterInfo(
        id="yamtrack",
        label="Yamtrack",
        modes=["file"],
        media_types=["tv", "movie", "anime"],
        requires={"tv": "tmdb", "movie": "tmdb", "anime": "mal"},
        output_ext="csv",
        output_mime="text/csv",
        file_hint="Upload via Yamtrack → Settings → Import",
    )

    def details(self, records):
        return summarize_rows(records)

    # ---- canonical -> Yamtrack rows ----
    def build(self, items: list[MediaItem]) -> list[dict]:
        rows: list[dict] = []
        for it in items:
            if it.media_type == MediaType.MOVIE:
                rows += self._movie_rows(it)
            elif it.media_type == MediaType.ANIME:
                rows += self._anime_rows(it)
            elif it.media_type == MediaType.TV:
                rows += self._tv_rows(it)
        return rows

    def _score(self, it):
        return it.score if it.score is not None else ""

    def _movie_rows(self, it):
        mid = it.ids.get("tmdb")
        if not mid:
            return []  # unmatched movie is reported, not written
        watched = it.status != Status.PLANNING
        return [_row(
            media_id=mid, media_type="movie", title=it.title,
            status=status_label(it.status),
            progress=1 if watched else "", score=self._score(it),
            end_date=_fmt_date(it.completed_at) if watched else "",
            progressed_at=_fmt_ts(it.completed_at) if watched else "",
            repeats=it.repeats or "",
        )]

    def _anime_rows(self, it):
        return [_row(
            media_id=it.ids.get("mal") or "", source="mal", media_type="anime",
            title=it.title, status=status_label(it.status),
            progress=it.progress or "", score=self._score(it),
            start_date=_fmt_date(it.started_at), end_date=_fmt_date(it.completed_at),
            progressed_at=_fmt_ts(it.completed_at or it.started_at),
        )]

    def _tv_rows(self, it):
        mid = it.ids.get("tmdb")
        if not mid:
            return []
        title = it.title
        if not it.episodes:
            # No episodes: either watchlist (Planning) or all-mismatched (bare In progress).
            status = "Planning" if it.status == Status.PLANNING else "In progress"
            return [_row(media_id=mid, media_type="tv", title=title, status=status,
                         score=self._score(it))]

        watched_total = len(it.episodes)
        tv_status = "Completed" if it.total and watched_total >= it.total else "In progress"
        rows = [_row(media_id=mid, media_type="tv", title=title, status=tv_status,
                     score=self._score(it))]
        for season in it.watched_seasons:
            watched = it.episodes_in_season(season)
            total = it.season_totals.get(season)
            rows.append(_row(
                media_id=mid, media_type="season", title=title, season_number=season,
                progress=watched,
                status="Completed" if total and watched >= total else "In progress",
            ))
        for e in sorted(it.episodes, key=lambda e: (e.season, e.number)):
            rows.append(_row(
                media_id=mid, media_type="episode", title=title,
                season_number=e.season, episode_number=e.number,
                end_date=_fmt_date(e.watched_at), progressed_at=_fmt_ts(e.watched_at),
                repeats=e.repeats or "",
            ))
        return rows

    # ---- output ----
    def write(self, rows: list[dict], out_path: str) -> int:
        return write_csv(rows, out_path)
