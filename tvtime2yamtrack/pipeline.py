"""Shared pipeline: parse -> resolve -> build rows, with reporting."""

from __future__ import annotations

import logging
import os
import urllib.parse

from . import build_records as br
from .mal import MALResolver
from .models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PLANNING,
    AnimeRecord,
    MovieRecord,
    ShowRecord,
)
from .parse import parse_movies, parse_shows
from .resolve import TMDBResolver

logger = logging.getLogger(__name__)


def _anime_from_show(show: ShowRecord, watched: bool) -> AnimeRecord:
    """Build an anime record from a TV Time show flagged as anime."""
    dates = [ep.last_watched for ep in show.episodes.values() if ep.last_watched]
    return AnimeRecord(
        title=show.name,  # TV Time's title (often romaji) matches MAL well
        progress=len(show.episodes) if watched else 0,
        status=STATUS_IN_PROGRESS if watched else STATUS_PLANNING,
        start_date=min(dates) if dates else None,
        end_date=max(dates) if dates else None,
        score=show.score,
    )


def _search_url(kind: str, name: str) -> str:
    q = urllib.parse.quote(name)
    return f"https://www.themoviedb.org/search/{'tv' if kind == 'show' else 'movie'}?query={q}"


def _unmatched_show(show: ShowRecord) -> dict:
    if show.episodes:
        state = STATUS_IN_PROGRESS
        date = max((e.last_watched for e in show.episodes.values() if e.last_watched),
                   default=None)
    else:
        state = STATUS_PLANNING
        date = None
    return {
        "kind": "show",
        "title": show.name,
        "year": "",
        "state": state,
        "date": date.strftime("%Y-%m-%d") if date else "",
        "override_key": f"tv:{show.tvdb_id or show.name.lower()}",
        "search_url": _search_url("show", show.name),
        "note": show.resolve_note,
    }


def _drop_episodes_missing_from_tmdb(show: ShowRecord) -> int:
    """Remove watched episodes that don't exist in TMDB's season structure.

    TV Time numbers episodes the TheTVDB way; TMDB often differs (especially
    anime and long-runners, plus season-0 specials). Emitting those would make
    Yamtrack 404 on every one during CSV import, so we drop them here. Returns
    the number removed. If we have no TMDB season data, nothing is dropped.
    """
    counts = show.season_episode_counts
    if not counts:
        return 0
    before = len(show.episodes)
    show.episodes = {
        (s, e): ep
        for (s, e), ep in show.episodes.items()
        if 1 <= e <= counts.get(s, 0)
    }
    return before - len(show.episodes)


def _unmatched_anime(anime: AnimeRecord) -> dict:
    return {
        "kind": "anime",
        "title": anime.title,
        "year": "",
        "state": anime.status,
        "date": anime.end_date.strftime("%Y-%m-%d") if anime.end_date else "",
        "override_key": f"anime:{anime.title.lower()}",
        "search_url": "https://myanimelist.net/anime.php?q="
                      + urllib.parse.quote(anime.title),
        "note": anime.resolve_note,
    }


def _unmatched_movie(movie: MovieRecord) -> dict:
    return {
        "kind": "movie",
        "title": movie.name,
        "year": movie.year or "",
        "state": STATUS_COMPLETED if movie.watched else STATUS_PLANNING,
        "date": movie.last_watched.strftime("%Y-%m-%d") if movie.last_watched else "",
        "override_key": f"movie:{movie.name.lower()}|{movie.year or ''}",
        "search_url": _search_url("movie", movie.name),
        "note": movie.resolve_note,
    }


def _find_export_dir(path: str) -> str:
    """Accept either the extracted folder or a folder containing it."""
    marker = "tracking-prod-records-v2.csv"
    if os.path.exists(os.path.join(path, marker)):
        return path
    for root, _dirs, files in os.walk(path):
        if marker in files:
            return root
    raise FileNotFoundError(
        f"Could not find {marker} under {path}. Point --export at the extracted "
        "TV Time GDPR folder."
    )


def _noop(**_kw):
    pass


