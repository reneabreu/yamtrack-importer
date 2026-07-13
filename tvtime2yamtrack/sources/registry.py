"""Registry of available and planned migration sources."""

from __future__ import annotations

from .base import PlannedSource, Source, SourceInfo
from .crunchyroll import CrunchyrollSource
from .tvtime import TVTimeSource

# Planned sources. Each notes the Yamtrack metadata provider it will resolve
# against, which determines the resolver/matching strategy still to be built.
_PLANNED = [
    SourceInfo("netflix", "Netflix", "planned", ["tv", "movie"], "tmdb",
               note="Viewing history CSV; title-only, matched by name + year."),
    SourceInfo("globoplay", "Globo Play", "planned", ["tv", "movie"], "tmdb",
               note="BR catalog; title-based TMDB matching."),
    SourceInfo("xbox", "Xbox", "planned", ["game"], "igdb",
               note="Achievements/played games -> IGDB ids."),
    SourceInfo("nintendo", "Nintendo", "planned", ["game"], "igdb",
               note="Play activity -> IGDB ids."),
    SourceInfo("hbomax", "HBO Max", "planned", ["tv", "movie"], "tmdb",
               note="Viewing history; title-based TMDB matching."),
    SourceInfo("retroachievements", "RetroAchievements", "planned", ["game"], "igdb",
               note="Played games + completion -> IGDB ids."),
    SourceInfo("googleplaygames", "Google Play Games", "planned", ["game"], "igdb",
               note="Play history -> IGDB ids."),
    SourceInfo("appletv", "Apple TV", "planned", ["tv", "movie"], "tmdb",
               note="Viewing history; title-based TMDB matching."),
    SourceInfo("komga", "Komga", "planned", ["manga", "comic", "book"], "mangaupdates",
               note="Read progress via Komga API/export."),
    SourceInfo("kavita", "Kavita", "planned", ["manga", "comic", "book"], "mangaupdates",
               note="Read progress via Kavita API/export."),
]

_REGISTRY: dict[str, Source] = {}


def _register(source: Source) -> None:
    _REGISTRY[source.info.id] = source


_register(TVTimeSource())
_register(CrunchyrollSource())
for _info in _PLANNED:
    _register(PlannedSource(_info))


def get_source(source_id: str) -> Source:
    if source_id not in _REGISTRY:
        raise KeyError(f"Unknown source: {source_id}")
    return _REGISTRY[source_id]


def all_sources() -> list[Source]:
    """Ready sources first, then planned, each alphabetical by label."""
    return sorted(
        _REGISTRY.values(),
        key=lambda s: (not s.info.ready, s.info.label.lower()),
    )
