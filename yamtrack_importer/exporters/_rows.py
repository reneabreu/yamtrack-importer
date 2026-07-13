"""Yamtrack row helpers: the flat import-CSV record shape + a review summary.

A Yamtrack row is a dict with the native import column names below. These are
used only by the Yamtrack exporter.
"""

from __future__ import annotations

import csv
from datetime import datetime

CSV_COLUMNS = [
    "media_id", "source", "media_type", "title", "image", "season_number",
    "episode_number", "score", "progress", "status", "start_date", "end_date",
    "notes", "progressed_at",
]


def fmt_date(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def fmt_ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def row(**kw) -> dict:
    base = {
        "media_id": "", "source": "tmdb", "media_type": "", "title": "", "image": "",
        "season_number": "", "episode_number": "", "score": "", "progress": "",
        "status": "", "start_date": "", "end_date": "", "notes": "",
        "progressed_at": "", "repeats": "",
    }
    base.update(kw)
    return base


def write_csv(rows: list[dict], out_path: str) -> int:
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL, extrasaction="ignore"
        )
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in CSV_COLUMNS})
    return len(rows)


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def summarize_rows(rows: list[dict]) -> list[dict]:
    """Collapse flat Yamtrack rows into one review entry per title."""
    shows: dict[str, dict] = {}
    out: list[dict] = []
    for r in rows:
        mt = r.get("media_type")
        if mt in ("tv", "season", "episode"):
            g = shows.get(r["media_id"])
            if g is None:
                g = {"type": "tv", "title": r["title"], "media_id": r["media_id"],
                     "_seasons": set(), "episodes": 0, "rewatches": 0,
                     "status": "", "score": "", "last": ""}
                shows[r["media_id"]] = g
                out.append(g)
            if mt == "tv":
                g["status"] = r.get("status", "")
                g["score"] = r.get("score", "")
            elif mt == "season":
                g["_seasons"].add(r.get("season_number"))
            elif mt == "episode":
                g["episodes"] += 1
                g["rewatches"] += _to_int(r.get("repeats"))
                d = r.get("end_date") or ""
                if d > g["last"]:
                    g["last"] = d
        elif mt == "movie":
            out.append({"type": "movie", "title": r["title"], "media_id": r["media_id"],
                        "seasons": "", "episodes": "", "rewatches": _to_int(r.get("repeats")),
                        "status": r.get("status", ""), "score": r.get("score", ""),
                        "last": r.get("end_date") or ""})
        elif mt == "anime":
            out.append({"type": "anime", "title": r["title"], "media_id": r["media_id"],
                        "seasons": "", "episodes": r.get("progress") or "", "rewatches": "",
                        "status": r.get("status", ""), "score": r.get("score", ""),
                        "last": r.get("end_date") or r.get("start_date") or ""})
    for g in shows.values():
        g["seasons"] = len(g.pop("_seasons"))
    out.sort(key=lambda x: (x["type"], str(x["title"]).lower()))
    return out
