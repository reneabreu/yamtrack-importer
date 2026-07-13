"""Canonical JSON exporter: dump the neutral MediaItems as JSON.

Needs no external resolution (``requires`` is empty), so it works offline and
captures the data exactly as the source produced it — a portable interchange
file, and a demonstration that the import/export seam is destination-agnostic.
"""

from __future__ import annotations

import json

from ..core.model import MediaItem
from .base import Exporter, ExporterInfo


def _item_to_dict(it: MediaItem) -> dict:
    return {
        "media_type": it.media_type.value,
        "title": it.title,
        "ids": it.ids,
        "year": it.year,
        "status": it.status.value,
        "score": it.score,
        "progress": it.progress,
        "total": it.total,
        "repeats": it.repeats,
        "started_at": it.started_at.isoformat() if it.started_at else None,
        "completed_at": it.completed_at.isoformat() if it.completed_at else None,
        "favorite": it.favorite,
        "episodes": [
            {"season": e.season, "number": e.number,
             "watched_at": e.watched_at.isoformat() if e.watched_at else None,
             "repeats": e.repeats}
            for e in it.episodes
        ],
    }


class CanonicalJSONExporter(Exporter):
    info = ExporterInfo(
        id="json",
        label="Canonical JSON",
        modes=["file"],
        media_types=["tv", "movie", "anime", "manga", "game", "book"],
        requires={},                 # no external id resolution needed
        output_ext="json",
        output_mime="application/json",
        file_hint="Portable canonical export — the neutral data as JSON",
    )

    def build(self, items):
        # records here are the canonical dicts themselves
        return [_item_to_dict(it) for it in items]

    def write(self, records, out_path):
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
        return len(records)

    def details(self, records):
        out = []
        for r in records:
            eps = r.get("episodes") or []
            out.append({
                "type": r["media_type"], "title": r["title"],
                "seasons": len({e["season"] for e in eps}) if eps else "",
                "episodes": len(eps) if eps else (r.get("progress") or ""),
                "rewatches": sum(e.get("repeats", 0) for e in eps) if eps
                             else (r.get("repeats") or ""),
                "status": r["status"], "score": r.get("score") or "",
                "last": (r.get("completed_at") or "")[:10],
            })
        out.sort(key=lambda x: (x["type"], str(x["title"]).lower()))
        return out
