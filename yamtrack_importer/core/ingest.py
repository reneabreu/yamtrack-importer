"""Ingest a source into the local library.

Resolution normally targets whatever the chosen exporter needs. For the library
we always resolve to the *canonical* ids that give a title its identity — TMDB
for TV/movies, MAL for anime — so items from different sources dedupe correctly
regardless of where they'll eventually be exported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .library import Library
from .resolve_service import ResolutionService

# TV/movie identity is a TMDB id; anime identity is a MAL id. Types without a
# provider here (game, book, manga) pass through and dedupe on title for now.
_CANONICAL_REQUIRES = {"tv": "tmdb", "movie": "tmdb", "anime": "mal"}


@dataclass
class _CanonicalInfo:
    media_types: list[str] = field(
        default_factory=lambda: ["tv", "movie", "anime", "manga", "game", "book"]
    )


class _CanonicalProfile:
    """A resolution target that fills canonical identity ids (not exporter-specific)."""

    info = _CanonicalInfo()

    def requirements(self) -> dict[str, str]:
        return dict(_CANONICAL_REQUIRES)


def ingest_source(library: Library, source, inputs, options, providers,
                  progress=None) -> dict:
    """Fetch a source, resolve to canonical ids, and merge into the library.

    Returns the library ingest stats plus the resolution stats.
    """
    reroute = options.get("include_anime_as_anime", True)
    items = source.fetch(inputs, options, progress)
    stats = ResolutionService(providers).resolve(
        items, _CanonicalProfile(), reroute_anime=reroute, progress=progress
    )
    ingest_stats = library.ingest(items, source_id=getattr(source.info, "id", None))
    return {"ingest": ingest_stats, "resolve": stats, "items": items}
