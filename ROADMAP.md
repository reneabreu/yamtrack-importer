# Roadmap

## Anime as anime (not TV) — ✅ done

TV Time tracks anime with **TheTVDB** episode numbering, which rarely lines up
with **TMDB** (different season splits, specials), so those episodes used to get
dropped and the show added as a plain TV entry.

Now: during resolution, shows that TMDB flags as **Animation** with Japanese
origin are rerouted to Yamtrack **`anime`** (source `mal`), matching the title
to MyAnimeList via Jikan — so episode counts map cleanly. Toggle: "Route anime
to MyAnimeList" (on by default; `--no-anime` on the CLI).

Still possible later:

- Absolute-episode remap for multi-cour anime where one TV Time show spans
  several MAL entries (progress is currently capped at the matched entry's
  episode count).
- Prefer a dedicated anime source (Crunchyroll — done; later MAL/AniList export)
  where the data is already anime-native.

## Architecture — canonical import/export core ✅

The project is a neutral pipeline, not a Yamtrack-only tool:

- **Import modules** (`sources/`) produce canonical `MediaItem`s.
- A **resolution layer** enriches items with the ids the chosen exporter needs.
- **Export modules** (`exporters/`) write the destination's format.

Yamtrack (CSV) and a portable **canonical JSON** are the first two exporters.
Others (Trakt, Simkl, or a home-grown tracker) can be added without touching
sources — the foundation for making this the base of a larger media-tracking
system. Destinations with a real create-API can implement the exporter's
`push` path; Yamtrack has no such API, so it stays file-only.

## Local library — cross-source dedup ✅

Sources feed a persistent **SQLite library** (`library.db`) keyed by canonical id
(TMDB for screen media, MAL for anime). Re-importing or importing a second source
merges into existing entries instead of duplicating — union of episodes, highest
progress/score, widest date range, unioned provenance (smart auto-merge). A
**Library** page browses/exports/clears it; the CLI has `ingest` /
`export-library` / `clear-library`.

Exports can be **full** or **delta** ("changes only"): each destination snapshots
the library when it exports, so the next delta contains just the titles added or
changed since (new episodes, rewatches, status/score). Baselines are per-exporter.

Anime matching uses the **official MyAnimeList API** when a Client ID is set,
falling back to the keyless **Jikan** mirror otherwise.

Still possible later:

- Per-title conflict review UI (choose a winner when sources disagree) as an
  alternative to the automatic merge.
- Manual edits and removals of library entries from the web UI.
- Source-priority overrides (e.g. always prefer Crunchyroll's data for anime).
- MAL as a first-class OAuth source/exporter (read/write a user's anime list
  directly), building on the official-API client.

## Standalone tracker (long-term)

The library is already a canonical, deduplicated store of watch history — the
hard part of a tracker. The natural next step is to make it usable *on its own*,
so exporting to Yamtrack (or anything else) becomes optional rather than the
point:

- **Read/write library UI** — edit, add, and remove entries directly (statuses,
  scores, progress, mark episodes watched), not just import + export.
- **Views** — currently-watching, up-next, planning, per-type dashboards, and
  history/stats over the library.
- **Yamtrack becomes one exporter among many** — keep the import/export seams so
  you can still sync out, but nothing depends on Yamtrack being present.
- **Prerequisites** deferred until it's a hosted tracker rather than a local
  tool: app **login** (Basic Auth via env) and optional **at-rest encryption**
  of `library.db` (SQLCipher). Skipped for now — behind Tailscale + filesystem
  permissions the local file is sufficient.

This is exploratory: the modular core is deliberately destination-agnostic so
this can grow incrementally without a rewrite.

## Sources

| Source | Status | Yamtrack type | Matching |
|--------|--------|---------------|----------|
| TV Time | ✅ ready | tv, movie | TheTVDB id → TMDB |
| Crunchyroll | 🧪 beta | anime | title → MAL (Jikan) |
| Netflix | planned | tv, movie | title + year → TMDB |
| HBO Max | planned | tv, movie | title + year → TMDB |
| Apple TV | planned | tv, movie | title + year → TMDB |
| Globo Play | planned | tv, movie | title + year → TMDB |
| Xbox | planned | game | → IGDB |
| Nintendo | planned | game | → IGDB |
| RetroAchievements | planned | game | → IGDB |
| Google Play Games | planned | game | → IGDB |
| Komga | planned | manga/comic/book | Komga API |
| Kavita | planned | manga/comic/book | Kavita API |

## Other ideas

- Absolute-episode remap for anime coming through the TV Time (TMDB) path, as a
  fallback when a dedicated anime source isn't used.
- Real create-API exporters (e.g. Trakt/Simkl) over the exporter `push` seam.
- A one-click "write overrides.json" editor in the result page.
