"""Resolution layer: enrich canonical items with the ids an exporter needs.

Given the items a source produced and the destination's requirements
(media_type -> id provider), fill in ``item.ids`` via the provider clients
(TMDB, MAL/Jikan), reclassify TV → anime where appropriate, and validate
episodes against the provider's season structure. Destination-agnostic.
"""

from __future__ import annotations

import urllib.parse

from .model import EpisodeWatch, MediaItem, MediaType, Status

_STATUS_LABEL = {
    Status.IN_PROGRESS: "In progress",
    Status.COMPLETED: "Completed",
    Status.PLANNING: "Planning",
    Status.PAUSED: "Paused",
    Status.DROPPED: "Dropped",
}


def _noop(**_kw):
    pass


class ResolutionService:
    def __init__(self, providers: dict):
        # providers: {"tmdb": TMDBResolver, "mal": MALResolver}
        self.providers = providers

    def resolve(self, items: list[MediaItem], exporter, reroute_anime: bool = True,
                progress=None) -> dict:
        emit = progress or _noop
        req = exporter.requirements()
        supports = set(getattr(exporter.info, "media_types", []))
        tmdb = self.providers.get("tmdb")
        mal = self.providers.get("mal")

        stats = {
            "unmatched": [], "anime_rerouted": 0,
            "episodes_skipped": 0, "numbering_mismatches": [],
        }
        total = len(items)
        emit(type="log", msg=f"Resolving {total} titles…")
        emit(type="progress", phase="resolve", current=0, total=total)
        for i, it in enumerate(items, 1):
            try:
                if it.media_type == MediaType.MOVIE:
                    self._movie(it, tmdb, req, stats)
                elif it.media_type == MediaType.TV:
                    self._tv(it, tmdb, mal, req, supports, reroute_anime, stats, emit)
                elif it.media_type == MediaType.ANIME:
                    self._anime(it, mal, stats)
            except Exception as exc:  # a bad title shouldn't kill the run
                it.resolve_note = f"error: {exc}"
            if i % 25 == 0:
                for p in self.providers.values():
                    p.save_cache()
            emit(type="progress", phase="resolve", current=i, total=total)

        for p in self.providers.values():
            p.save_cache()
        if stats["anime_rerouted"]:
            emit(type="log", msg=f"Routed {stats['anime_rerouted']} anime to MyAnimeList.")
        if stats["episodes_skipped"]:
            emit(type="log", msg=f"Skipped {stats['episodes_skipped']} episode(s) not in the "
                                 "provider's numbering.")
        return stats

    # ---- per media type ----
    def _movie(self, it, tmdb, req, stats):
        provider = req.get("movie", "tmdb")
        data = tmdb.resolve_movie_by_title(it.title, it.year) if provider == "tmdb" else None
        if not data or not data.get("tmdb_id"):
            it.resolve_note = (data or {}).get("note", "not found")
            stats["unmatched"].append(_unmatched(it))
            return
        it.ids["tmdb"] = str(data["tmdb_id"])
        it.title = data.get("title") or it.title
        it.resolved = True

    def _tv(self, it, tmdb, mal, req, supports, reroute_anime, stats, emit):
        data = tmdb.resolve_tv(it.ids.get("tvdb"), it.title)
        if not data or not data.get("tmdb_id"):
            it.resolve_note = (data or {}).get("note", "not found")
            stats["unmatched"].append(_unmatched(it))
            return
        it.ids["tmdb"] = str(data["tmdb_id"])
        it.title = data.get("title") or it.title
        it.total = data.get("total_episodes")
        it.season_totals = {int(k): int(v)
                            for k, v in (data.get("season_episode_counts") or {}).items()}

        if data.get("is_anime") and reroute_anime and "anime" in supports:
            self._reroute_anime(it, mal, stats, emit)
        else:
            it.resolved = True
            self._validate_episodes(it, stats, emit)

    def _reroute_anime(self, it, mal, stats, emit):
        stats["anime_rerouted"] += 1
        watched = bool(it.episodes)
        dates = [e.watched_at for e in it.episodes if e.watched_at]
        it.progress = len(it.episodes) if watched else 0
        it.started_at = min(dates) if dates else None
        it.completed_at = max(dates) if dates else None
        it.last_activity = it.completed_at
        it.episodes = []                       # anime tracked flat
        it.media_type = MediaType.ANIME
        if watched and it.status != Status.PLANNING:
            it.status = Status.IN_PROGRESS
        self._anime(it, mal, stats)

    def _anime(self, it, mal, stats):
        data = mal.resolve_anime_by_title(it.title) if mal else None
        if not data or not data.get("mal_id"):
            it.resolve_note = (data or {}).get("note", "not found") if data else "not found"
            stats["unmatched"].append(_unmatched(it))
            return
        it.ids["mal"] = str(data["mal_id"])
        it.title = data.get("title") or it.title
        it.total = data.get("episodes")
        it.resolved = True
        if it.total and it.progress and it.progress > it.total:
            it.progress = it.total
        if it.status != Status.PLANNING and it.total and (it.progress or 0) >= it.total:
            it.status = Status.COMPLETED

    def _validate_episodes(self, it, stats, emit):
        counts = it.season_totals
        if not counts:
            return
        before = len(it.episodes)
        it.episodes = [e for e in it.episodes if 1 <= e.number <= counts.get(e.season, 0)]
        dropped = before - len(it.episodes)
        if dropped:
            stats["episodes_skipped"] += dropped
            stats["numbering_mismatches"].append(
                {"title": it.title, "tmdb_id": it.ids.get("tmdb"), "skipped": dropped}
            )
            emit(type="log", msg=f"  ⚠ {it.title}: {dropped} episode(s) not in TMDB numbering — skipped")


def status_label(status: Status) -> str:
    return _STATUS_LABEL.get(status, "In progress")


def _unmatched(it: MediaItem) -> dict:
    if it.media_type == MediaType.ANIME:
        kind, key = "anime", f"anime:{it.title.lower()}"
        url = "https://myanimelist.net/anime.php?q=" + urllib.parse.quote(it.title)
    elif it.media_type == MediaType.MOVIE:
        kind = "movie"
        key = f"movie:{it.title.lower()}|{it.year or ''}"
        url = "https://www.themoviedb.org/search/movie?query=" + urllib.parse.quote(it.title)
    else:
        kind = "show"
        key = f"tv:{it.ids.get('tvdb') or it.title.lower()}"
        url = "https://www.themoviedb.org/search/tv?query=" + urllib.parse.quote(it.title)
    date = ""
    d = it.completed_at or it.last_activity
    if d:
        date = d.strftime("%Y-%m-%d")
    return {
        "kind": kind, "title": it.title, "year": it.year or "",
        "state": status_label(it.status), "date": date,
        "override_key": key, "search_url": url, "note": it.resolve_note,
    }
