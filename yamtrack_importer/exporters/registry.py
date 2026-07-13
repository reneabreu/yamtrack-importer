"""Registry of export destinations."""

from __future__ import annotations

from .base import Exporter
from .canonical_json import CanonicalJSONExporter
from .yamtrack import YamtrackExporter

_REGISTRY: dict[str, Exporter] = {}


def _register(exporter: Exporter) -> None:
    _REGISTRY[exporter.info.id] = exporter


_register(YamtrackExporter())
_register(CanonicalJSONExporter())


def get_exporter(exporter_id: str) -> Exporter:
    if exporter_id not in _REGISTRY:
        raise KeyError(f"Unknown exporter: {exporter_id}")
    return _REGISTRY[exporter_id]


def all_exporters() -> list[Exporter]:
    return sorted(_REGISTRY.values(), key=lambda e: e.info.label.lower())


DEFAULT_EXPORTER = "yamtrack"
