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

from yamtrack_importer.api_client import YamtrackClient
from yamtrack_importer.build_records import summarize_rows
from yamtrack_importer.csv_writer import write_csv
from yamtrack_importer.resolvers import get_resolver
from yamtrack_importer.sources.registry import all_sources, get_source

from . import config, jobs

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
        has_tmdb=bool(settings.get("tmdb_key")),
        has_yamtrack=bool(settings.get("yamtrack_url") and settings.get("yamtrack_key")),
        cr_cookie_remembered=bool(_SESSION_SECRETS.get("crunchyroll_etp_rt")),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings_view():
    if request.method == "POST":
        config.save_settings(
            {
                "tmdb_key": request.form.get("tmdb_key", ""),
                "yamtrack_url": request.form.get("yamtrack_url", ""),
                "yamtrack_key": request.form.get("yamtrack_key", ""),
            }
        )
        flash("Settings saved.", "ok")
        return redirect(url_for("settings_view"))

    settings = config.load_settings()
    return render_template(
        "settings.html",
        tmdb_key=settings.get("tmdb_key", ""),
        yamtrack_url=settings.get("yamtrack_url", ""),
        yamtrack_key=settings.get("yamtrack_key", ""),
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


@app.route("/test-connection", methods=["POST"])
def test_connection():
    settings = config.load_settings()
    if not (settings.get("yamtrack_url") and settings.get("yamtrack_key")):
        return jsonify(ok=False, detail="Set the Yamtrack URL and API key first, then save.")
    client = YamtrackClient(settings["yamtrack_url"], settings["yamtrack_key"])
    ok, detail = client.check_connection()
    return jsonify(ok=ok, detail=detail)


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
    dry_run = bool(request.form.get("dry_run"))
    try:
        source = get_source(source_id)
    except KeyError:
        return jsonify(error="Unknown source."), 400
    if not source.info.ready:
        return jsonify(error=f"{source.info.label} is not available yet."), 400

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

    if mode == "push" and not dry_run and not (
        settings.get("yamtrack_url") and settings.get("yamtrack_key")
    ):
        return jsonify(error="Set your Yamtrack URL and API key on the Settings page first."), 400

    job = jobs.create_job()

    def worker(job):
        _run_migration(job, source, files, settings, options, mode, dry_run, work_dir)

    jobs.run_async(job, worker)
    return jsonify(job_id=job.id)


def _run_migration(job, source, files, settings, options, mode, dry_run, work_dir):
    job.source_label = source.info.label
    job.mode = mode
    resolver = get_resolver(
        source.info.metadata_provider, settings, config.CACHE_PATH, config.OVERRIDES_PATH
    )
    rows, report = source.build(files, resolver, options, progress=job.emit)
    report["details"] = summarize_rows(rows)  # per-title review data

    if mode == "csv":
        out_path = os.path.join(work_dir, f"{source.info.id}_yamtrack_import.csv")
        write_csv(rows, out_path)
        job.csv_path = out_path
        job.summary = {"mode": "csv", "report": report, "download": True}
        job.emit(type="log", msg=f"Wrote {len(rows)} rows to CSV. Ready to download.")
        return

    # push
    client = YamtrackClient(
        base_url=settings.get("yamtrack_url", ""),
        api_key=settings.get("yamtrack_key", ""),
        dry_run=dry_run,
    )
    if not dry_run:
        ok, detail = client.check_connection()
        if not ok:
            raise RuntimeError(
                f"Could not connect to Yamtrack: {detail}. "
                "If Yamtrack is on Tailscale, this container isn't on your tailnet — "
                "see the Tailscale section of the README."
            )

    job.emit(type="log", msg=("Dry run — resolving only, nothing will be written."
                              if dry_run else "Pushing to Yamtrack…"))
    total = len(rows)
    job.emit(type="progress", phase="push", current=0, total=total)
    created = skipped = failed = 0
    failures: list[str] = []
    for i, row in enumerate(rows, 1):
        mt, src, mid = row["media_type"], row.get("source", "tmdb"), str(row["media_id"])
        if not dry_run and mt in ("tv", "movie") and client.exists(mt, src, mid):
            skipped += 1
        else:
            ok, msg = client.create(row)
            if ok:
                created += 1
            else:
                failed += 1
                if len(failures) < 100:
                    failures.append(f"{mt} {mid}: {msg}")
                    job.emit(type="log", msg=f"  ✗ {mt} {mid}: {msg}")
        if i % 25 == 0 or i == total:
            job.emit(type="progress", phase="push", current=i, total=total)

    job.summary = {
        "mode": "push",
        "report": report,
        "download": False,
        "push": {
            "created": created,
            "skipped": skipped,
            "failed": failed,
            "dry_run": dry_run,
            "failures": failures,
        },
    }
    job.emit(type="log", msg=f"Done. created={created} skipped={skipped} failed={failed}")


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
    path = job.csv_path if (job and job.csv_path) else jobs.record_csv_path(job_id)
    if not path or not os.path.exists(path):
        flash("Nothing to download (run expired?).", "err")
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True, download_name="yamtrack_import.csv",
                     mimetype="text/csv")


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True, threaded=True)
