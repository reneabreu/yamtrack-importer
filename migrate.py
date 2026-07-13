#!/usr/bin/env python3
"""TV Time -> Yamtrack migration tool.

Usage
-----
One-shot: convert a source to a Yamtrack import CSV, then upload it via
Yamtrack -> Settings -> Import (Yamtrack has no media-create API; the CSV is its
bulk-import path):

    python migrate.py convert --export "./tv time gdpr data" --out yamtrack_import.csv

Library: ingest one or more sources into a local, deduplicated library, then
export the whole thing (so titles seen on multiple sources merge into one):

    python migrate.py ingest --export "./tv time gdpr data"
    python migrate.py export-library --exporter yamtrack --out yamtrack_import.csv

Config can also come from a .env file (see .env.example).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from yamtrack_importer.core.ingest import ingest_source
from yamtrack_importer.core.library import Library
from yamtrack_importer.core.pipeline import export_library
from yamtrack_importer.core.pipeline import run as run_pipeline
from yamtrack_importer.exporters.registry import all_exporters, get_exporter
from yamtrack_importer.mal import MALResolver
from yamtrack_importer.resolve import TMDBResolver
from yamtrack_importer.sources.tvtime import TVTimeSource


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--export", required=True, help="Path to the extracted TV Time GDPR folder.")
    p.add_argument("--tmdb-key", default=os.environ.get("TMDB_API_KEY", ""),
                   help="TMDB v3 API key or v4 read token (env: TMDB_API_KEY).")
    p.add_argument("--mal-client-id", default=os.environ.get("MAL_CLIENT_ID", ""),
                   help="Official MAL API Client ID (env: MAL_CLIENT_ID). "
                        "Blank uses the free Jikan API.")
    p.add_argument("--cache", default="tmdb_cache.json", help="Resolution cache file.")
    p.add_argument("--overrides", default="overrides.json",
                   help="Manual id overrides file (optional).")
    p.add_argument("--no-shows", action="store_true", help="Skip TV shows.")
    p.add_argument("--no-movies", action="store_true", help="Skip movies.")
    p.add_argument("--no-watchlist", action="store_true", help="Skip watchlist / planning items.")
    p.add_argument("--no-ratings", action="store_true", help="Skip star ratings.")
    p.add_argument("--no-anime", action="store_true",
                   help="Import anime as TV (don't reroute to MyAnimeList).")
    p.add_argument("--report", default="migration_report.json",
                   help="Where to write the match/unmatched report.")


def _providers(args):
    return {
        "tmdb": TMDBResolver(api_key=args.tmdb_key, cache_path=args.cache,
                             overrides_path=args.overrides),
        "mal": MALResolver(
            cache_path=os.path.join(os.path.dirname(args.cache) or ".", "mal_cache.json"),
            overrides_path=args.overrides,
            client_id=getattr(args, "mal_client_id", "")),
    }


def _options(args):
    return {
        "include_shows": not args.no_shows,
        "include_movies": not args.no_movies,
        "include_watchlist": not args.no_watchlist,
        "include_ratings": not args.no_ratings,
        "include_anime_as_anime": not args.no_anime,
    }


def _run_pipeline(args):
    providers = _providers(args)
    options = _options(args)
    rows, report = run_pipeline(
        TVTimeSource(), {"export": args.export}, options, get_exporter("yamtrack"), providers
    )
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    scaffold = report.get("overrides_scaffold") or {}
    if scaffold:
        with open("overrides.template.json", "w", encoding="utf-8") as fh:
            json.dump(scaffold, fh, ensure_ascii=False, indent=2)
    _print_report(report, args.report)
    return rows, report


def _print_report(report: dict, report_path: str) -> None:
    print("\n=== Migration summary ===")
    print(f"  Shows matched : {report['shows_matched']}/{report['shows_total']}")
    print(f"  Movies matched: {report['movies_matched']}/{report['movies_total']}")
    print(f"  Rows generated: {report['rows']}  {report['row_counts_by_type']}")
    n_unmatched = len(report["unmatched_shows"]) + len(report["unmatched_movies"])
    if n_unmatched:
        print(f"  Unmatched     : {n_unmatched} — fill ids in overrides.template.json,")
        print(f"                  save as overrides.json, and re-run. Details: {report_path}")
    print()


def cmd_convert(args):
    rows, _ = _run_pipeline(args)
    n = get_exporter("yamtrack").write(rows, args.out)
    print(f"Wrote {n} rows -> {args.out}")
    print("Upload it in Yamtrack: Settings -> Import -> Yamtrack CSV.")


def cmd_ingest(args):
    with Library(args.library) as lib:
        result = ingest_source(
            lib, TVTimeSource(), {"export": args.export}, _options(args), _providers(args)
        )
        ing = result["ingest"]
        print(f"Ingested into {args.library}: +{ing['added']} new, {ing['merged']} merged "
              f"— {ing['total']} titles total.")


def cmd_export_library(args):
    with Library(args.library) as lib:
        rows, report = export_library(lib, get_exporter(args.exporter), delta=args.delta)
        if not rows:
            if args.delta:
                print("No changes since the last export — nothing written.")
                return
            sys.exit("Library is empty — run `ingest` first.")
        n = get_exporter(args.exporter).write(rows, args.out)
    if args.delta:
        print(f"Wrote {n} rows for {report['changed_titles']} changed title(s) -> {args.out}")
    else:
        print(f"Wrote {n} rows -> {args.out}")


def cmd_clear_library(args):
    with Library(args.library) as lib:
        n = lib.clear()
    print(f"Cleared {n} title(s) from {args.library}.")


def main(argv=None):
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Migrate TV Time data to Yamtrack.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_conv = sub.add_parser("convert", help="One-shot: write a Yamtrack import CSV.")
    _add_common(p_conv)
    p_conv.add_argument("--out", default="yamtrack_import.csv", help="Output CSV path.")
    p_conv.set_defaults(func=cmd_convert)

    p_ing = sub.add_parser("ingest", help="Add a source to the local library (dedup/merge).")
    _add_common(p_ing)
    p_ing.add_argument("--library", default="library.db", help="SQLite library path.")
    p_ing.set_defaults(func=cmd_ingest)

    exporter_ids = [e.info.id for e in all_exporters()]
    p_exp = sub.add_parser("export-library", help="Export the whole library to a file.")
    p_exp.add_argument("--library", default="library.db", help="SQLite library path.")
    p_exp.add_argument("--exporter", default="yamtrack", choices=exporter_ids,
                       help="Destination format.")
    p_exp.add_argument("--out", default="yamtrack_import.csv", help="Output file path.")
    p_exp.add_argument("--delta", action="store_true",
                       help="Only titles added/changed since this exporter's last export.")
    p_exp.set_defaults(func=cmd_export_library)

    p_clr = sub.add_parser("clear-library", help="Empty the local library.")
    p_clr.add_argument("--library", default="library.db", help="SQLite library path.")
    p_clr.set_defaults(func=cmd_clear_library)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if args.command in ("convert", "ingest") and not args.tmdb_key:
        sys.exit("A TMDB API key is required. Set --tmdb-key or TMDB_API_KEY in .env.")
    args.func(args)


if __name__ == "__main__":
    main()
