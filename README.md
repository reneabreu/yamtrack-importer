# Yamtrack Migrate

Migrate your media history from other services into
[Yamtrack](https://github.com/FuzzyGrim/Yamtrack). Runs as a **Docker web app**
(pick a source, upload an export, download a CSV or push to the API) or as a
**command-line tool**.

**TV Time** is fully supported today — watched TV episodes (with dates and
rewatches), watched movies, watchlist items, and show ratings. TV Time shuts
down on **15 July 2026**, so export your data first at
<https://gdpr.tvtime.com/gdpr/self-service>.

More sources are on the roadmap (the app is built around a source-plugin
architecture): Crunchyroll, Netflix, Globo Play, HBO Max, Apple TV, Xbox,
Nintendo, RetroAchievements, Google Play Games, Komga, and Kavita.

## Run with Docker (web UI)

```bash
docker compose up -d --build
# open http://localhost:8080
```

1. Go to **Settings** and paste your **TMDB API key** (free at
   [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)). For
   direct API import, also add your **Yamtrack URL + API key**.
2. On the main page pick **TV Time**, upload your GDPR `.zip`, choose to
   **download a CSV** (recommended) or **push to the API**, and run.

The run streams **live progress** — a progress bar plus a console log — while it
resolves titles and imports, so a large library that takes a few minutes shows
exactly what it's doing.

Every run is saved under **History** (in the data volume): re-open a past
summary or re-download its CSV without reprocessing. Unmatched titles can be
fixed right on the result page — paste the correct TMDB/MAL id and Save (writes
`overrides.json` for you), then re-run. For Crunchyroll, leave the `etp_rt`
field blank on a re-run to reuse the last fetch instead of re-downloading.

Keys, the TMDB match cache, and `overrides.json` live in the `./data` volume, so
they persist across restarts. You can also seed keys via the `TMDB_API_KEY` /
`YAMTRACK_URL` / `YAMTRACK_API_KEY` env vars in `docker-compose.yml`.

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
3. **Output** either a Yamtrack import CSV or a direct REST API import.

Two output modes:

- **`convert`** — writes a Yamtrack-native CSV you upload in the UI
  (*Settings → Import → Yamtrack CSV*). This is the most robust path and is
  recommended for the first run.
- **`push`** — sends each item to the Yamtrack REST API with your API key.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
```

You need a **TMDB API key** (free): create one at
<https://www.themoviedb.org/settings/api>. Either a v3 key or a v4 read token
works. For `push` you also need your Yamtrack URL and the API key from
*Yamtrack → Settings → Integrations*.

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

### Push via the API

```bash
python migrate.py push \
  --export "./tv time gdpr data" \
  --yamtrack-url https://yamtrack.example.com

# preview first without writing anything:
python migrate.py push --export "./tv time gdpr data" --dry-run
```

The push command checks whether each show/movie already exists and skips it, so
it is safe to re-run.

### Useful flags

| Flag | Effect |
|------|--------|
| `--no-movies` / `--no-shows` | Migrate only one media type |
| `--no-watchlist` | Skip "planning" items (followed-but-unwatched, to-watch) |
| `--no-ratings` | Don't import star ratings |
| `--dry-run` | (push) resolve and print, but don't POST |
| `--no-skip-existing` | (push) re-import items already in Yamtrack |
| `-v` | Verbose logging |

## Mapping details

| TV Time | Yamtrack |
|---------|----------|
| Watched episode | `episode` row with watch date (`progressed_at` / `end_date`) |
| Rewatches of an episode | `repeats` (API push only) |
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

- `yamtrack_import.csv` — the import file (convert mode)
- `tmdb_cache.json` — resolution cache (safe to keep; makes re-runs instant)
- `migration_report.json` — match stats and unmatched list
- `push_failures.log` — any API errors (push mode)

## Reaching a Yamtrack that's on Tailscale

If Yamtrack is only reachable over Tailscale (a `100.x.y.z` IP or a `*.ts.net`
name), the **API push won't work from a normal container** — Docker Desktop /
OrbStack run containers in a VM that isn't on your tailnet, so there's no route
to `100.x`. (The **Settings → Test Yamtrack connection** button will tell you if
this is the problem.) Pick one:

- **Easiest — download the CSV instead.** CSV mode never contacts Yamtrack. Grab
  the CSV from the web app and upload it via *Yamtrack → Settings → Import*.
- **Run the push on your Mac**, which is already on Tailscale:

  ```bash
  pip install -r requirements.txt
  python migrate.py push --export ./tvtime_extracted \
    --tmdb-key YOUR_TMDB_KEY \
    --yamtrack-url http://100.x.y.z:PORT --yamtrack-key YOUR_YT_KEY
  ```

  (`--export` wants the unzipped folder — unzip your GDPR `.zip` first.)
- **Keep the containerized web push** by joining the container to your tailnet
  with the included sidecar compose:

  ```bash
  echo "TS_AUTHKEY=tskey-auth-xxxx" >> .env   # from the Tailscale admin console
  docker compose -f docker-compose.tailscale.yml up -d --build
  ```

  The app becomes a device on your tailnet, so `http://100.x.y.z:PORT` resolves
  and routes. Open the UI at <http://localhost:8080> as usual.

## Crunchyroll (beta)

Imports your Crunchyroll watch history as Yamtrack **anime** (source
MyAnimeList), which is the right media type for anime — unlike the TV Time path,
which forces anime through TMDB's TV numbering.

1. On the main page pick **Crunchyroll**.
2. Paste your **`etp_rt` cookie**: log in at crunchyroll.com, open DevTools →
   Application (Chrome) / Storage (Firefox) → Cookies → `https://www.crunchyroll.com`,
   and copy the value of `etp_rt`. It's used only for the run and never stored.
3. Run — it fetches your history, matches each series to MyAnimeList (via the
   free Jikan API, no key), and produces anime rows (CSV or API push).

Notes and caveats:

- **Beta.** The auth + history flow matches the actively-maintained
  `crunchyexporter-cli` and `crunchyroll-downloader` projects (public web client
  `noaihdevm_6iyg0a8l0q`, `etp_rt_cookie` grant, `/content/v2/{account}/watch-history`).
  Crunchyroll's API is private, so if auth starts failing, grab a fresh `etp_rt`
  (it expires with your browser session); the client id and endpoints live at the
  top of `tvtime2yamtrack/crunchyroll.py` if Crunchyroll ever rotates them.
- Titles are matched to MAL by name (Crunchyroll doesn't expose MAL ids).
  Unmatched series appear on the result page with a MAL search link and an
  `overrides.json` scaffold (`anime:<title>` → `{"mal_id": …}`).
- Progress is the count of distinct watched episodes; a series is marked
  Completed only when Crunchyroll reports you've seen every episode.

## Adding a new source

The app is organized around a source-plugin layer in
`tvtime2yamtrack/sources/`. To add one:

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

## Notes

- The CSV import format is verified against Yamtrack's own importer. The REST
  API path targets the documented `/api/v1` endpoints; if your Yamtrack version
  differs, prefer the CSV path.
- A direct API push of a large library makes thousands of calls and can take a
  while; the CSV path is faster for big imports. (The container runs gunicorn
  with no request timeout to accommodate long pushes.)
- Nothing is sent anywhere except TMDB (for matching) and your own Yamtrack
  instance. Your export never leaves your machine otherwise.
