# Yamtrack Importer

[![CI](https://github.com/reneabreu/yamtrack-importer/actions/workflows/ci.yml/badge.svg)](https://github.com/reneabreu/yamtrack-importer/actions/workflows/ci.yml)
[![Publish image](https://github.com/reneabreu/yamtrack-importer/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/reneabreu/yamtrack-importer/actions/workflows/docker-publish.yml)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-yamtrack--importer-blue?logo=docker)](https://github.com/reneabreu/yamtrack-importer/pkgs/container/yamtrack-importer)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Import your TV, movie, and anime watch history into
[Yamtrack](https://github.com/FuzzyGrim/Yamtrack) — from a growing list of
services. Runs as a self-hosted **Docker web app** (pick a source, upload an
export or connect an account, then download a Yamtrack import CSV or a portable
JSON export) or as a **command-line tool**.

> Yamtrack has no media-create REST API — its bulk-import path is the CSV upload
> (*Settings → Import*), which is also the only one that preserves progress,
> status, score, rewatches, and real dates. So this tool produces files; it never
> pushes to a live instance.

It's built around a **source-plugin architecture**, so each service is a small
plugin. Available today:

- **TV Time** — watched episodes (with dates & rewatches), movies, watchlist,
  and ratings. Shows/movies match via TMDB; anime is auto-routed to MyAnimeList.
- **Crunchyroll** — watch history matched to MyAnimeList (Jikan).

Every import feeds a **local library** (a SQLite file in your data volume) that
**deduplicates and merges** across sources — so an anime you watched on both TV
Time and Crunchyroll becomes one entry with the union of episodes, the highest
progress and score, and the widest date range, not two rows. Exports are built
from the whole merged library.

On the roadmap: Netflix, HBO Max, Apple TV, Globo Play, Xbox, Nintendo,
RetroAchievements, Google Play Games, Komga, and Kavita. See
[ROADMAP.md](ROADMAP.md).

## Run with Docker (web UI)

Pulls the prebuilt multi-arch image from GitHub Container Registry — no local
build needed:

```bash
docker compose up -d
# open http://localhost:8080
```

Update to the newest published build with `docker compose pull && docker compose up -d`.
Pin a release by setting `IMAGE_TAG` (e.g. `IMAGE_TAG=v1.0.0`) in `.env`. To build
from source instead, add the build override:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

For active development, use the **live-reload** override — it mounts your working
tree and runs the Flask dev server, so template/code edits show on refresh with
no rebuild (local use only):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

To reach the web UI **from another device on your Tailscale network**, layer the
dev override over the Tailscale file — reachable at
`http://yamtrack-importer:8080` on the tailnet:

```bash
docker compose -f docker-compose.tailscale.yml -f docker-compose.dev.yml up
```

Images are published by GitHub Actions **only for version tags** `vX.Y.Z`
(tagged `X.Y.Z`, `X.Y`, and `latest`) or a manual run — not on every push. See
[Releasing](#releasing).

### Make shortcuts

A `Makefile` wraps the compose combinations (run `make` to list them):

| Command | Does |
|---------|------|
| `make up` / `make update` | Run / update the published image |
| `make build` | Build & run from local source |
| `make dev` | Live-reload dev server |
| `make dev-tailscale` | Live-reload dev server on your tailnet |
| `make tailscale` | Published image as a tailnet node |
| `make down` | Stop & remove everything (any mode) |
| `make release VERSION=v1.0.0` | Tag & push a release |

1. Go to **Settings** and paste your **TMDB API key** (free at
   [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)).
2. On the main page pick a source (e.g. **TV Time**, upload your GDPR `.zip`),
   choose a destination (**Yamtrack CSV** or **Canonical JSON**), and run.

> **TV Time is shutting down on 15 July 2026.** If you use it, request your data
> export first at <https://gdpr.tvtime.com/gdpr/self-service> — the importer
> reads that `.zip` directly.

The run streams **live progress** — a progress bar plus a console log — while it
resolves titles and imports, so a large library that takes a few minutes shows
exactly what it's doing.

Each run is ingested into your **Library** (`Library` in the nav): a persistent,
deduplicated collection that all sources feed into. The result page shows how
many titles were newly added versus merged into existing ones, and the export
you download reflects the whole library — so importing TV Time and then
Crunchyroll gives you one merged collection, not overlapping duplicates. On the
Library page you can browse everything (with the sources each title came from),
re-export it as CSV or JSON at any time, or clear it to start fresh.

Each destination also offers a **Changes only** export: it snapshots the library
whenever you export, so the next "changes only" download contains just the titles
added or changed since — new episodes, rewatches, status or score updates. Handy
for topping up Yamtrack after you watch more, without re-importing everything.

Every run is also saved under **History** (in the data volume): re-open a past
summary or re-download its CSV without reprocessing. Unmatched titles can be
fixed right on the result page — paste the correct TMDB/MAL id and Save (writes
`overrides.json` for you), then re-run. For Crunchyroll, leave the `etp_rt`
field blank on a re-run to reuse the last fetch instead of re-downloading.

Keys, the TMDB match cache, `overrides.json`, and the library (`library.db`) live
in the `./data` volume, so they persist across restarts. You can also seed the
key via the `TMDB_API_KEY` env var in `docker-compose.yml`.

## Run without Docker (web UI)

```bash
pip install -r requirements.txt
python -m webapp.app          # http://localhost:8080
```

## Command line

The CLI is still available for scripted/one-off runs — see **Setup** and
**Usage** below.

## How it works

TV Time identifies shows by **TheTVDB** id and movies by title only, while
Yamtrack tracks TV and movies by **TMDB** id. This tool bridges the gap:

1. **Parse** the GDPR CSVs into normalized show/movie records.
2. **Resolve** every title to a TMDB id — shows via TMDB's `/find` (exact,
   using the TheTVDB id), movies via a title + year search. Results are cached.
3. **Output** a Yamtrack-native import CSV you upload in the UI
   (*Settings → Import → Yamtrack CSV*), or a portable canonical JSON export.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
```

You need a **TMDB API key** (free): create one at
<https://www.themoviedb.org/settings/api>. Either a v3 key or a v4 read token
works.

Optionally, set a **MyAnimeList Client ID** (`MAL_CLIENT_ID` / `--mal-client-id`,
or the Settings page) to match anime via the official MAL API instead of the
free Jikan mirror — better results and higher rate limits. Register an app at
<https://myanimelist.net/apiconfig> (no OAuth needed for search).

## Usage

Point `--export` at your extracted GDPR folder (the one containing
`tracking-prod-records-v2.csv`). A `.zip` must be unzipped first.

### Convert to a CSV (recommended)

```bash
python migrate.py convert \
  --export "./tv time gdpr data" \
  --out yamtrack_import.csv
```

Then in Yamtrack: **Settings → Import → Yamtrack CSV** and upload the file.

### Build a merged library (multiple sources)

`convert` is a one-shot. To combine several sources and deduplicate, ingest each
into a local library, then export the whole thing:

```bash
python migrate.py ingest --export "./tv time gdpr data"   # add TV Time
# ...ingest other sources into the same --library...
python migrate.py export-library --exporter yamtrack --out yamtrack_import.csv
```

The library is a SQLite file (`--library`, default `library.db`). Titles seen on
more than one source merge into a single entry — union of episodes, highest
progress/score, widest date range. `clear-library` empties it.

Add `--delta` to `export-library` to write only titles added or changed since
this exporter's last export (new episodes, rewatches, status/score). Exporting
advances the baseline, so a follow-up `--delta` starts fresh:

```bash
python migrate.py export-library --exporter yamtrack --out changes.csv --delta
```

### Useful flags

| Flag | Effect |
|------|--------|
| `--no-movies` / `--no-shows` | Migrate only one media type |
| `--no-watchlist` | Skip "planning" items (followed-but-unwatched, to-watch) |
| `--no-ratings` | Don't import star ratings |
| `--no-anime` | Import anime as TV instead of routing to MyAnimeList |
| `-v` | Verbose logging |

## Mapping details

| TV Time | Yamtrack |
|---------|----------|
| Watched episode | `episode` row with watch date (`progressed_at` / `end_date`) |
| Rewatches of an episode | `repeats` |
| Anime (TMDB Animation + Japanese) | Rerouted to Yamtrack `anime` matched on MyAnimeList (not TV) |
| Show fully watched vs partial | `Completed` vs `In progress` (compared against TMDB episode counts) |
| Followed / for-later show, no watches | `Planning` |
| Watched movie | `movie`, `Completed` |
| To-watch movie | `movie`, `Planning` |
| Show rating (1–5) | `score` (×2 → 0–10) |

Movie/episode "ratings" in the export are TV Time **emotion** votes (an emotion
id, not a numeric score) and are intentionally not imported.

## Fixing unmatched titles

Foreign-language titles are matched against TMDB's original title, so most
non-English films resolve automatically. Anything left over is listed on the
result page (with its state, last-watched date, and a direct TMDB search link)
and written to `overrides.template.json` / the report's `overrides_scaffold`.
Fill in each `tmdb_id`, save the file as `overrides.json` (in the `data/` volume
for Docker), and re-run — cached matches are reused, overrides take priority:

```json
{
  "tv:70327": { "tmdb_id": 95, "title": "Buffy the Vampire Slayer",
                "total_episodes": 144, "season_episode_counts": {"1": 12, "2": 22} },
  "movie:some obscure film|2001": { "tmdb_id": 12345, "title": "Some Obscure Film" }
}
```

Keys are `tv:<tvdb_id>` (or `tvname:<lowercase name>`) and
`movie:<lowercase name>|<year>`. Re-run — cached matches are reused, overrides
take priority.

## Files produced

- `yamtrack_import.csv` — the import file (convert / export-library)
- `library.db` — the local deduplicated library (SQLite; ingest/export-library)
- `tmdb_cache.json` — resolution cache (safe to keep; makes re-runs instant)
- `migration_report.json` — match stats and unmatched list

## Crunchyroll (beta)

Imports your Crunchyroll watch history as Yamtrack **anime** (source
MyAnimeList), which is the right media type for anime — unlike the TV Time path,
which forces anime through TMDB's TV numbering.

1. On the main page pick **Crunchyroll**.
2. Paste your **`etp_rt` cookie**: log in at crunchyroll.com, open DevTools →
   Application (Chrome) / Storage (Firefox) → Cookies → `https://www.crunchyroll.com`,
   and copy the value of `etp_rt`. It's used only for the run and never stored.
3. Run — it fetches your history, matches each series to MyAnimeList (via the
   free Jikan API, no key), and produces anime rows (CSV or JSON).

Notes and caveats:

- **Beta.** The auth + history flow matches the actively-maintained
  `crunchyexporter-cli` and `crunchyroll-downloader` projects (public web client
  `noaihdevm_6iyg0a8l0q`, `etp_rt_cookie` grant, `/content/v2/{account}/watch-history`).
  Crunchyroll's API is private, so if auth starts failing, grab a fresh `etp_rt`
  (it expires with your browser session); the client id and endpoints live at the
  top of `yamtrack_importer/crunchyroll.py` if Crunchyroll ever rotates them.
- Titles are matched to MAL by name (Crunchyroll doesn't expose MAL ids).
  Unmatched series appear on the result page with a MAL search link and an
  `overrides.json` scaffold (`anime:<title>` → `{"mal_id": …}`).
- Progress is the count of distinct watched episodes; a series is marked
  Completed only when Crunchyroll reports you've seen every episode.

## Adding a new source

The app is organized around a source-plugin layer in
`yamtrack_importer/sources/`. To add one:

1. Subclass `Source` (see `sources/tvtime.py`), declaring its `SourceInfo`
   (id, label, inputs, and the Yamtrack metadata provider it resolves against —
   `tmdb` for TV/movies, `igdb` for games, etc.).
2. Implement `build(files, resolver, options)` to return `(rows, report)` using
   the shared `build_records` helpers and a resolver.
3. Register it in `sources/registry.py`.

The other services in the roadmap are already registered as `planned` so they
appear in the UI. TMDB-based ones (Netflix, HBO Max, Apple TV, Globo Play) only
need a parser plus title+year matching; game sources need an IGDB resolver;
Komga/Kavita need a manga/book resolver.

## Contributing & releasing

Changes go through **pull requests**. On every PR (and push to `main`) the
[CI workflow](.github/workflows/ci.yml) byte-compiles the code and runs an
import/route smoke test — doc-only changes are skipped. CI never builds or
publishes the Docker image.

The image is published (by [docker-publish.yml](.github/workflows/docker-publish.yml))
only when you **cut a release** or trigger it **manually** — so ordinary commits
never rebuild it or move `:latest`. Versioning is semver via git tags:

```bash
git tag v1.0.0
git push origin v1.0.0
```

That publishes `ghcr.io/reneabreu/yamtrack-importer` tagged `1.0.0`, `1.0`,
`latest`, and `sha-<commit>`. To force a rebuild without a new version, run the
**Publish Docker image** workflow from the Actions tab (Run workflow); its
optional `tag` input defaults to `latest`.

## Notes

- The CSV import format is verified against Yamtrack's own importer. Yamtrack has
  no media-create REST API, so the CSV upload is the supported bulk-import path
  (and the only one that preserves progress, score, rewatches, and dates).
- Nothing is sent anywhere except TMDB and MyAnimeList/Jikan (for matching). Your
  export never leaves your machine otherwise, and the output file stays local.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — PRs welcome, CI runs on every PR.

## License

[MIT](LICENSE) © Rene Abreu. Not affiliated with Yamtrack, TV Time, Crunchyroll,
TMDB, or MyAnimeList.
