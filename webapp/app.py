"""Flask web UI for migrating third-party data into Yamtrack.

Pick a source, upload its export, and either download a Yamtrack import CSV or
push directly to the Yamtrack API. Long-running work happens on a background
thread and streams live progress to the browser over Server-Sent Events.
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
)

from yamtrack_importer.core.library import Library
from yamtrack_importer.core.pipeline import export_library, run_with_library
from yamtrack_importer.exporters.registry import DEFAULT_EXPORTER, all_exporters, get_exporter
from yamtrack_importer.mal import MALResolver
from yamtrack_importer.resolve import TMDBResolver
from yamtrack_importer.sources.registry import all_sources, get_source

from . import config, jobs


def _build_providers(settings: dict) -> dict:
    """Provider clients the resolution layer uses. MAL (Jikan) needs no key."""
    providers: dict = {}
    tmdb_key = settings.get("tmdb_key", "")
    if tmdb_key:
        providers["tmdb"] = TMDBResolver(
            api_key=tmdb_key, cache_path=config.CACHE_PATH, overrides_path=config.OVERRIDES_PATH
        )
    mal_cache = os.path.join(os.path.dirname(config.CACHE_PATH) or ".", "mal_cache.json")
    providers["mal"] = MALResolver(cache_path=mal_cache, overrides_path=config.OVERRIDES_PATH)
    return providers

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "yamtrack-importer-dev-key")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024

# Secrets kept only in process memory (never written to disk), cleared on restart.
# Lets you paste the Crunchyroll cookie once and refresh all session.
_SESSION_SECRETS: dict[str, str] = {}


@app.route("/")
def index():
    settings = config.load_settings()
    return render_template(
        "index.html",
        sources=[s.info for s in all_sources()],
        exporters=[e.info for e in all_exporters()],
        default_exporter=DEFAULT_EXPORTER,
        has_tmdb=bool(settings.get("tmdb_key")),
        cr_cookie_remembered=bool(_SESSION_SECRETS.get("crunchyroll_etp_rt")),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings_view():
    if request.method == "POST":
        config.save_settings({"tmdb_key": request.form.get("tmdb_key", "")})
        flash("Settings saved.", "ok")
        return redirect(url_for("settings_view"))

    settings = config.load_settings()
    return render_template(
        "settings.html",
        tmdb_key=settings.get("tmdb_key", ""),
        masked=config.masked,
    )


@app.route("/overrides", methods=["POST"])
def save_overrides():
    """Save manually-entered ids for unmatched titles into overrides.json."""
    keys = request.form.getlist("ovr_key")
    ids = request.form.getlist("ovr_id")
    titles = request.form.getlist("ovr_title")

    config.ensure_data_dir()
    data = {}
    if os.path.exists(config.OVERRIDES_PATH):
        try:
            with open(config.OVERRIDES_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            data = {}

    saved = 0
    for key, raw_id, title in zip(keys, ids, titles):
        raw_id = (raw_id or "").strip()
        if not raw_id:
            continue
        try:
            num = int(raw_id)
        except ValueError:
            continue
        if key.startswith("anime:"):
            data[key] = {"mal_id": num, "title": title}
        else:
            data[key] = {"tmdb_id": num, "title": title}
        saved += 1

    tmp = config.OVERRIDES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, config.OVERRIDES_PATH)

    if saved:
        flash(f"Saved {saved} override(s). Re-run the migration to apply them.", "ok")
    else:
        flash("No valid ids entered.", "err")
    return redirect(url_for("index"))


def _collect_inputs(source, work_dir: str) -> dict[str, str]:
    """Gather each source input: a path for file uploads (.zip auto-extracted),
    or the submitted string for text/password fields."""
    inputs: dict[str, str] = {}
    for inp in source.info.inputs:
        field = f"input__{inp.key}"
        if inp.is_file:
            uploaded = request.files.get(field)
            if not uploaded or not uploaded.filename:
                if inp.required:
                    raise ValueError(f"Missing required upload: {inp.label}")
                continue
            raw_path = os.path.join(work_dir, os.path.basename(uploaded.filename))
            uploaded.save(raw_path)
            if raw_path.lower().endswith(".zip"):
                extract_dir = os.path.join(work_dir, inp.key + "_extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(raw_path) as zf:
                    zf.extractall(extract_dir)
                inputs[inp.key] = extract_dir
            else:
                inputs[inp.key] = raw_path
        else:
            value = (request.form.get(field) or "").strip()
            if not value and inp.required:
                raise ValueError(f"Missing required field: {inp.label}")
            inputs[inp.key] = value
    return inputs


@app.route("/start", methods=["POST"])
def start():
    """Accept the upload + options, launch a background job, return its id."""
    source_id = request.form.get("source", "")
    mode = request.form.get("mode", "csv")
    exporter_id = request.form.get("exporter", DEFAULT_EXPORTER)
    dry_run = bool(request.form.get("dry_run"))
    try:
        source = get_source(source_id)
    except KeyError:
        return jsonify(error="Unknown source."), 400
    if not source.info.ready:
        return jsonify(error=f"{source.info.label} is not available yet."), 400
    try:
        exporter = get_exporter(exporter_id)
    except KeyError:
        return jsonify(error="Unknown destination."), 400
    if mode == "push" and "api" not in exporter.info.modes:
        return jsonify(error=f"{exporter.info.label} has no API mode — choose a file download."), 400

    settings = config.load_settings()
    options = {
        "include_shows": bool(request.form.get("include_shows")),
        "include_movies": bool(request.form.get("include_movies")),
        "include_watchlist": bool(request.form.get("include_watchlist")),
        "include_ratings": bool(request.form.get("include_ratings")),
        "include_anime_as_anime": bool(request.form.get("include_anime_as_anime")),
    }

    work_dir = tempfile.mkdtemp(prefix="yamimport_")
    try:
        files = _collect_inputs(source, work_dir)
    except (ValueError, zipfile.BadZipFile) as exc:
        return jsonify(error=str(exc)), 400

    # Crunchyroll: remember the cookie in memory; resolve the effective one.
    if source_id == "crunchyroll":
        typed = (files.get("etp_rt") or "").strip()
        if typed:
            _SESSION_SECRETS["crunchyroll_etp_rt"] = typed
        if request.form.get("cr_reuse"):
            files["etp_rt"] = ""  # source will use the cached fetch
        else:
            files["etp_rt"] = typed or _SESSION_SECRETS.get("crunchyroll_etp_rt", "")
            if not files["etp_rt"]:
                return jsonify(
                    error="Paste your Crunchyroll etp_rt cookie, or tick ‘Reuse last fetch’."
                ), 400

    job = jobs.create_job()

    def worker(job):
        _run_migration(job, source, files, settings, options, mode, dry_run, work_dir, exporter_id)

    jobs.run_async(job, worker)
    return jsonify(job_id=job.id)


def _run_migration(job, source, files, settings, options, mode, dry_run, work_dir, exporter_id):
    job.source_label = source.info.label
    job.mode = mode
    exporter = get_exporter(exporter_id)

    # A TMDB key is only needed if this exporter resolves any source type via TMDB.
    reqs = exporter.requirements()
    needs_tmdb = any(reqs.get(t) == "tmdb" for t in source.info.media_types)
    if needs_tmdb and not settings.get("tmdb_key"):
        raise RuntimeError("A TMDB API key is required. Set it on the Settings page.")

    providers = _build_providers(settings)
    options = {**options, "data_dir": config.DATA_DIR}

    if mode == "csv":
        # Ingest this source into the persistent library (dedup/merge), then
        # export the whole library so the file reflects every source combined.
        library = Library(config.LIBRARY_PATH)
        try:
            rows, report = run_with_library(
                library, source, files, options, exporter, providers, progress=job.emit
            )
        finally:
            library.close()
        ext = exporter.info.output_ext
        out_path = os.path.join(work_dir, f"library_{exporter.info.id}_import.{ext}")
        exporter.write(rows, out_path)
        job.csv_path = out_path
        job.download_name = f"library_{exporter.info.id}.{ext}"
        job.download_mime = exporter.info.output_mime
        job.summary = {"mode": "csv", "report": report, "download": True}
        job.emit(type="log", msg=f"Wrote {len(rows)} records. Ready to download.")
        return

    from yamtrack_importer.core.pipeline import run as run_pipeline
    rows, report = run_pipeline(source, files, options, exporter, providers, progress=job.emit)

    # push
    if "api" not in exporter.info.modes:
        raise RuntimeError(f"{exporter.info.label} has no API mode — use a file download.")
    if not dry_run:
        ok, detail = exporter.check_connection(settings)
        if not ok:
            raise RuntimeError(
                f"Could not connect to {exporter.info.label}: {detail}. "
                "If it's on Tailscale, this container isn't on your tailnet — "
                "see the Tailscale section of the README."
            )
    job.emit(type="log", msg=("Dry run — resolving only, nothing will be written."
                              if dry_run else f"Pushing to {exporter.info.label}…"))
    push_stats = exporter.push(rows, settings, dry_run=dry_run, progress=job.emit)
    job.summary = {"mode": "push", "report": report, "download": False, "push": push_stats}


@app.route("/progress/<job_id>")
def progress(job_id):
    job = jobs.get_job(job_id)
    if not job:
        return jsonify(error="Unknown job."), 404

    @stream_with_context
    def stream():
        while True:
            event = job.events.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(stream(), mimetype="text/event-stream", headers=headers)


@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get_job(job_id)
    if job and job.csv_path and os.path.exists(job.csv_path):
        path, name, mime = job.csv_path, job.download_name, job.download_mime
    else:
        rec = jobs.get_record(job_id)
        path = jobs.record_csv_path(job_id)
        name = (rec or {}).get("download_name", "yamtrack_import.csv")
        mime = (rec or {}).get("mime", "text/csv")
    if not path or not os.path.exists(path):
        flash("Nothing to download (run expired?).", "err")
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True, download_name=name, mimetype=mime)


@app.route("/result/<job_id>")
def result(job_id):
    job = jobs.get_job(job_id)
    if job and job.summary:
        summary = job.summary
        download_ok = bool(summary.get("download"))
    else:
        rec = jobs.get_record(job_id)
        if not rec:
            flash("Result not available.", "err")
            return redirect(url_for("index"))
        summary = rec["summary"]
        download_ok = jobs.record_csv_path(job_id) is not None
    return render_template(
        "result.html",
        report=summary["report"],
        push=summary.get("push"),
        mode=summary["mode"],
        job_id=job_id,
        download=download_ok,
    )


@app.route("/history")
def history():
    from datetime import datetime

    records = []
    for rec in jobs.list_history():
        r = rec.get("summary", {}).get("report", {})
        records.append({
            "id": rec["id"],
            "source": rec.get("source", "?"),
            "mode": rec.get("mode", ""),
            "when": datetime.fromtimestamp(rec.get("created", 0)).strftime("%Y-%m-%d %H:%M"),
            "rows": r.get("rows", 0),
            "matched": r.get("shows_matched", 0) + r.get("movies_matched", 0),
            "total": r.get("shows_total", 0) + r.get("movies_total", 0),
            "has_csv": bool(rec.get("csv")),
        })
    return render_template("history.html", records=records)


@app.route("/library")
def library_view():
    """Show the merged local library — every source deduped into one collection."""
    library = Library(config.LIBRARY_PATH)
    try:
        items = library.all_items()
        counts = library.counts_by_type()
        total = library.count()
    finally:
        library.close()
    # Reuse the canonical exporter's per-title summary for the review table.
    json_exp = get_exporter("json")
    details = json_exp.details(json_exp.build(items))
    # provenance chips per title (type+title -> sources)
    prov = {(it.media_type.value, it.title): it.sources for it in items}
    for d in details:
        d["sources"] = prov.get((d["type"], d["title"]), [])
    return render_template(
        "library.html",
        details=details, counts=counts, total=total,
        exporters=[e.info for e in all_exporters()],
    )


@app.route("/library/export/<exporter_id>")
def library_export(exporter_id):
    try:
        exporter = get_exporter(exporter_id)
    except KeyError:
        flash("Unknown destination.", "err")
        return redirect(url_for("library_view"))
    library = Library(config.LIBRARY_PATH)
    try:
        rows, _ = export_library(library, exporter)
    finally:
        library.close()
    if not rows:
        flash("Library is empty — run an import first.", "err")
        return redirect(url_for("library_view"))
    ext = exporter.info.output_ext
    out_dir = tempfile.mkdtemp(prefix="yamlib_")
    out_path = os.path.join(out_dir, f"library_{exporter.info.id}.{ext}")
    exporter.write(rows, out_path)
    return send_file(out_path, as_attachment=True,
                     download_name=f"library_{exporter.info.id}.{ext}",
                     mimetype=exporter.info.output_mime)


@app.route("/library/clear", methods=["POST"])
def library_clear():
    library = Library(config.LIBRARY_PATH)
    try:
        n = library.clear()
    finally:
        library.close()
    flash(f"Cleared the library ({n} title(s) removed).", "ok")
    return redirect(url_for("library_view"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True, threaded=True)
