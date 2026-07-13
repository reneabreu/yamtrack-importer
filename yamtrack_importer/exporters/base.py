"""Exporter (destination) interface."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import MediaItem


@dataclass
class ExporterInfo:
    id: str
    label: str
    modes: list[str] = field(default_factory=lambda: ["csv"])   # "csv" and/or "api"
    # media_type value -> id provider this exporter needs (e.g. {"tv": "tmdb"}).
    # An empty/missing entry means the exporter matches by title itself.
    requires: dict[str, str] = field(default_factory=dict)


class Exporter:
    """Base class for an export destination."""

    info: ExporterInfo

    def requirements(self) -> dict[str, str]:
        return dict(self.info.requires)

    # ---- CSV mode ----
    def to_csv(self, items: list[MediaItem], out_path: str) -> int:
        """Write ``items`` to ``out_path``; return the number of records written."""
        raise NotImplementedError

    # ---- API mode ----
    def check_connection(self, settings: dict) -> tuple[bool, str]:
        return False, "This exporter has no API mode."

    def push(self, items, settings, dry_run=False, progress=None) -> dict:
        """Send ``items`` to the destination; return a stats dict."""
        raise NotImplementedError
