"""Crunchyroll source (beta): watch history -> Yamtrack anime rows."""

from __future__ import annotations

import json
import os
from datetime import datetime

from .. import build_records as br
from ..crunchyroll import CrunchyrollClient
from ..models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    AnimeRecord,
)
from .base import Source, SourceInfo, SourceInput


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _episode_meta(item: dict) -> dict:
    """Extract episode metadata from a watch-history item.

    Shape (verified against crunchyexporter-cli): item.panel.episode_metadata
    holds series_title/season_number/episode_number; item.date_played and
    item.fully_watched sit on the item.
    """
    panel = item.get("panel") or {}
    meta = panel.get("episode_metadata") or {}
    return {
        "series_title": meta.get("series_title") or panel.get("title"),
        "season_number": meta.get("season_number"),
        "episode_number": meta.get("episode_number"),
        "fully_watched": item.get("fully_watched", False),
        "date_played": item.get("date_played"),
    }


class CrunchyrollSource(Source):
    info = SourceInfo(
        id="crunchyroll",
        label="Crunchyroll",
        status="ready",
        yamtrack_types=["anime"],
        metadata_provider="mal",
        note="Anime watch history → Yamtrack anime (matched to MyAnimeList). Beta.",
        inputs=[
            SourceInput(
                key="etp_rt",
                label="Crunchyroll etp_rt cookie",
                kind="password",
                required=False,
                help="Log in to crunchyroll.com, open DevTools → Application → Cookies → "
                     "copy the value of 'etp_rt'. Not stored. Leave blank to reuse your "
                     "last fetch (handy when re-running after adding overrides).",
            )
        ],
    )

    def _history_cache_path(self, resolver) -> str:
        data_dir = os.path.dirname(getattr(resolver, "cache_path", "") or ".") or "."
        return os.path.join(data_dir, "crunchyroll_history.json")

    def build(self, files, resolver, options, progress=None):
        emit = progress or (lambda **_k: None)
        etp_rt = (files.get("etp_rt") or "").strip()
        cache_path = self._history_cache_path(resolver)

        items: list[dict] = []
        if etp_rt:
            emit(type="log", msg="Authenticating with Crunchyroll…")
            client = CrunchyrollClient(etp_rt)
            client.authenticate()
            emit(type="log", msg="Fetching watch history…")
            for item in client.iter_history():
                items.append(item)
            try:
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump(items, fh)
            except OSError:
                pass
        elif os.path.exists(cache_path):
            emit(type="log", msg="Reusing last Crunchyroll fetch (no cookie provided)…")
            with open(cache_path, encoding="utf-8") as fh:
                items = json.load(fh)
        else:
            raise RuntimeError(
                "Paste your Crunchyroll etp_rt cookie — there's no saved fetch to reuse yet."
            )

        series: dict[str, AnimeRecord] = {}
        episodes_by_series: dict[str, set] = {}
        count = 0
        for item in items:
            meta = _episode_meta(item)
            title = (meta["series_title"] or "").strip()
            if not title:
                continue
            rec = series.get(title)
            if rec is None:
                rec = AnimeRecord(title=title)
                series[title] = rec
                episodes_by_series[title] = set()

            if meta["episode_number"] is not None:
                episodes_by_series[title].add((meta["season_number"], meta["episode_number"]))

            played = _parse_dt(meta["date_played"])
            if played:
                if rec.start_date is None or played < rec.start_date:
                    rec.start_date = played
                if rec.end_date is None or played > rec.end_date:
                    rec.end_date = played

            count += 1
            if count % 100 == 0:
                emit(type="log", msg=f"  …{count} history entries")

        emit(type="log", msg=f"Fetched {count} entries across {len(series)} series.")

        # Progress = distinct watched episodes; completion is decided after MAL
        # resolution (watch history doesn't reliably include episode totals).
        for title, rec in series.items():
            rec.progress = len(episodes_by_series[title])
            rec.status = STATUS_IN_PROGRESS

        # Resolve to MAL ids.
        rows: list[dict] = []
        unmatched: list[dict] = []
        total_n = len(series)
        emit(type="progress", phase="resolve", current=0, total=total_n)
        for i, rec in enumerate(series.values(), 1):
            resolver.resolve_anime(rec)
            emit(type="progress", phase="resolve", current=i, total=total_n)
            # Now that MAL knows the episode total, cap progress and mark done.
            if rec.total_episodes and rec.progress > rec.total_episodes:
                rec.progress = rec.total_episodes
            if rec.total_episodes and rec.progress >= rec.total_episodes:
                rec.status = STATUS_COMPLETED
            rows.extend(br.rows_for_anime(rec))
            if not rec.mal_id:
                unmatched.append({
                    "kind": "anime", "title": rec.title, "year": "",
                    "state": rec.status, "date": rec.end_date.strftime("%Y-%m-%d")
                    if rec.end_date else "",
                    "override_key": f"anime:{rec.title.lower()}",
                    "search_url": f"https://myanimelist.net/anime.php?q="
                                  f"{rec.title.replace(' ', '+')}",
                    "note": rec.resolve_note,
                })
                emit(type="log", msg=f"  ⚠ no MAL match: {rec.title}")
        resolver.save_cache()
        emit(type="log", msg=f"Resolved. {len(rows)} anime rows generated.")

        matched = sum(1 for r in series.values() if r.mal_id)
        report = {
            "shows_total": total_n,
            "shows_matched": matched,
            "movies_total": 0,
            "movies_matched": 0,
            "rows": len(rows),
            "episodes_skipped": 0,
            "numbering_mismatches": [],
            "unmatched_shows": unmatched,
            "unmatched_movies": [],
            "overrides_scaffold": {
                u["override_key"]: {"mal_id": None, "title": u["title"]} for u in unmatched
            },
            "row_counts_by_type": {"anime": len(rows)},
        }
        return rows, report
