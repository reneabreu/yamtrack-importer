# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> On release, move the **Unreleased** items into a new `## [X.Y.Z] - YYYY-MM-DD`
> section and tag the commit `vX.Y.Z` (see [CONTRIBUTING](CONTRIBUTING.md#releasing-maintainers)).

## [Unreleased]

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
- **Output**: Yamtrack-native CSV export (verified against Yamtrack's importer)
  and direct REST API push, both with live SSE progress and connection
  diagnostics.
- **Result tooling**: in-web override editor for unmatched titles (writes
  `overrides.json`; bare ids self-enrich), and persistent run **History** with
  re-view / re-download.
- **Docker**: multi-arch (amd64/arm64) image on GitHub Container Registry,
  `docker-compose.yml` (pull) + build override, and a Tailscale sidecar compose.
- **Project**: GitHub Actions CI on PRs, release-gated image publishing, MIT
  license, and a contributing guide.

[Unreleased]: https://github.com/reneabreu/yamtrack-importer/commits/main
