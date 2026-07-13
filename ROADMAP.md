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

Yamtrack is the first exporter. Others (Trakt, Simkl, plain JSON, or a
home-grown tracker) can be added as exporters without touching sources — the
foundation for making this the base of a larger media-tracking system.

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
- Background/queued pushes so large API imports don't tie up a request.
- A one-click "write overrides.json" editor in the result page.
