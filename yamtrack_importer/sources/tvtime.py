"""TV Time source (implemented)."""

from __future__ import annotations

from ..pipeline import load_and_resolve
from .base import Source, SourceInfo, SourceInput


class TVTimeSource(Source):
    info = SourceInfo(
        id="tvtime",
        label="TV Time",
        status="ready",
        yamtrack_types=["tv", "movie"],
        metadata_provider="tmdb",
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

    def build(self, files, resolver, options, progress=None):
        export_dir = files["export"]  # already-extracted directory
        return load_and_resolve(
            export_dir,
            resolver,
            include_shows=options.get("include_shows", True),
            include_movies=options.get("include_movies", True),
            include_watchlist=options.get("include_watchlist", True),
            include_ratings=options.get("include_ratings", True),
            include_anime_as_anime=options.get("include_anime_as_anime", True),
            progress=progress,
        )
