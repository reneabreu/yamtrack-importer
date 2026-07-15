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

import hashlib
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

CREATE TABLE IF NOT EXISTS export_snapshots (
    exporter_id  TEXT PRIMARY KEY,
    taken_at     TEXT NOT NULL,
    fingerprints TEXT NOT NULL         -- JSON {identity: content-hash}
);
"""


def item_fingerprint(it: MediaItem) -> str:
    """A content hash of the fields that make a title "changed" for export.

    Covers status/progress/score/dates and per-episode watches + rewatches, so a
    new episode or an incremented rewatch flips the fingerprint (and thus shows
    up in a delta export), while re-importing identical data does not.
    """
    payload = {
        "status": it.status.value,
        "score": it.score,
        "progress": it.progress,
        "total": it.total,
        "repeats": it.repeats,
        "started_at": it.started_at.isoformat() if it.started_at else None,
        "completed_at": it.completed_at.isoformat() if it.completed_at else None,
        "favorite": it.favorite,
        "ids": {k: it.ids[k] for k in sorted(it.ids)},
        "episodes": sorted(
            (e.season, e.number, e.watched_at.isoformat() if e.watched_at else None, e.repeats)
            for e in it.episodes
        ),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


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

    def items_with_keys(self, status: Status | None = None) -> list[tuple[str, MediaItem]]:
        """(identity-key, item) pairs, ordered, optionally filtered by status.

        The key is the stable row id (:func:`identity`); the tracker UI needs it
        to target a specific title for edit/delete.
        """
        rows = self._conn.execute(
            "SELECT key, data FROM items ORDER BY media_type, title"
        ).fetchall()
        out = []
        for r in rows:
            it = item_from_json(json.loads(r["data"]))
            if status is not None and it.status != status:
                continue
            out.append((r["key"], it))
        return out

    def get_item(self, key: str) -> MediaItem | None:
        row = self._conn.execute("SELECT data FROM items WHERE key=?", (key,)).fetchone()
        return item_from_json(json.loads(row["data"])) if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]

    def counts_by_type(self) -> dict:
        rows = self._conn.execute(
            "SELECT media_type, COUNT(*) AS n FROM items GROUP BY media_type"
        ).fetchall()
        return {r["media_type"]: r["n"] for r in rows}

    def counts_by_status(self) -> dict:
        """{status-value: count} across the whole library, for the status views."""
        out = {s.value: 0 for s in Status}
        for it in self.all_items():
            out[it.status.value] = out.get(it.status.value, 0) + 1
        return out

    # ---- write (tracker edits) ----
    # Fields a user may edit on a stored title. Provenance, ids, episodes, and
    # identity stay owned by import/merge; edits here never change the row key.
    EDITABLE_FIELDS = frozenset(
        {"status", "score", "repeats", "started_at", "completed_at", "favorite", "notes"}
    )

    def update_item(self, key: str, **fields) -> MediaItem:
        """Apply edited fields to the stored title and persist it.

        Values must already be the right type (``Status``, ``float``/``None``,
        ``int``, ``datetime``/``None``, ``bool``, ``str``); the web layer coerces
        form strings before calling this. Raises ``KeyError`` if the title does
        not exist and ``ValueError`` for any field outside ``EDITABLE_FIELDS``.
        """
        bad = set(fields) - self.EDITABLE_FIELDS
        if bad:
            raise ValueError(f"not editable: {', '.join(sorted(bad))}")
        it = self.get_item(key)
        if it is None:
            raise KeyError(key)
        for name, value in fields.items():
            setattr(it, name, value)
        self._conn.execute(
            "UPDATE items SET title=?, data=?, updated_at=? WHERE key=?",
            (it.title, json.dumps(item_to_json(it), ensure_ascii=False),
             datetime.utcnow().isoformat(), key),
        )
        self._conn.commit()
        return it

    def delete_item(self, key: str) -> bool:
        """Remove a title. Returns True if a row was deleted, False if absent."""
        cur = self._conn.execute("DELETE FROM items WHERE key=?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        n = self.count()
        self._conn.execute("DELETE FROM items")
        self._conn.execute("DELETE FROM export_snapshots")
        self._conn.commit()
        return n

    # ---- delta / export snapshots ----
    def fingerprints(self) -> dict[str, str]:
        """{identity: content-hash} for every title currently in the library."""
        return {identity(it): item_fingerprint(it) for it in self.all_items()}

    def get_snapshot(self, exporter_id: str) -> dict[str, str]:
        row = self._conn.execute(
            "SELECT fingerprints FROM export_snapshots WHERE exporter_id=?", (exporter_id,)
        ).fetchone()
        return json.loads(row["fingerprints"]) if row else {}

    def save_snapshot(self, exporter_id: str, fingerprints: dict[str, str]) -> None:
        self._conn.execute(
            "INSERT INTO export_snapshots(exporter_id, taken_at, fingerprints) "
            "VALUES(?,?,?) ON CONFLICT(exporter_id) DO UPDATE SET "
            "taken_at=excluded.taken_at, fingerprints=excluded.fingerprints",
            (exporter_id, datetime.utcnow().isoformat(),
             json.dumps(fingerprints, ensure_ascii=False)),
        )
        self._conn.commit()

    def changed_since_snapshot(self, exporter_id: str) -> tuple[list[MediaItem], dict[str, str]]:
        """Items new or modified since the last export for this exporter.

        Returns (changed_items, current_fingerprints). Saving the returned
        fingerprints as the new snapshot resets the delta baseline.
        """
        snap = self.get_snapshot(exporter_id)
        changed, current = [], {}
        for it in self.all_items():
            key = identity(it)
            fp = item_fingerprint(it)
            current[key] = fp
            if snap.get(key) != fp:
                changed.append(it)
        return changed, current
