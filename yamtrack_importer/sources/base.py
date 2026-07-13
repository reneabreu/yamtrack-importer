"""Source (import module) interface.

A source extracts data from some service and returns neutral
``core.model.MediaItem``s. It does not know about resolution or any export
destination — those are separate layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import MediaItem


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
    media_types: list[str]            # canonical types it can emit, e.g. ["tv", "movie"]
    note: str = ""
    beta: bool = False                # show a "beta" tag in the UI
    inputs: list[SourceInput] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def has_include_options(self) -> bool:
        """Whether the shows/movies/watchlist/ratings toggles apply."""
        return any(t in self.media_types for t in ("tv", "movie"))


class Source:
    """Base class for an import source."""

    info: SourceInfo

    def fetch(self, inputs: dict[str, str], options: dict, progress=None) -> list[MediaItem]:
        """Return the source's tracked items as canonical ``MediaItem``s.

        ``inputs`` maps each SourceInput.key to a local path (a directory for
        extracted archives) or a submitted string. ``options`` carries the
        include_* toggles. ``progress`` is an optional event callback.
        """
        raise NotImplementedError


class PlannedSource(Source):
    """A source that is on the roadmap but not implemented yet."""

    def __init__(self, info: SourceInfo):
        self.info = info

    def fetch(self, inputs, options, progress=None):
        raise NotImplementedError(f"The '{self.info.label}' source is not implemented yet.")