def load_and_resolve(
    export_path: str,
    resolver: TMDBResolver,
    include_shows: bool = True,
    include_movies: bool = True,
    include_watchlist: bool = True,
    include_ratings: bool = True,
    include_anime_as_anime: bool = True,
    progress=None,
) -> tuple[list[dict], dict]:
    """Return (rows, report). Rows are ready for CSV or API.

    ``progress`` is an optional callback that receives keyword events:
    ``progress(type="log", msg=...)`` and
    ``progress(type="progress", phase="resolve", current=n, total=m)``.
    """
    emit = progress or _noop
    export_dir = _find_export_dir(export_path)
    logger.info("Using export dir: %s", export_dir)

    emit(type="log", msg="Parsing TV Time export…")
    shows: dict[str, ShowRecord] = parse_shows(export_dir) if include_shows else {}
    movies: dict[str, MovieRecord] = parse_movies(export_dir) if include_movies else {}

    if not include_ratings:
        for s in shows.values():
            s.score = None

    rows: list[dict] = []
    unmatched_shows: list[str] = []
    unmatched_movies: list[str] = []
    episodes_skipped = 0
    numbering_mismatches: list[dict] = []
    anime_rerouted = 0

    # Anime detected in the TV Time data are matched to MyAnimeList (Jikan)
    # instead of forced through TMDB's TV numbering.
    mal_resolver = None
    if include_anime_as_anime:
        mal_cache = os.path.join(os.path.dirname(resolver.cache_path) or ".", "mal_cache.json")
        mal_resolver = MALResolver(cache_path=mal_cache, overrides_path=resolver.overrides_path)

    total = len(shows) + len(movies)
    emit(type="log", msg=f"Resolving {total} titles against TMDB "
                         f"({len(shows)} shows, {len(movies)} movies)…")
    emit(type="progress", phase="resolve", current=0, total=total)
    done = 0
    for show in shows.values():
        resolver.resolve_show(show)
        done += 1
        if done % 25 == 0:
            resolver.save_cache()
        emit(type="progress", phase="resolve", current=done, total=total)

        if not show.tmdb_id:
            unmatched_shows.append(_unmatched_show(show))
            emit(type="log", msg=f"  ⚠ no match: {show.name} (show)")
            continue

        # Reroute anime to the MAL/anime pipeline.
        if mal_resolver is not None and show.is_anime:
            watched = bool(show.episodes)
            if not watched and not (include_watchlist and (show.for_later or show.followed)):
                continue
            anime = _anime_from_show(show, watched)
            mal_resolver.resolve_anime(anime)
            if anime.total_episodes and anime.progress > anime.total_episodes:
                anime.progress = anime.total_episodes
            if watched and anime.total_episodes and anime.progress >= anime.total_episodes:
                anime.status = STATUS_COMPLETED
            rows.extend(br.rows_for_anime(anime))
            anime_rerouted += 1
            if not anime.mal_id:
                unmatched_shows.append(_unmatched_anime(anime))
                emit(type="log", msg=f"  ⚠ no MAL match: {show.name} (anime)")
            continue

        if show.episodes:
            dropped = _drop_episodes_missing_from_tmdb(show)
            episodes_skipped += dropped
            if dropped:
                numbering_mismatches.append(
                    {"title": show.tmdb_title or show.name, "tmdb_id": show.tmdb_id,
                     "skipped": dropped}
                )
                emit(type="log", msg=f"  ⚠ {show.tmdb_title or show.name}: "
                                     f"{dropped} episode(s) not in TMDB (TVDB↔TMDB "
                                     "numbering) — skipped")
            if show.episodes:
                rows.extend(br.rows_for_show(show))
            else:
                # All episodes mismatched; keep the show itself in the library.
                rows.extend(br.rows_for_show_bare(show))
        elif include_watchlist and (show.for_later or show.followed):
            rows.extend(br.rows_for_show_watchlist(show))

    for movie in movies.values():
        resolver.resolve_movie(movie)
        done += 1
        if done % 25 == 0:
            resolver.save_cache()
        emit(type="progress", phase="resolve", current=done, total=total)

        if not movie.tmdb_id:
            unmatched_movies.append(_unmatched_movie(movie))
            emit(type="log", msg=f"  ⚠ no match: {movie.name} (movie)")
            continue
        if movie.watched:
            rows.extend(br.rows_for_movie(movie))
        elif include_watchlist and movie.watchlist:
            rows.extend(br.rows_for_movie(movie))

    resolver.save_cache()
    if mal_resolver is not None:
        mal_resolver.save_cache()
    if anime_rerouted:
        emit(type="log", msg=f"Routed {anime_rerouted} anime to MyAnimeList.")
    if episodes_skipped:
        emit(type="log", msg=f"Skipped {episodes_skipped} episode(s) across "
                             f"{len(numbering_mismatches)} show(s) due to TVDB↔TMDB "
                             "numbering differences.")
    emit(type="log", msg=f"Resolved. {len(rows)} Yamtrack rows generated.")

    def _scaffold_entry(u: dict) -> dict:
        if u["override_key"].startswith("anime:"):
            return {"mal_id": None, "title": u["title"]}
        return {"tmdb_id": None, "title": u["title"]}

    scaffold = {
        u["override_key"]: _scaffold_entry(u)
        for u in (unmatched_shows + unmatched_movies)
    }

    report = {
        "shows_total": len(shows),
        "shows_matched": sum(1 for s in shows.values() if s.tmdb_id),
        "movies_total": len(movies),
        "movies_matched": sum(1 for m in movies.values() if m.tmdb_id),
        "rows": len(rows),
        "anime_rerouted": anime_rerouted,
        "episodes_skipped": episodes_skipped,
        "numbering_mismatches": sorted(
            numbering_mismatches, key=lambda m: m["skipped"], reverse=True
        ),
        "unmatched_shows": unmatched_shows,
        "unmatched_movies": unmatched_movies,
        "overrides_scaffold": scaffold,
        "row_counts_by_type": _count_by_type(rows),
    }
    return rows, report


def _count_by_type(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["media_type"]] = counts.get(r["media_type"], 0) + 1
    return counts
