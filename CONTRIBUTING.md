# Contributing

Thanks for your interest in improving Yamtrack Importer! Contributions —
new sources, bug fixes, docs — are welcome.

## Workflow

1. Fork and create a branch off `main`.
2. Make your change (see **Local development** below).
3. Open a **pull request**. CI byte-compiles the code and runs an import/route
   smoke test on every PR; doc-only changes skip CI. The Docker image is never
   built from a PR — it's only published on a release (see **Releasing**).

Keep PRs focused, and update `README.md` / `ROADMAP.md` when behavior changes and
add a note under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).

## Local development

```bash
pip install -r requirements.txt
python -m webapp.app        # web UI at http://localhost:8080
```

Prefer Docker? Use the live-reload override — it mounts your working tree and
auto-reloads on edits (no rebuild):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Note: the default `docker compose up` pulls the **published** image from ghcr,
which won't include your uncommitted changes — use the dev (or build) override
above to run local code.

Run the same checks CI runs before pushing:

```bash
python -m compileall -q migrate.py yamtrack_importer webapp
DATA_DIR=/tmp/yi-dev python - <<'PY'
import webapp.app as app
from yamtrack_importer.sources.registry import all_sources
ids = [s.info.id for s in all_sources()]
assert "tvtime" in ids and "crunchyroll" in ids
c = app.app.test_client()
assert all(c.get(p).status_code == 200 for p in ("/", "/history", "/settings"))
print("ok:", ids)
PY
```

No network is needed for these checks — resolvers and source clients are only
contacted at runtime, and tests stub them.

## Project layout

The app is a **canonical import/export pipeline**: sources produce neutral
`MediaItem`s, a resolution layer fills in the ids the chosen exporter needs, and
exporters write the destination's format. Sources and exporters are independent
plugins — add or remove one without touching the rest.

```
yamtrack_importer/
  core/
    model.py            # canonical MediaItem / Status / EpisodeWatch
    resolve_service.py  # enrich items with exporter-required ids (TMDB/MAL)
    pipeline.py         # source -> resolve -> exporter; builds report/details
  sources/              # IMPORT modules: Source.fetch() -> [MediaItem]  (+ registry)
    tvtime.py, crunchyroll.py
  exporters/            # EXPORT modules: consume [MediaItem]  (+ registry)
    yamtrack.py         # canonical -> Yamtrack rows (CSV/API)
  resolve.py / mal.py   # provider clients (TMDB, MyAnimeList via Jikan)
  parse.py              # TV Time export parsing
  crunchyroll.py        # Crunchyroll watch-history client
webapp/                 # Flask UI (routes, jobs, templates)
migrate.py              # CLI entry point
```

- **Add a source**: subclass `Source`, implement `fetch(inputs, options, progress)
  -> list[MediaItem]`, register in `sources/registry.py`.
- **Add an exporter**: subclass `Exporter`, declare `requires` (media_type → id
  provider) and `media_types`, implement `build()/write_csv()/push()`, register
  in `exporters/registry.py`.

## Adding a source

Sources are small plugins under `yamtrack_importer/sources/`. See
[README → Adding a new source](README.md#adding-a-new-source) for the steps, and
`sources/tvtime.py` / `sources/crunchyroll.py` as references. Register new
sources in `sources/registry.py`.

## Style

- Standard library + the deps in `requirements.txt`; avoid adding dependencies
  unless necessary.
- Keep functions small and readable; match the surrounding style.
- Never commit secrets, exports, or generated data — `.gitignore` already covers
  `.env`, `data/`, caches, and `overrides.json`.

## Releasing (maintainers)

Versioning is semver via git tags. Tagging publishes the multi-arch image to
`ghcr.io/reneabreu/yamtrack-importer`:

```bash
git tag v1.0.0
git push origin v1.0.0     # -> tags 1.0.0, 1.0, latest, sha-<commit>
```

To rebuild `latest` without a new version, run the **Publish Docker image**
workflow manually from the Actions tab.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
