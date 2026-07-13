"""Crunchyroll source (beta): watch history -> canonical anime MediaItems."""

from __future__ import annotations

import json
import os
from datetime import datetime

from ..core.model import MediaItem, MediaType, Status
from ..crunchyroll import CrunchyrollClient
from .base import Source, SourceInfo, SourceInput


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _episode_meta(item: dict) -> dict:
    """item.panel.episode_metadata holds series_title/season_number/episode_number;
    item.date_played / item.fully_watched sit on the item (per crunchyexporter-cli)."""
    panel = item.get("panel") or {}
    meta = panel.get("episode_metadata") or {}
    return {
        "series_title": meta.get("series_title") or panel.get("title"),
        "season_number": meta.get("season_number"),
        "episode_number": meta.get("episode_number"),
        "date_played": item.get("date_played"),
    }


class CrunchyrollSource(Source):
    info = SourceInfo(
        id="crunchyroll",
        label="Crunchyroll",
        status="ready",
        media_types=["anime"],
        beta=True,
        note="Anime watch history → anime (matched to MyAnimeList).",
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

    def _history_cache_path(self, options) -> str:
        # The fetched history is a media-metadata cache, so prefer the media dir.
        cache_dir = (options.get("media_dir") or os.environ.get("MEDIA_DIR")
                     or options.get("data_dir") or os.environ.get("DATA_DIR") or ".")
        return os.path.join(cache_dir, "crunchyroll_history.json")

    def fetch(self, inputs, options, progress=None):
        emit = progress or (lambda **_k: None)
        etp_rt = (inputs.get("etp_rt") or "").strip()
        cache_path = self._history_cache_path(options)

        raw: list[dict] = []
        if etp_rt:
            emit(type="log", msg="Authenticating with Crunchyroll…")
            client = CrunchyrollClient(etp_rt)
            client.authenticate()
            emit(type="log", msg="Fetching watch history…")
            for item in client.iter_history():
                raw.append(item)
            try:
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump(raw, fh)
            except OSError:
                pass
        elif os.path.exists(cache_path):
            emit(type="log", msg="Reusing last Crunchyroll fetch (no cookie provided)…")
            with open(cache_path, encoding="utf-8") as fh:
                raw = json.load(fh)
        else:
            raise RuntimeError(
                "Paste your Crunchyroll etp_rt cookie — there's no saved fetch to reuse yet."
            )

        series: dict[str, MediaItem] = {}
        episodes: dict[str, set] = {}
        count = 0
        for item in raw:
            meta = _episode_meta(item)
            title = (meta["series_title"] or "").strip()
            if not title:
                continue
            it = series.get(title)
            if it is None:
                it = MediaItem(media_type=MediaType.ANIME, title=title,
                               status=Status.IN_PROGRESS)
                series[title] = it
                episodes[title] = set()
            if meta["episode_number"] is not None:
                episodes[title].add((meta["season_number"], meta["episode_number"]))
            played = _parse_dt(meta["date_played"])
            if played:
                if it.started_at is None or played < it.started_at:
                    it.started_at = played
                if it.completed_at is None or played > it.completed_at:
                    it.completed_at = played
                    it.last_activity = played
            count += 1
            if count % 200 == 0:
                emit(type="log", msg=f"  …{count} history entries")

        for title, it in series.items():
            it.progress = len(episodes[title])   # completion decided at resolution

        emit(type="log", msg=f"Fetched {count} entries across {len(series)} series.")
        return list(series.values())
