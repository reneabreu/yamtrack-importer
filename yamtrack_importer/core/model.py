"""The canonical media model — the neutral interchange format.

Import sources produce ``MediaItem``s; the resolution layer enriches their
``ids`` with whatever a chosen exporter needs; export destinations consume them.
Nothing here knows about Yamtrack, TMDB, TV Time, or any specific service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MediaType(str, Enum):
    TV = "tv"
    MOVIE = "movie"
    ANIME = "anime"
    MANGA = "manga"
    GAME = "game"
    BOOK = "book"


class Status(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PLANNING = "planning"
    PAUSED = "paused"
    DROPPED = "dropped"


@dataclass
class EpisodeWatch:
    """One watched episode of a TV/anime item."""

    season: int
    number: int
    watched_at: datetime | None = None
    repeats: int = 0  # extra watches beyond the first


@dataclass
class MediaItem:
    """A single tracked title in neutral form.

    ``ids`` maps a provider name to that provider's id, e.g.
    ``{"tvdb": "80348"}`` from a source, later enriched to
    ``{"tvdb": "80348", "tmdb": "1404"}`` by resolution. ``episodes`` carries
    per-episode fidelity for TV/anime; flat media (movies, games) use
    ``progress``/``repeats`` instead.
    """

    media_type: MediaType
    title: str
    ids: dict[str, str] = field(default_factory=dict)
    year: int | None = None
    status: Status = Status.IN_PROGRESS
    score: float | None = None            # canonical 0–10
    progress: int | None = None           # flat progress (episodes/chapters watched)
    total: int | None = None              # total units if known
    repeats: int = 0                      # rewatches of a flat item
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_activity: datetime | None = None
    favorite: bool = False
    notes: str = ""
    episodes: list[EpisodeWatch] = field(default_factory=list)
    # provenance: source ids this item's data came from (e.g. ["tvtime", "crunchyroll"])
    sources: list[str] = field(default_factory=list)

    # --- resolution bookkeeping (filled by the resolution layer) ---
    resolved: bool = False
    resolve_note: str = ""
    # {season_number: aired_episode_count} from the provider, for validation/status
    season_totals: dict[int, int] = field(default_factory=dict)

    # ---- convenience ----
    def id(self, provider: str) -> str | None:
        return self.ids.get(provider)

    @property
    def watched_episodes(self) -> int:
        return len(self.episodes)

    @property
    def watched_seasons(self) -> list[int]:
        return sorted({e.season for e in self.episodes})

    def episodes_in_season(self, season: int) -> int:
        return sum(1 for e in self.episodes if e.season == season)

    @property
    def total_rewatches(self) -> int:
        return sum(e.repeats for e in self.episodes)
