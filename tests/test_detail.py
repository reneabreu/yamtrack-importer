"""Tests for the content-page detail layer: pure normalizers + provider routing.

Run: python -m pytest tests/  (or: python tests/test_detail.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yamtrack_importer.core.detail import (
    get_detail,
    get_season_episodes,
    normalize_anime,
    normalize_movie,
    normalize_tv,
    watched_numbers,
)
from yamtrack_importer.core.model import EpisodeWatch, MediaItem, MediaType, Status

# ---- sample payloads (trimmed to the fields the normalizers read) ----

TV_RAW = {
    "id": 1399,
    "name": "Game of Thrones",
    "original_name": "Game of Thrones",
    "overview": "Seven noble families fight for the Iron Throne.",
    "poster_path": "/poster.jpg",
    "first_air_date": "2011-04-17",
    "number_of_episodes": 73,
    "seasons": [
        {"season_number": 0, "name": "Specials", "episode_count": 14},
        {"season_number": 1, "name": "Season 1", "episode_count": 10},
        {"season_number": 2, "name": "Season 2", "episode_count": 10},
    ],
    "recommendations": {"results": [
        {"id": 1402, "name": "The Walking Dead", "poster_path": "/twd.jpg"},
        {"id": 60059, "name": "Better Call Saul"},  # no poster
    ]},
}

ANIME_RAW = {
    "mal_id": 52991,
    "title": "Sousou no Frieren",
    "title_japanese": "葬送のフリーレン",
    "synopsis": "An elf mage reflects on her journey.",
    "episodes": 28,
    "url": "https://myanimelist.net/anime/52991",
    "aired": {"from": "2023-09-29T00:00:00+00:00"},
    "images": {"jpg": {"image_url": "https://cdn/small.jpg",
                       "large_image_url": "https://cdn/large.jpg"}},
}
ANIME_RECS = [
    {"entry": {"mal_id": 41025, "title": "Fumetsu no Anata e",
               "url": "https://myanimelist.net/anime/41025",
               "images": {"jpg": {"image_url": "https://cdn/rec.jpg"}}}},
    {"entry": {"mal_id": 1, "title": None}},  # dropped (no title)
]


def test_normalize_tv():
    it = MediaItem(MediaType.TV, "Game of Thrones", ids={"tmdb": "1399"},
                   episodes=[EpisodeWatch(1, 1), EpisodeWatch(1, 2), EpisodeWatch(2, 1)])
    d = normalize_tv(TV_RAW, it)
    assert d["cover"] == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert d["name"] == "Game of Thrones"
    assert d["original_name"] == "Game of Thrones"
    assert d["year"] == 2011
    assert d["episodes_total"] == 73
    assert d["watched_total"] == 3
    # seasons carry per-season watched counts pulled from the item
    s1 = next(s for s in d["seasons"] if s["number"] == 1)
    assert s1["episode_count"] == 10 and s1["watched"] == 2
    s2 = next(s for s in d["seasons"] if s["number"] == 2)
    assert s2["watched"] == 1
    # related keeps only titled entries and builds poster urls
    assert [r["name"] for r in d["related"]] == ["The Walking Dead", "Better Call Saul"]
    assert d["related"][0]["cover"] == "https://image.tmdb.org/t/p/w500/twd.jpg"
    assert d["related"][1]["cover"] is None


def test_normalize_movie():
    raw = {"id": 27205, "title": "Inception", "original_title": "Inception",
           "overview": "A thief who steals corporate secrets.",
           "poster_path": "/incep.jpg", "release_date": "2010-07-16",
           "recommendations": {"results": [{"id": 155, "title": "The Dark Knight"}]}}
    d = normalize_movie(raw, MediaItem(MediaType.MOVIE, "Inception", ids={"tmdb": "27205"}))
    assert d["kind"] == "movie" and d["year"] == 2010
    assert d["original_name"] == "Inception"
    assert d["seasons"] == [] and d["episodes_total"] is None
    assert d["related"][0]["name"] == "The Dark Knight"


def test_normalize_anime():
    it = MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "52991"},
                   status=Status.IN_PROGRESS, progress=12)
    d = normalize_anime(ANIME_RAW, ANIME_RECS, it)
    assert d["cover"] == "https://cdn/large.jpg"
    assert d["original_name"] == "葬送のフリーレン"
    assert d["year"] == 2023
    assert d["episodes_total"] == 28
    assert d["watched_total"] == 12
    # one pseudo-season covering the whole run, watched capped at total
    assert len(d["seasons"]) == 1
    assert d["seasons"][0]["episode_count"] == 28 and d["seasons"][0]["watched"] == 12
    # untitled recommendation is dropped
    assert [r["name"] for r in d["related"]] == ["Fumetsu no Anata e"]


def test_watched_numbers_falls_back_to_progress_for_anime():
    flat = MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "1"}, progress=3)
    assert watched_numbers(flat, 1) == {1, 2, 3}
    episodic = MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"},
                         episodes=[EpisodeWatch(1, 2), EpisodeWatch(1, 5), EpisodeWatch(2, 1)])
    assert watched_numbers(episodic, 1) == {2, 5}
    assert watched_numbers(episodic, 2) == {1}


class _StubTMDB:
    def tv_detail(self, i): return TV_RAW
    def tv_season(self, i, s):
        return {"episodes": [
            {"episode_number": 1, "name": "Winter Is Coming", "air_date": "2011-04-17"},
            {"episode_number": 2, "name": "The Kingsroad", "air_date": "2011-04-24"},
        ]}


class _StubMAL:
    def anime_detail(self, i): return ANIME_RAW
    def anime_recommendations(self, i): return ANIME_RECS
    def anime_episodes(self, i):
        return [{"mal_id": 1, "title": "The Journey's End", "aired": "2023-09-29T00:00:00+00:00"}]


def test_get_detail_routes_by_type_and_id():
    tv = MediaItem(MediaType.TV, "GoT", ids={"tmdb": "1399"})
    d, err = get_detail(tv, {"tmdb": _StubTMDB()})
    assert err is None and d["kind"] == "tv"

    anime = MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "52991"})
    d, err = get_detail(anime, {"mal": _StubMAL()})
    assert err is None and d["kind"] == "anime"


def test_get_detail_errors_without_tmdb_provider():
    tv = MediaItem(MediaType.TV, "GoT", ids={"tmdb": "1399"})
    d, err = get_detail(tv, {})           # no tmdb provider (no API key)
    assert d is None and "TMDB" in err

    orphan = MediaItem(MediaType.MOVIE, "Homemade", ids={})
    d, err = get_detail(orphan, {"tmdb": _StubTMDB()})
    assert d is None and "no tmdb" in err.lower()


def test_get_season_episodes_marks_watched():
    tv = MediaItem(MediaType.TV, "GoT", ids={"tmdb": "1399"},
                   episodes=[EpisodeWatch(1, 1)])
    eps = get_season_episodes(tv, {"tmdb": _StubTMDB()}, 1)
    assert [e["number"] for e in eps] == [1, 2]
    assert eps[0]["watched"] is True and eps[1]["watched"] is False

    anime = MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "52991"}, progress=1)
    eps = get_season_episodes(anime, {"mal": _StubMAL()}, 1)
    assert eps[0]["number"] == 1 and eps[0]["watched"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
