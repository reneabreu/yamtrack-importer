"""Registry of available and planned migration sources."""

from __future__ import annotations

from .base import PlannedSource, Source, SourceInfo
from .crunchyroll import CrunchyrollSource
from .tvtime import TVTimeSource

# Planned sources (canonical media types they'll emit).
_PLANNED = [
    SourceInfo("netflix", "Netflix", "planned", ["tv", "movie"],
               note="Viewing history CSV; title-only, matched by name + year."),
    SourceInfo("globoplay", "Globo Play", "planned", ["tv", "movie"],
               note="BR catalog; title-based matching."),
    SourceInfo("xbox", "Xbox", "planned", ["game"],
               note="Achievements/played games."),
    SourceInfo("nintendo", "Nintendo", "planned", ["game"],
               note="Play activity."),
    SourceInfo("hbomax", "HBO Max", "planned", ["tv", "movie"],
               note="Viewing history; title-based matching."),
    SourceInfo("retroachievements", "RetroAchievements", "planned", ["game"],
               note="Played games + completion."),
    SourceInfo("googleplaygames", "Google Play Games", "planned", ["game"],
               note="Play history."),
    SourceInfo("appletv", "Apple TV", "planned", ["tv", "movie"],
               note="Viewing history; title-based matching."),
    SourceInfo("komga", "Komga", "planned", ["manga", "book"],
               note="Read progress via Komga API/export."),
    SourceInfo("kavita", "Kavita", "planned", ["manga", "book"],
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
