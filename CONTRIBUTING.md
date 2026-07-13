# Contributing

Thanks for your interest in improving Yamtrack Importer! Contributions —
new sources, bug fixes, docs — are welcome.

## Workflow

1. Fork and create a branch off `main`.
2. Make your change (see **Local development** below).
3. Open a **pull request**. CI byte-compiles the code and runs an import/route
   smoke test on every PR; doc-only changes skip CI. The Docker image is never
   built from a PR — it's only published on a release (see **Releasing**).

Keep PRs focused, and update the `README.md` / `ROADMAP.md` when behavior changes.

## Local development

```bash
pip install -r requirements.txt
python -m webapp.app        # web UI at http://localhost:8080
```

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

```
yamtrack_importer/        # core package
  parse.py                # TV Time export parsing
  resolve.py / mal.py     # TMDB / MyAnimeList (Jikan) resolvers
  build_records.py        # -> Yamtrack rows (CSV + API shape)
  pipeline.py             # parse -> resolve -> rows, with anime rerouting
  api_client.py           # Yamtrack REST client
  crunchyroll.py          # Crunchyroll watch-history client
  sources/                # source plugins + registry
webapp/                   # Flask UI (routes, jobs, templates)
migrate.py                # CLI entry point
```

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
