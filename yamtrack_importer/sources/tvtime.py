"""TV Time source: GDPR export -> canonical MediaItems."""

from __future__ import annotations

import logging
import os

from ..core.model import EpisodeWatch, MediaItem, MediaType, Status
from ..parse import parse_movies, parse_shows
from .base import Source, SourceInfo, SourceInput

logger = logging.getLogger(__name__)


def _find_export_dir(path: str) -> str:
    marker = "tracking-prod-records-v2.csv"
    if os.path.exists(os.path.join(path, marker)):
        return path
    for root, _dirs, files in os.walk(path):
        if marker in files:
            return root
    raise FileNotFoundError(
        f"Could not find {marker} under {path}. Point the upload at the extracted "
        "TV Time GDPR folder / .zip."
    )


class TVTimeSource(Source):
    info = SourceInfo(
        id="tvtime",
        label="TV Time",
        status="ready",
        media_types=["tv", "movie"],
        note="TV & movie watch history, watchlist, and show ratings.",
        inputs=[
            SourceInput(
                key="export",
                label="TV Time GDPR export (.zip)",
                kind="file",
                accept=".zip",
                help="Request it at gdpr.tvtime.com/gdpr/self-service and upload the .zip.",
            )
        ],
    )

    def fetch(self, inputs, options, progress=None):
        emit = progress or (lambda **_k: None)
        export_dir = _find_export_dir(inputs["export"])
        emit(type="log", msg="Parsing TV Time export…")

        include_shows = options.get("include_shows", True)
        include_movies = options.get("include_movies", True)
        include_watchlist = options.get("include_watchlist", True)
        include_ratings = options.get("include_ratings", True)

        items: list[MediaItem] = []

        if include_shows:
            for show in parse_shows(export_dir).values():
                score = show.score if include_ratings else None
                if show.episodes:
                    eps = [
                        EpisodeWatch(season=ep.season_number, number=ep.episode_number,
                                     watched_at=ep.last_watched, repeats=ep.repeats)
                        for ep in show.episodes.values()
                    ]
                    items.append(MediaItem(
                        media_type=MediaType.TV, title=show.name,
                        ids={"tvdb": show.tvdb_id} if show.tvdb_id else {},
                        status=Status.IN_PROGRESS, score=score, episodes=eps,
                    ))
                elif include_watchlist and (show.for_later or show.followed):
                    items.append(MediaItem(
                        media_type=MediaType.TV, title=show.name,
                        ids={"tvdb": show.tvdb_id} if show.tvdb_id else {},
                        status=Status.PLANNING, score=score,
                    ))

        if include_movies:
            for movie in parse_movies(export_dir).values():
                if movie.watched:
                    items.append(MediaItem(
                        media_type=MediaType.MOVIE, title=movie.name, year=movie.year,
                        status=Status.COMPLETED, repeats=movie.repeats,
                        completed_at=movie.last_watched, last_activity=movie.last_watched,
                    ))
                elif include_watchlist and movie.watchlist:
                    items.append(MediaItem(
                        media_type=MediaType.MOVIE, title=movie.name, year=movie.year,
                        status=Status.PLANNING,
                    ))

        emit(type="log", msg=f"Parsed {len(items)} titles from TV Time.")
        return items
