"""In-memory background jobs + persistent run history.

Each job runs the full migration on a worker thread and pushes progress events
to a queue that an SSE endpoint drains. On completion the run (its summary and
generated CSV) is persisted under the data volume so it can be re-viewed and
re-downloaded later — no need to reprocess to look at a previous result.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import uuid

from . import config

# job_id -> Job (in-memory, for live/streaming runs)
_JOBS: dict[str, "Job"] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 20

HISTORY_DIR = os.path.join(config.DATA_DIR, "history")
_MAX_HISTORY = 50


class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.events: queue.Queue = queue.Queue()
        self.status = "running"           # running | done | error
        self.created = time.time()
        self.source_label = ""
        self.mode = "csv"
        self.csv_path: str | None = None  # set for csv mode when finished
        self.summary: dict | None = None  # report + push stats
        self.error: str | None = None

    def emit(self, **event) -> None:
        self.events.put(event)


def create_job() -> Job:
    job = Job()
    with _LOCK:
        if len(_JOBS) >= _MAX_JOBS:
            for jid in sorted(_JOBS, key=lambda k: _JOBS[k].created):
                if _JOBS[jid].status != "running":
                    del _JOBS[jid]
                if len(_JOBS) < _MAX_JOBS:
                    break
        _JOBS[job.id] = job
    return job


def get_job(job_id: str) -> "Job | None":
    return _JOBS.get(job_id)


def run_async(job: Job, target) -> None:
    """Run ``target(job)`` on a daemon thread, capturing success/failure."""

    def _wrap():
        try:
            target(job)
            job.status = "done"
            _persist(job)
            job.emit(type="done", summary=job.summary or {})
        except Exception as exc:  # surfaced to the browser via the stream
            job.status = "error"
            job.error = str(exc)
            job.emit(type="error", msg=str(exc))

    threading.Thread(target=_wrap, daemon=True).start()


# ---- persistence -----------------------------------------------------

def _persist(job: Job) -> None:
    if not job.summary:
        return
    try:
        rec_dir = os.path.join(HISTORY_DIR, job.id)
        os.makedirs(rec_dir, exist_ok=True)
        meta = {
            "id": job.id,
            "created": job.created,
            "source": job.source_label,
            "mode": job.mode,
            "summary": job.summary,
            "csv": None,
        }
        if job.csv_path and os.path.exists(job.csv_path):
            dest = os.path.join(rec_dir, "import.csv")
            shutil.copyfile(job.csv_path, dest)
            meta["csv"] = "import.csv"
        with open(os.path.join(rec_dir, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        _prune_history()
    except OSError:
        pass  # history is best-effort; never fail a run over it


def _prune_history() -> None:
    records = _list_dirs()
    for rec in records[_MAX_HISTORY:]:
        shutil.rmtree(os.path.join(HISTORY_DIR, rec), ignore_errors=True)


def _list_dirs() -> list[str]:
    if not os.path.isdir(HISTORY_DIR):
        return []
    dirs = [d for d in os.listdir(HISTORY_DIR)
            if os.path.isfile(os.path.join(HISTORY_DIR, d, "meta.json"))]
    return sorted(dirs, key=lambda d: _meta_created(d), reverse=True)


def _meta_created(rec_id: str) -> float:
    try:
        return get_record(rec_id).get("created", 0)
    except Exception:
        return 0


def get_record(rec_id: str) -> dict | None:
    path = os.path.join(HISTORY_DIR, rec_id, "meta.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def record_csv_path(rec_id: str) -> str | None:
    rec = get_record(rec_id)
    if rec and rec.get("csv"):
        path = os.path.join(HISTORY_DIR, rec_id, rec["csv"])
        if os.path.exists(path):
            return path
    return None


def list_history() -> list[dict]:
    out = []
    for rec_id in _list_dirs():
        rec = get_record(rec_id)
        if rec:
            out.append(rec)
    return out
