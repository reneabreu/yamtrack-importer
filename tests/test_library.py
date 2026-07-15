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
from yamtrack_importer.core.pipeline import export_library
from yamtrack_importer.exporters.registry import get_exporter


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


def test_delta_export_tracks_changes():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    yex = get_exporter("yamtrack")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"}, total=10,
                              episodes=[EpisodeWatch(1, 1, datetime(2020, 1, 1))])])
        # full export sets the baseline
        rows, rep = export_library(lib, yex)
        assert rep["delta"] is False and rep["rows"] > 0
        # nothing changed since -> empty delta
        rows, rep = export_library(lib, yex, delta=True)
        assert rep["changed_titles"] == 0 and rows == []
        # a new episode -> that title shows up in the next delta
        lib.ingest([MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"}, total=10,
                             episodes=[EpisodeWatch(1, 2, datetime(2020, 2, 1))])])
        rows, rep = export_library(lib, yex, delta=True)
        assert rep["changed_titles"] == 1 and rows
        # exporting advances the baseline -> next delta is empty again
        rows, rep = export_library(lib, yex, delta=True)
        assert rep["changed_titles"] == 0


def test_delta_is_per_exporter():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.MOVIE, "Film", ids={"tmdb": "2"},
                             status=Status.COMPLETED)])
        export_library(lib, get_exporter("yamtrack"))          # yamtrack baseline set
        # json exporter has its own baseline -> the item is still "new" to it
        _, rep = export_library(lib, get_exporter("json"), delta=True)
        assert rep["changed_titles"] == 1


def test_update_item_edits_fields():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([_anime("Frieren", "52991", progress=10, total=28)])
        key = identity(_anime("Frieren", "52991"))
        updated = lib.update_item(
            key, status=Status.COMPLETED, score=9.5, repeats=2,
            started_at=datetime(2024, 1, 1), completed_at=datetime(2024, 3, 1),
            favorite=True, notes="banger",
        )
        assert updated.status == Status.COMPLETED and updated.score == 9.5
        # persisted, not just returned in memory
        reread = lib.get_item(key)
        assert reread.status == Status.COMPLETED
        assert reread.score == 9.5
        assert reread.repeats == 2
        assert reread.completed_at == datetime(2024, 3, 1)
        assert reread.favorite is True
        assert reread.notes == "banger"
        # untouched fields survive
        assert reread.progress == 10 and reread.total == 28


def test_update_item_rejects_unknown_field():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([_anime("Frieren", "52991")])
        key = identity(_anime("Frieren", "52991"))
        try:
            lib.update_item(key, title="Hacked")   # title is not user-editable here
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_update_item_missing_key_raises():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        try:
            lib.update_item("anime:mal:99999", status=Status.DROPPED)
            assert False, "expected KeyError"
        except KeyError:
            pass


def test_delete_item():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([_anime("Frieren", "52991"), _anime("Bocchi", "50416")])
        key = identity(_anime("Frieren", "52991"))
        assert lib.delete_item(key) is True
        assert lib.get_item(key) is None
        assert lib.count() == 1
        # deleting again is a no-op, reported as False
        assert lib.delete_item(key) is False


def test_items_with_keys_and_status_filter():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([
            _anime("Frieren", "52991", status=Status.COMPLETED),
            _anime("Bocchi", "50416", status=Status.IN_PROGRESS),
        ])
        pairs = lib.items_with_keys()
        assert {k for k, _ in pairs} == {"anime:mal:52991", "anime:mal:50416"}
        done = lib.items_with_keys(Status.COMPLETED)
        assert [it.title for _, it in done] == ["Frieren"]
        assert lib.counts_by_status()["in_progress"] == 1
        assert lib.counts_by_status()["completed"] == 1


def test_edit_shows_up_in_delta_export():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    yex = get_exporter("yamtrack")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.MOVIE, "Film", ids={"tmdb": "2"},
                              status=Status.IN_PROGRESS)])
        export_library(lib, yex)                       # baseline
        _, rep = export_library(lib, yex, delta=True)
        assert rep["changed_titles"] == 0
        # a manual edit flips the fingerprint -> the title reappears in the delta
        lib.update_item("movie:tmdb:2", status=Status.COMPLETED, score=8.0)
        _, rep = export_library(lib, yex, delta=True)
        assert rep["changed_titles"] == 1


def test_set_episode_toggle():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"}, total=20,
                              episodes=[EpisodeWatch(1, 1)])])
        key = "tv:tmdb:1"
        r = lib.set_episode(key, 1, 2, True)
        assert r == {"watched_total": 2, "season_watched": 2}
        assert {(e.season, e.number) for e in lib.get_item(key).episodes} == {(1, 1), (1, 2)}
        # unwatch
        r = lib.set_episode(key, 1, 1, False)
        assert r["watched_total"] == 1
        assert {(e.season, e.number) for e in lib.get_item(key).episodes} == {(1, 2)}
        # marking an already-watched episode again is idempotent
        assert lib.set_episode(key, 1, 2, True)["watched_total"] == 1


def test_set_watched_count_fills_seasons_in_order():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"}, total=18,
                              season_totals={0: 5, 1: 10, 2: 8})])  # season 0 (specials) skipped
        key = "tv:tmdb:1"
        lib.set_watched_count(key, 13)   # 10 in S1 + 3 in S2
        it = lib.get_item(key)
        assert it.watched_episodes == 13
        assert it.episodes_in_season(1) == 10
        assert it.episodes_in_season(2) == 3
        assert it.episodes_in_season(0) == 0
        assert it.progress is None       # episodes are now the source of truth


def test_set_watched_count_preserves_and_truncates():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        lib.ingest([MediaItem(MediaType.TV, "Show", ids={"tmdb": "1"}, total=10,
                              season_totals={1: 10},
                              episodes=[EpisodeWatch(1, 1, datetime(2020, 1, 1), repeats=2)])])
        key = "tv:tmdb:1"
        lib.set_watched_count(key, 3)
        it = lib.get_item(key)
        assert it.watched_episodes == 3
        ep1 = next(e for e in it.episodes if e.number == 1)
        assert ep1.watched_at == datetime(2020, 1, 1) and ep1.repeats == 2  # preserved
        # lowering the count truncates from the end
        lib.set_watched_count(key, 1)
        it = lib.get_item(key)
        assert [e.number for e in it.episodes] == [1]
        assert next(e for e in it.episodes if e.number == 1).repeats == 2  # still preserved


def test_set_watched_count_flat_anime_without_structure():
    db = os.path.join(tempfile.mkdtemp(), "lib.db")
    with Library(db) as lib:
        # no episodes, no season_totals -> single unbounded season 1
        lib.ingest([MediaItem(MediaType.ANIME, "Frieren", ids={"mal": "52991"},
                              total=28, progress=0)])
        key = "anime:mal:52991"
        lib.set_watched_count(key, 12)
        it = lib.get_item(key)
        assert it.watched_episodes == 12
        assert it.watched_seasons == [1]
        assert it.progress is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
