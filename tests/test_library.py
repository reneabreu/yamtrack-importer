"""Tests for the local library: identity keying, smart merge, and dedup on ingest.

Run: python -m pytest tests/  (or: python tests/test_library.py)
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yamtrack_importer.core.library import Library, item_from_json, item_to_json
from yamtrack_importer.core.merge import identity, merge_items
from yamtrack_importer.core.model import EpisodeWatch, MediaItem, MediaType, Status


def _anime(title, mal, **kw):
    return MediaItem(MediaType.ANIME, title, ids={"mal": mal}, **kw)


def test_identity_same_across_sources():
    a = _anime("Frieren", "52991", sources=["tvtime"])
    b = _anime("Frieren (Beyond Journey's End)", "52991", sources=["crunchyroll"])
    assert identity(a) == identity(b) == "anime:mal:52991"


def test_identity_falls_back_to_title():
    a = MediaItem(MediaType.MOVIE, "Some Film", year=2001)
    assert identity(a) == "movie:title:some film|2001"


def test_merge_widens_everything():
    a = _anime("Frieren", "52991", status=Status.IN_PROGRESS, progress=10, total=28,
               score=9.0, started_at=datetime(2024, 1, 1), completed_at=datetime(2024, 3, 1),
               sources=["tvtime"])
    b = _anime("Frieren", "52991", status=Status.COMPLETED, progress=28, total=28,
               score=None, started_at=datetime(2023, 12, 1), completed_at=datetime(2024, 4, 1),
               sources=["crunchyroll"])
    m = merge_items(a, b)
    assert m.progress == 28
    assert m.status == Status.COMPLETED
    assert m.score == 9.0                       # keeps the real score
    assert m.started_at == datetime(2023, 12, 1)  # earliest start
    assert m.completed_at == datetime(2024, 4, 1)  # latest completion
    assert m.sources == ["crunchyroll", "tvtime"]


def test_merge_unions_episodes():
    a = MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"},
                  episodes=[EpisodeWatch(1, 1, datetime(2020, 1, 1)), EpisodeWatch(1, 2)])
    b = MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"},
                  episodes=[EpisodeWatch(1, 2, datetime(2019, 1, 1), repeats=1), EpisodeWatch(1, 3)])
    m = merge_items(a, b)
    eps = {(e.season, e.number): e for e in m.episodes}
    assert set(eps) == {(1, 1), (1, 2), (1, 3)}
    assert eps[(1, 2)].watched_at == datetime(2019, 1, 1)  # earliest first-watch
    assert eps[(1, 2)].repeats == 1                          # higher rewatch count


def test_ingest_dedupes_across_sources():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        s1 = lib.ingest([_anime("Frieren", "52991", progress=10, total=28)], source_id="tvtime")
        assert s1 == {"added": 1, "merged": 0, "total": 1}
        s2 = lib.ingest([_anime("Frieren", "52991", progress=28, total=28,
                                 status=Status.COMPLETED)], source_id="crunchyroll")
        assert s2 == {"added": 0, "merged": 1, "total": 1}
        it = lib.all_items()[0]
        assert it.progress == 28
        assert it.status == Status.COMPLETED
        assert it.sources == ["crunchyroll", "tvtime"]


def test_roundtrip_serialization():
    it = MediaItem(MediaType.TV, "Show", ids={"tmdb": "1", "tvdb": "9"}, year=2011,
                   status=Status.COMPLETED, score=8.5, total=10, sources=["tvtime"],
                   season_totals={1: 10},
                   episodes=[EpisodeWatch(1, 1, datetime(2020, 5, 4), repeats=2)])
    back = item_from_json(item_to_json(it))
    assert back.title == "Show"
    assert back.ids == {"tmdb": "1", "tvdb": "9"}
    assert back.season_totals == {1: 10}
    assert back.episodes[0].watched_at == datetime(2020, 5, 4)
    assert back.episodes[0].repeats == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
