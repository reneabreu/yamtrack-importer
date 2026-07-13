"""Exporter (destination) interface."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import MediaItem


@dataclass
class ExporterInfo:
    id: str
    label: str
    modes: list[str] = field(default_factory=lambda: ["file"])   # "file" and/or "api"
    media_types: list[str] = field(default_factory=list)          # types it can write
    # media_type value -> id provider this exporter needs (e.g. {"tv": "tmdb"}).
    # Empty means the exporter needs no external resolution.
    requires: dict[str, str] = field(default_factory=dict)
    output_ext: str = "csv"
    output_mime: str = "text/csv"


class Exporter:
    """Base class for an export destination."""

    info: ExporterInfo

    def requirements(self) -> dict[str, str]:
        return dict(self.info.requires)

    # ---- records ----
    def build(self, items: list[MediaItem]) -> list[dict]:
        """Turn canonical items into this destination's record dicts."""
        raise NotImplementedError

    def write(self, records: list[dict], out_path: str) -> int:
        """Write records to a file; return the count."""
        raise NotImplementedError

    def details(self, records: list[dict]) -> list[dict]:
        """A per-title review summary for the result page (optional)."""
        return []

    # ---- API mode ----
    def check_connection(self, settings: dict) -> tuple[bool, str]:
        return False, "This exporter has no API mode."

    def push(self, records, settings, dry_run=False, progress=None) -> dict:
        raise NotImplementedError
