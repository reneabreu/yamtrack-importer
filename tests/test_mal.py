"""Tests for the MAL resolver: provider selection + official-API/Jikan parsing.

HTTP is stubbed, so these run offline. Run: python tests/test_mal.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yamtrack_importer.mal import MALResolver


def _resolver(**kw):
    return MALResolver(cache_path="/tmp/_mal_test_cache.json", overrides_path=None, **kw)


def test_provider_selection():
    assert _resolver().provider == "jikan"
    assert _resolver(client_id="abc").provider == "mal"


def test_official_mal_parsed_and_preferred():
    r = _resolver(client_id="abc")
    r._mal_get = lambda path, params: {"data": [
        {"node": {"id": 52991, "title": "Sousou no Frieren", "num_episodes": 28,
                  "alternative_titles": {"en": "Frieren: Beyond Journey's End",
                                         "ja": "葬送", "synonyms": ["Frieren"]}}}]}

    def _no_jikan(*a, **k):
        raise AssertionError("Jikan should not be called when MAL returns a match")

    r._jikan_get = _no_jikan
    d = r.resolve_anime_by_title("Frieren")
    assert d["mal_id"] == 52991
    assert d["episodes"] == 28


def test_falls_back_to_jikan_when_mal_empty():
    r = _resolver(client_id="abc")
    r._mal_get = lambda path, params: {"data": []}
    r._jikan_get = lambda path, params: {"data": [
        {"mal_id": 21, "title": "One Piece", "episodes": None,
         "titles": [{"title": "One Piece"}]}]}
    d = r.resolve_anime_by_title("One Piece")
    assert d["mal_id"] == 21


def test_no_match_returns_miss():
    r = _resolver()
    r._jikan_get = lambda path, params: {"data": [
        {"mal_id": 1, "title": "Totally Unrelated", "titles": [{"title": "Totally Unrelated"}]}]}
    d = r.resolve_anime_by_title("Zzzz Nonexistent Show")
    assert d["mal_id"] is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
