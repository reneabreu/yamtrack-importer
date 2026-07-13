#!/usr/bin/env python3
"""TV Time -> Yamtrack migration tool.

Usage
-----
Convert to a Yamtrack import CSV (recommended, upload via the Yamtrack UI):

    python migrate.py convert --export "./tv time gdpr data" --out yamtrack_import.csv

Push straight to the Yamtrack REST API:

    python migrate.py push --export "./tv time gdpr data" \
        --yamtrack-url https://yamtrack.example.com

Config can also come from a .env file (see .env.example).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from tvtime2yamtrack.api_client import YamtrackClient
from tvtime2yamtrack.csv_writer import write_csv
from tvtime2yamtrack.pipeline import load_and_resolve
from tvtime2yamtrack.resolve import TMDBResolver


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


def _run_pipeline(args):
    resolver = TMDBResolver(
        api_key=args.tmdb_key, cache_path=args.cache, overrides_path=args.overrides
    )
    rows, report = load_and_resolve(
        args.export,
        resolver,
        include_shows=not args.no_shows,
        include_movies=not args.no_movies,
        include_watchlist=not args.no_watchlist,
        include_ratings=not args.no_ratings,
        include_anime_as_anime=not args.no_anime,
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
    n = write_csv(rows, args.out)
    print(f"Wrote {n} rows -> {args.out}")
    print("Upload it in Yamtrack: Settings -> Import -> Yamtrack CSV.")


def cmd_push(args):
    client = YamtrackClient(
        base_url=args.yamtrack_url or os.environ.get("YAMTRACK_URL", ""),
        api_key=args.yamtrack_key or os.environ.get("YAMTRACK_API_KEY", ""),
        dry_run=args.dry_run,
    )
    if not args.dry_run:
        ok, detail = client.check_connection()
        if not ok:
            sys.exit(f"Could not connect to Yamtrack: {detail}")

    rows, _ = _run_pipeline(args)

    created = skipped = failed = 0
    failures = []
    for i, row in enumerate(rows, 1):
        mt, src, mid = row["media_type"], row.get("source", "tmdb"), str(row["media_id"])
        # Episodes/seasons are created together with their parent; still try each.
        if not args.dry_run and not args.no_skip_existing and mt in ("tv", "movie"):
            if client.exists(mt, src, mid):
                skipped += 1
                continue
        ok, msg = client.create(row)
        if ok:
            created += 1
        else:
            failed += 1
            failures.append(f"{mt} {mid}: {msg}")
        if i % 100 == 0:
            print(f"  ...{i}/{len(rows)} (created {created}, skipped {skipped}, failed {failed})")

    print(f"\nDone. created={created} skipped={skipped} failed={failed}")
    if failures:
        with open("push_failures.log", "w", encoding="utf-8") as fh:
            fh.write("\n".join(failures))
        print(f"  Wrote {len(failures)} failures -> push_failures.log")


def main(argv=None):
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Migrate TV Time data to Yamtrack.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_conv = sub.add_parser("convert", help="Write a Yamtrack import CSV.")
    _add_common(p_conv)
    p_conv.add_argument("--out", default="yamtrack_import.csv", help="Output CSV path.")
    p_conv.set_defaults(func=cmd_convert)

    p_push = sub.add_parser("push", help="Push to the Yamtrack REST API.")
    _add_common(p_push)
    p_push.add_argument("--yamtrack-url", default=os.environ.get("YAMTRACK_URL", ""))
    p_push.add_argument("--yamtrack-key", default=os.environ.get("YAMTRACK_API_KEY", ""))
    p_push.add_argument("--dry-run", action="store_true", help="Resolve + print, don't POST.")
    p_push.add_argument("--no-skip-existing", action="store_true",
                        help="Do not skip items already in Yamtrack.")
    p_push.set_defaults(func=cmd_push)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if not args.tmdb_key:
        sys.exit("A TMDB API key is required. Set --tmdb-key or TMDB_API_KEY in .env.")
    args.func(args)


if __name__ == "__main__":
    main()
