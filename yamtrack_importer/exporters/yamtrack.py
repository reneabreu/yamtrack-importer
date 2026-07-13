"""Yamtrack export destination: canonical MediaItems -> Yamtrack rows (CSV/API)."""

from __future__ import annotations

from ..api_client import YamtrackClient
from ..build_records import CSV_COLUMNS, _fmt_date, _fmt_ts, _row  # shared row helpers
from ..core.model import MediaItem, MediaType, Status
from ..core.resolve_service import status_label
from ..csv_writer import write_csv
from .base import Exporter, ExporterInfo

_SOURCE = {"tmdb": "tmdb", "mal": "mal"}


class YamtrackExporter(Exporter):
    info = ExporterInfo(
        id="yamtrack",
        label="Yamtrack",
        modes=["csv", "api"],
        # id provider Yamtrack keys on, per media type
        requires={"tv": "tmdb", "movie": "tmdb", "anime": "mal"},
    )
    # what Yamtrack can write
    info.media_types = ["tv", "movie", "anime"]  # type: ignore[attr-defined]

    def requirements(self):
        return dict(self.info.requires)

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

    # ---- outputs ----
    def write_csv(self, rows: list[dict], out_path: str) -> int:
        return write_csv(rows, out_path)

    def check_connection(self, settings: dict):
        client = YamtrackClient(settings.get("yamtrack_url", ""), settings.get("yamtrack_key", ""))
        return client.check_connection()

    def push(self, rows: list[dict], settings: dict, dry_run=False, progress=None) -> dict:
        emit = progress or (lambda **_k: None)
        client = YamtrackClient(
            settings.get("yamtrack_url", ""), settings.get("yamtrack_key", ""), dry_run=dry_run
        )
        total = len(rows)
        emit(type="progress", phase="push", current=0, total=total)
        created = skipped = failed = 0
        failures: list[str] = []
        for i, row in enumerate(rows, 1):
            mt, src, mid = row["media_type"], row.get("source", "tmdb"), str(row["media_id"])
            if not dry_run and mt in ("tv", "movie") and mid and client.exists(mt, src, mid):
                skipped += 1
            else:
                ok, msg = client.create(row)
                if ok:
                    created += 1
                else:
                    failed += 1
                    if len(failures) < 100:
                        failures.append(f"{mt} {mid}: {msg}")
                        emit(type="log", msg=f"  ✗ {mt} {mid}: {msg}")
            if i % 25 == 0 or i == total:
                emit(type="progress", phase="push", current=i, total=total)
        emit(type="log", msg=f"Done. created={created} skipped={skipped} failed={failed}")
        return {"created": created, "skipped": skipped, "failed": failed,
                "dry_run": dry_run, "failures": failures}


# columns re-exported for the CSV writer
__all__ = ["YamtrackExporter", "CSV_COLUMNS"]
