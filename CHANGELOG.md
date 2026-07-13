# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> On release, move the **Unreleased** items into a new `## [X.Y.Z] - YYYY-MM-DD`
> section and tag the commit `vX.Y.Z` (see [CONTRIBUTING](CONTRIBUTING.md#releasing-maintainers)).

## [Unreleased]

### Added

- **Local library with cross-source dedup**: every import is ingested into a
  persistent SQLite library (`library.db` in the data volume) keyed by canonical
  id (TMDB for screen media, MAL for anime). A title seen on more than one source
  (e.g. an anime on both TV Time and Crunchyroll) merges into one entry —
  union of episodes, highest progress/score, widest date range, unioned
  provenance — instead of duplicating. A **Library** page browses the merged
  collection and re-exports it (CSV/JSON) or clears it; CLI adds `ingest`,
  `export-library`, and `clear-library`. Exports are built from the whole library.

### Changed

- **Modular import/export architecture**: sources (imports) and exporters
  (destinations) are now independent plugins over a neutral canonical model, so
  either can be added or removed without touching the core.

### Removed

- **Yamtrack "Push to API" mode** and its `YamtrackClient`, Test-connection
  route, and Yamtrack URL/key settings. Yamtrack has no media-create REST API —
  only the CSV upload preserves progress, score, rewatches, and dates — so
  Yamtrack is now a file/CSV-only destination.

### Added

- Self-hosted **web app** (Flask) and **CLI** to import media watch history into
  [Yamtrack](https://github.com/FuzzyGrim/Yamtrack), with a source-plugin
  architecture (TV Time and Crunchyroll implemented; 11 more registered as
  planned).
- **TV Time**: TheTVDB→TMDB resolution for watched shows/episodes (with dates and
  rewatches), movies, watchlist, and ratings. Episodes are validated against
  TMDB's season structure to avoid import 404s.
- **Anime auto-routing**: shows TMDB flags as Animation + Japanese origin are
  imported as Yamtrack `anime` (matched to MyAnimeList via Jikan) instead of TV.
- **Crunchyroll**: `etp_rt` cookie auth + paginated watch history → anime rows
  matched to MyAnimeList. The raw fetch is cached and the cookie is remembered
  in process memory for the session.
- **Exporters**: Yamtrack-native CSV export (verified against Yamtrack's
  importer) and a portable **canonical JSON** export, with live SSE progress.
- **Result tooling**: in-web override editor for unmatched titles (writes
  `overrides.json`; bare ids self-enrich), and persistent run **History** with
  re-view / re-download.
- **Docker**: multi-arch (amd64/arm64) image on GitHub Container Registry,
  `docker-compose.yml` (pull) + build override, and a Tailscale sidecar compose.
- **Project**: GitHub Actions CI on PRs, release-gated image publishing, MIT
  license, and a contributing guide.

[Unreleased]: https://github.com/reneabreu/yamtrack-importer/commits/main
