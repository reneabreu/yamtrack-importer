"""Orchestration: source (import) -> resolution -> exporter (destination).

Source-agnostic and destination-agnostic. Produces the exporter's records plus
a neutral report used by the UI.
"""

from __future__ import annotations

from .model import MediaType
from .resolve_service import ResolutionService


def _noop(**_kw):
    pass


def run(source, inputs, options, exporter, providers, progress=None):
    """Return (records, report). ``records`` are the exporter's output rows."""
    emit = progress or _noop

    items = source.fetch(inputs, options, progress)
    shows = [it for it in items if it.media_type in (MediaType.TV, MediaType.ANIME)]
    movies = [it for it in items if it.media_type == MediaType.MOVIE]

    reroute = options.get("include_anime_as_anime", True)
    stats = ResolutionService(providers).resolve(
        items, exporter, reroute_anime=reroute, progress=progress
    )

    rows = exporter.build(items)
    emit(type="log", msg=f"Resolved. {len(rows)} records generated.")

    unmatched = stats["unmatched"]
    unmatched_shows = [u for u in unmatched if u["kind"] in ("show", "anime")]
    unmatched_movies = [u for u in unmatched if u["kind"] == "movie"]

    def _scaffold(u):
        if u["override_key"].startswith("anime:"):
            return {"mal_id": None, "title": u["title"]}
        return {"tmdb_id": None, "title": u["title"]}

    report = {
        "shows_total": len(shows),
        "shows_matched": sum(1 for it in shows if it.resolved),
        "movies_total": len(movies),
        "movies_matched": sum(1 for it in movies if it.resolved),
        "rows": len(rows),
        "anime_rerouted": stats["anime_rerouted"],
        "episodes_skipped": stats["episodes_skipped"],
        "numbering_mismatches": sorted(
            stats["numbering_mismatches"], key=lambda m: m["skipped"], reverse=True
        ),
        "unmatched_shows": unmatched_shows,
        "unmatched_movies": unmatched_movies,
        "overrides_scaffold": {u["override_key"]: _scaffold(u) for u in unmatched},
        "row_counts_by_type": _count_by_type(rows),
        "details": exporter.details(rows),
    }
    return rows, report


def _count_by_type(rows):
    counts = {}
    for r in rows:
        counts[r["media_type"]] = counts.get(r["media_type"], 0) + 1
    return counts
