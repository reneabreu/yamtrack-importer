"""A local, persistent media library backed by SQLite.

Runs no longer stand alone: each ingest folds its items into this store, keyed
by :func:`~yamtrack_importer.core.merge.identity`, so the same title coming from
two sources (e.g. an anime watched on both TV Time and Crunchyroll) becomes a
single merged row instead of a duplicate. Exporters then build from the whole
library, not one run.

One table, one JSON blob per title — the library speaks the canonical
``MediaItem`` model and nothing else, so it stays destination-agnostic.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

from .merge import identity, merge_items
from .model import EpisodeWatch, MediaItem, MediaType, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key         TEXT PRIMARY KEY,
    media_type  TEXT NOT NULL,
    title       TEXT NOT NULL,
    data        TEXT NOT NULL,        -- full canonical MediaItem as JSON
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(media_type);
"""


def _dt(s: str | None):
    return datetime.fromisoformat(s) if s else None


def item_to_json(it: MediaItem) -> dict:
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
        "last_activity": it.last_activity.isoformat() if it.last_activity else None,
        "favorite": it.favorite,
        "notes": it.notes,
        "sources": it.sources,
        "resolved": it.resolved,
        "season_totals": {str(k): v for k, v in it.season_totals.items()},
        "episodes": [
            {"season": e.season, "number": e.number,
             "watched_at": e.watched_at.isoformat() if e.watched_at else None,
             "repeats": e.repeats}
            for e in it.episodes
        ],
    }


def item_from_json(d: dict) -> MediaItem:
    return MediaItem(
        media_type=MediaType(d["media_type"]),
        title=d["title"],
        ids=dict(d.get("ids") or {}),
        year=d.get("year"),
        status=Status(d.get("status", "in_progress")),
        score=d.get("score"),
        progress=d.get("progress"),
        total=d.get("total"),
        repeats=d.get("repeats", 0),
        started_at=_dt(d.get("started_at")),
        completed_at=_dt(d.get("completed_at")),
        last_activity=_dt(d.get("last_activity")),
        favorite=d.get("favorite", False),
        notes=d.get("notes", ""),
        sources=list(d.get("sources") or []),
        resolved=d.get("resolved", False),
        season_totals={int(k): int(v) for k, v in (d.get("season_totals") or {}).items()},
        episodes=[
            EpisodeWatch(e["season"], e["number"], _dt(e.get("watched_at")), e.get("repeats", 0))
            for e in (d.get("episodes") or [])
        ],
    )


class Library:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- ingest ----
    def ingest(self, items: list[MediaItem], source_id: str | None = None) -> dict:
        """Upsert-merge items. Returns {added, merged, total}."""
        added = merged = 0
        cur = self._conn.cursor()
        for it in items:
            if source_id and source_id not in it.sources:
                it.sources = sorted(set(it.sources) | {source_id})
            key = identity(it)
            row = cur.execute("SELECT data FROM items WHERE key=?", (key,)).fetchone()
            if row is None:
                final = it
                added += 1
            else:
                final = merge_items(item_from_json(json.loads(row["data"])), it)
                merged += 1
            cur.execute(
                "INSERT INTO items(key, media_type, title, data, updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "media_type=excluded.media_type, title=excluded.title, "
                "data=excluded.data, updated_at=excluded.updated_at",
                (key, final.media_type.value, final.title,
                 json.dumps(item_to_json(final), ensure_ascii=False),
                 datetime.utcnow().isoformat()),
            )
        self._conn.commit()
        return {"added": added, "merged": merged, "total": self.count()}

    # ---- read ----
    def all_items(self) -> list[MediaItem]:
        rows = self._conn.execute("SELECT data FROM items ORDER BY media_type, title").fetchall()
        return [item_from_json(json.loads(r["data"])) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]

    def counts_by_type(self) -> dict:
        rows = self._conn.execute(
            "SELECT media_type, COUNT(*) AS n FROM items GROUP BY media_type"
        ).fetchall()
        return {r["media_type"]: r["n"] for r in rows}

    def clear(self) -> int:
        n = self.count()
        self._conn.execute("DELETE FROM items")
        self._conn.commit()
        return n
