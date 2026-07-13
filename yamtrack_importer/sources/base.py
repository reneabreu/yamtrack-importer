"""Source plugin interface."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceInput:
    """An input a source needs from the user.

    ``kind`` is "file" (upload; .zip archives are auto-extracted), "text", or
    "password" (rendered as a masked field, e.g. a session cookie).
    """

    key: str
    label: str
    kind: str = "file"
    accept: str = ""          # for file inputs, e.g. ".zip,.csv"
    help: str = ""
    required: bool = True

    @property
    def is_file(self) -> bool:
        return self.kind == "file"


@dataclass
class SourceInfo:
    id: str
    label: str
    status: str                       # "ready" | "planned"
    yamtrack_types: list[str]         # e.g. ["tv", "movie"]
    metadata_provider: str            # "tmdb" | "igdb" | "openlibrary" | ...
    note: str = ""
    beta: bool = False                # show a "beta" tag in the UI
    inputs: list[SourceInput] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def has_include_options(self) -> bool:
        """Whether the shows/movies/watchlist/ratings toggles apply."""
        return any(t in self.yamtrack_types for t in ("tv", "movie"))


class Source:
    """Base class for a migration source."""

    info: SourceInfo

    def build(self, files: dict[str, str], resolver, options: dict, progress=None
              ) -> tuple[list[dict], dict]:
        """Return (rows, report).

        ``files`` maps each SourceInput.key to a local path (a directory for
        archive uploads that were already extracted). ``resolver`` is the
        metadata resolver for ``info.metadata_provider``. ``options`` carries
        the include_* toggles. ``progress`` is an optional event callback.
        """
        raise NotImplementedError


class PlannedSource(Source):
    """A source that is on the roadmap but not implemented yet."""

    def __init__(self, info: SourceInfo):
        self.info = info

    def build(self, files, resolver, options, progress=None):
        raise NotImplementedError(f"The '{self.info.label}' source is not implemented yet.")
