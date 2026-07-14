"""Regression tests for the import -> resolve -> Yamtrack-export path.

Locks the behaviour the tracker will build on: the TV Time parser, the
source -> canonical mapping, the Yamtrack row mapping, and the resolution
layer's anime reroute + episode validation. All fixtures are synthetic, so
these run offline with no real GDPR export.

Run: python tests/test_export.py  (or python -m pytest tests/)
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The parser logs a warning for optional GDPR files the fixtures omit; quiet it.
logging.disable(logging.WARNING)

from yamtrack_importer.core.model import EpisodeWatch, MediaItem, MediaType, Status
from yamtrack_importer.core.resolve_service import ResolutionService
from yamtrack_importer.exporters.registry import get_exporter
from yamtrack_importer.parse import parse_movies, parse_shows
from yamtrack_importer.sources.tvtime import TVTimeSource


# --------------------------------------------------------------------------
# fixture: a minimal TV Time GDPR export
# --------------------------------------------------------------------------
def _write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _make_export() -> str:
    d = tempfile.mkdtemp()
    _write_csv(
        os.path.join(d, "tracking-prod-records-v2.csv"),
        ["series_name", "s_id", "season_number", "episode_number", "created_at",
         "is_followed", "is_archived", "is_for_later", "key"],
        [
            # Alpha S1E1 watched twice (=> repeats 1), S1E2 once (=> repeats 0)
            {"series_name": "Alpha", "s_id": "100", "season_number": "1", "episode_number": "1",
             "created_at": "2020-01-01 10:00:00", "is_followed": "true", "key": "episode-1"},
            {"series_name": "Alpha", "s_id": "100", "season_number": "1", "episode_number": "1",
             "created_at": "2021-06-01 10:00:00", "key": "rewatch-episode-1"},
            {"series_name": "Alpha", "s_id": "100", "season_number": "1", "episode_number": "2",
             "created_at": "2020-01-02 10:00:00", "key": "episode-2"},
            # Beta: followed only, no episodes -> planning
            {"series_name": "Beta", "s_id": "200", "season_number": "", "episode_number": "",
             "created_at": "", "is_followed": "true", "is_for_later": "true", "key": "user"},
        ],
    )
    _write_csv(
        os.path.join(d, "tv_show_rate.csv"),
        ["tv_show_name", "tv_show_id", "rating"],
        [{"tv_show_name": "Alpha", "tv_show_id": "100", "rating": "4"}],  # 4 -> 8.0
    )
    _write_csv(
        os.path.join(d, "tracking-prod-records.csv"),
        ["entity_type", "movie_name", "release_date", "type", "created_at", "updated_at", "runtime"],
        [
            {"entity_type": "movie", "movie_name": "Gamma", "release_date": "1999-03-31",
             "type": "watch", "created_at": "2019-05-05 00:00:00", "updated_at": "2019-05-05 00:00:00"},
            {"entity_type": "movie", "movie_name": "Gamma", "release_date": "0001-01-01",
             "type": "rewatch", "updated_at": "2022-01-01 00:00:00"},  # +1 repeat, placeholder year ignored
            {"entity_type": "movie", "movie_name": "Delta", "release_date": "2010-01-01",
             "type": "towatch"},
        ],
    )
    return d


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def test_parse_shows():
    shows = parse_shows(_make_export())
    assert set(s.name for s in shows.values()) == {"Alpha", "Beta"}
    alpha = next(s for s in shows.values() if s.name == "Alpha")
    assert alpha.tvdb_id == "100"
    assert alpha.score == 8.0                       # rating 4 -> 0-10
    assert alpha.episodes[(1, 1)].repeats == 1      # watched twice -> 1 extra
    assert alpha.episodes[(1, 2)].repeats == 0
    beta = next(s for s in shows.values() if s.name == "Beta")
    assert beta.for_later and not beta.episodes


def test_parse_movies():
    movies = parse_movies(_make_export())
    gamma = movies["gamma"]
    assert gamma.watched and gamma.repeats == 1 and gamma.year == 1999
    assert movies["delta"].watchlist and not movies["delta"].watched


# --------------------------------------------------------------------------
# source -> canonical
# --------------------------------------------------------------------------
def test_tvtime_source_to_items():
    opts = {"include_shows": True, "include_movies": True,
            "include_watchlist": True, "include_ratings": True}
    items = TVTimeSource().fetch({"export": _make_export()}, opts)
    by_title = {it.title: it for it in items}
    assert by_title["Alpha"].media_type == MediaType.TV
    assert by_title["Alpha"].status == Status.IN_PROGRESS
    assert len(by_title["Alpha"].episodes) == 2
    assert by_title["Alpha"].ids == {"tvdb": "100"}
    assert by_title["Beta"].status == Status.PLANNING
    assert by_title["Gamma"].media_type == MediaType.MOVIE
    assert by_title["Gamma"].status == Status.COMPLETED and by_title["Gamma"].repeats == 1
    assert by_title["Delta"].status == Status.PLANNING


def test_source_respects_toggles():
    items = TVTimeSource().fetch(
        {"export": _make_export()},
        {"include_shows": True, "include_movies": False,
         "include_watchlist": False, "include_ratings": False},
    )
    titles = {it.title for it in items}
    assert "Gamma" not in titles and "Delta" not in titles  # movies off
    assert "Beta" not in titles                              # watchlist off
    assert next(it for it in items if it.title == "Alpha").score is None  # ratings off


# --------------------------------------------------------------------------
# Yamtrack export mapping
# --------------------------------------------------------------------------
def _rows_by_type(rows):
    out = {}
    for r in rows:
        out.setdefault(r["media_type"], []).append(r)
    return out


def test_export_movie_rows():
    yex = get_exporter("yamtrack")
    watched = MediaItem(MediaType.MOVIE, "Gamma", ids={"tmdb": "500"},
                        status=Status.COMPLETED, score=7.0, repeats=1,
                        completed_at=datetime(2019, 5, 5))
    planning = MediaItem(MediaType.MOVIE, "Delta", ids={"tmdb": "501"}, status=Status.PLANNING)
    unmatched = MediaItem(MediaType.MOVIE, "NoId", status=Status.COMPLETED)
    rows = yex.build([watched, planning, unmatched])
    assert len(rows) == 2                       # unmatched movie produces no row
    m = {r["media_id"]: r for r in rows}
    assert m["500"]["status"] == "Completed" and m["500"]["progress"] == 1
    assert m["500"]["end_date"] == "2019-05-05" and m["500"]["repeats"] == 1
    assert m["501"]["status"] == "Planning" and m["501"]["progress"] == ""


def test_export_tv_rows_completed_with_seasons():
    yex = get_exporter("yamtrack")
    tv = MediaItem(
        MediaType.TV, "Alpha", ids={"tmdb": "900"}, total=3, score=8.0,
        season_totals={1: 2, 2: 1},
        episodes=[EpisodeWatch(1, 1, datetime(2020, 1, 1), repeats=1),
                  EpisodeWatch(1, 2, datetime(2020, 1, 2)),
                  EpisodeWatch(2, 1, datetime(2020, 2, 1))],
    )
    by_type = _rows_by_type(yex.build([tv]))
    assert len(by_type["tv"]) == 1 and by_type["tv"][0]["status"] == "Completed"
    assert by_type["tv"][0]["score"] == 8.0
    assert len(by_type["season"]) == 2
    assert all(s["status"] == "Completed" for s in by_type["season"])
    assert len(by_type["episode"]) == 3
    ep11 = next(e for e in by_type["episode"] if e["season_number"] == 1 and e["episode_number"] == 1)
    assert ep11["repeats"] == 1 and ep11["end_date"] == "2020-01-01"


def test_export_tv_in_progress_and_planning():
    yex = get_exporter("yamtrack")
    in_prog = MediaItem(MediaType.TV, "Partial", ids={"tmdb": "1"}, total=10,
                        season_totals={1: 10}, episodes=[EpisodeWatch(1, 1)])
    planning = MediaItem(MediaType.TV, "Later", ids={"tmdb": "2"}, status=Status.PLANNING)
    rows = yex.build([in_prog, planning])
    tv_rows = {r["media_id"]: r for r in rows if r["media_type"] == "tv"}
    assert tv_rows["1"]["status"] == "In progress"
    assert tv_rows["2"]["status"] == "Planning"
    assert not any(r["media_type"] == "episode" for r in rows if r["media_id"] == "2")


def test_export_anime_row():
    yex = get_exporter("yamtrack")
    anime = MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "52991"},
                      status=Status.COMPLETED, progress=28, score=9.0,
                      completed_at=datetime(2024, 4, 1))
    rows = yex.build([anime])
    assert len(rows) == 1
    assert rows[0]["source"] == "mal" and rows[0]["media_id"] == "52991"
    assert rows[0]["progress"] == 28 and rows[0]["status"] == "Completed"


# --------------------------------------------------------------------------
# resolution: anime reroute + episode validation
# --------------------------------------------------------------------------
class _StubTMDB:
    def __init__(self, anime_titles=()):
        self.anime_titles = set(anime_titles)

    def resolve_tv(self, tvdb, title):
        return {"tmdb_id": 1000 + int(tvdb or 0), "title": title, "total_episodes": 2,
                "season_episode_counts": {1: 2}, "is_anime": title in self.anime_titles}

    def resolve_movie_by_title(self, title, year):
        return {"tmdb_id": 42, "title": title}

    def save_cache(self):
        pass


class _StubMAL:
    def resolve_anime_by_title(self, title):
        return {"mal_id": 7000, "title": title, "episodes": 12}

    def save_cache(self):
        pass


def test_resolution_reroutes_anime_to_mal():
    yex = get_exporter("yamtrack")
    tv = MediaItem(MediaType.TV, "SomeAnime", ids={"tvdb": "5"},
                   episodes=[EpisodeWatch(1, 1, datetime(2020, 1, 1))])
    stats = ResolutionService({"tmdb": _StubTMDB(anime_titles=["SomeAnime"]),
                               "mal": _StubMAL()}).resolve([tv], yex)
    assert stats["anime_rerouted"] == 1
    assert tv.media_type == MediaType.ANIME
    assert tv.ids["mal"] == "7000"
    assert tv.progress == 1 and not tv.episodes   # flattened to a count


def test_resolution_drops_out_of_range_episodes():
    yex = get_exporter("yamtrack")
    tv = MediaItem(MediaType.TV, "Normal", ids={"tvdb": "9"},
                   episodes=[EpisodeWatch(1, 1), EpisodeWatch(1, 2), EpisodeWatch(1, 99)])
    stats = ResolutionService({"tmdb": _StubTMDB(), "mal": _StubMAL()}).resolve([tv], yex)
    assert tv.media_type == MediaType.TV
    assert {(e.season, e.number) for e in tv.episodes} == {(1, 1), (1, 2)}  # e99 dropped
    assert stats["episodes_skipped"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
