"""Orchestration: source (import) -> resolution -> exporter (destination).

Source-agnostic and destination-agnostic. Produces the exporter's records plus
a neutral report used by the UI.
"""

from __future__ import annotations

from .ingest import ingest_source
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


def run_with_library(library, source, inputs, options, exporter, providers, progress=None):
    """Ingest a source into the local library, then export the whole library.

    Returns (records, report). Deduplication happens on ingest, so the export
    reflects every source merged so far, not just this run.
    """
    emit = progress or _noop

    result = ingest_source(library, source, inputs, options, providers, progress)
    ing, stats = result["ingest"], result["resolve"]
    emit(type="log", msg=(f"Library: +{ing['added']} new, {ing['merged']} merged "
                          f"into existing — {ing['total']} titles total."))

    items = library.all_items()
    rows = exporter.build(items)
    emit(type="log", msg=f"Built {len(rows)} records from the library.")

    unmatched = stats["unmatched"]
    unmatched_shows = [u for u in unmatched if u["kind"] in ("show", "anime")]
    unmatched_movies = [u for u in unmatched if u["kind"] == "movie"]

    def _scaffold(u):
        if u["override_key"].startswith("anime:"):
            return {"mal_id": None, "title": u["title"]}
        return {"tmdb_id": None, "title": u["title"]}

    report = {
        "library": True,
        "ingest": ing,
        "library_counts_by_type": library.counts_by_type(),
        "rows": len(rows),
        "row_counts_by_type": _count_by_type(rows),
        "anime_rerouted": stats["anime_rerouted"],
        "episodes_skipped": stats["episodes_skipped"],
        "numbering_mismatches": sorted(
            stats["numbering_mismatches"], key=lambda m: m["skipped"], reverse=True
        ),
        "unmatched_shows": unmatched_shows,
        "unmatched_movies": unmatched_movies,
        "overrides_scaffold": {u["override_key"]: _scaffold(u) for u in unmatched},
        "details": exporter.details(rows),
    }
    return rows, report


def export_library(library, exporter, delta: bool = False):
    """Build export records from the library (no ingest).

    With ``delta=True`` only titles added or changed since this exporter's last
    export are included, and the export baseline is advanced so the next delta
    starts fresh. A full export also advances the baseline.
    """
    exporter_id = exporter.info.id
    if delta:
        items, current_fps = library.changed_since_snapshot(exporter_id)
    else:
        items = library.all_items()
        current_fps = library.fingerprints()

    rows = exporter.build(items)
    library.save_snapshot(exporter_id, current_fps)
    return rows, {
        "library": True,
        "delta": delta,
        "changed_titles": len(items) if delta else None,
        "library_total": library.count(),
        "library_counts_by_type": library.counts_by_type(),
        "rows": len(rows),
        "row_counts_by_type": _count_by_type(rows),
        "details": exporter.details(rows),
    }


def _count_by_type(rows):
    counts = {}
    for r in rows:
        counts[r["media_type"]] = counts.get(r["media_type"], 0) + 1
    return counts
