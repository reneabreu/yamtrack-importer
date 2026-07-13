"""Internal record types used by the TV Time parser (parse.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EpisodeWatch:
    """A single watched episode of a show (aggregated across watches)."""

    season_number: int
    episode_number: int
    # Most recent time the episode was watched (used for progressed_at / end_date).
    last_watched: datetime | None = None
    # Number of *extra* watches beyond the first (Yamtrack "repeats").
    repeats: int = 0

    def register(self, watched_at: datetime | None) -> None:
        self.repeats += 1  # caller decrements the first watch, see ShowRecord
        if watched_at and (self.last_watched is None or watched_at > self.last_watched):
            self.last_watched = watched_at


@dataclass
class ShowRecord:
    """A TV show tracked in TV Time."""

    tvdb_id: str | None
    name: str
    episodes: dict[tuple[int, int], EpisodeWatch] = field(default_factory=dict)
    followed: bool = False
    archived: bool = False
    for_later: bool = False
    score: float | None = None  # 0-10 (already converted from TV Time's 1-5)

    # Filled in during resolution.
    tmdb_id: int | None = None
    tmdb_title: str | None = None
    # {season_number: aired_episode_count} from TMDB, for status computation.
    season_episode_counts: dict[int, int] = field(default_factory=dict)
    total_episodes: int | None = None
    is_anime: bool = False  # TMDB Animation genre + Japanese origin
    resolve_note: str = ""

    @property
    def watched_episode_count(self) -> int:
        return len(self.episodes)

    def watched_in_season(self, season_number: int) -> int:
        return sum(1 for (s, _e) in self.episodes if s == season_number)

    @property
    def watched_seasons(self) -> list[int]:
        return sorted({s for (s, _e) in self.episodes})


@dataclass
class MovieRecord:
    """A movie tracked in TV Time (no external id is present in the export)."""

    name: str
    year: int | None
    watched: bool = False
    watchlist: bool = False
    last_watched: datetime | None = None
    repeats: int = 0
    runtime_seconds: int | None = None
    score: float | None = None  # 0-10

    # Filled in during resolution.
    tmdb_id: int | None = None
    tmdb_title: str | None = None
    resolve_note: str = ""
