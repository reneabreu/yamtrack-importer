"""Push resolved rows to the Yamtrack REST API.

Yamtrack exposes an API-key protected REST API (Django-Ninja) under
``/api/v1``. Authentication is the key from ``Settings -> Integrations`` sent
in the ``X-api-key`` header. Media is created with:

    POST /api/v1/media/{media_type}/

with a JSON body of the item id/source plus the tracking fields. Existing items
are detected with:

    GET  /api/v1/media/{media_type}/{source}/{media_id}/

so re-runs skip what is already present. The exact field names come straight
from the Yamtrack model (media_id, source, season_number, episode_number,
status, score, progress, start_date, end_date, notes, repeats).
"""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Fields that are meaningful to the API for each row (empty ones are dropped).
_TRACK_FIELDS = (
    "season_number",
    "episode_number",
    "status",
    "score",
    "progress",
    "start_date",
    "end_date",
    "notes",
    "repeats",
    "progressed_at",
)


class YamtrackClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        dry_run: bool = False,
        request_delay: float = 0.1,
    ):
        if not base_url:
            raise ValueError("Yamtrack base URL is required (e.g. https://yamtrack.example.com).")
        if not api_key:
            raise ValueError("A Yamtrack API key is required (Settings -> Integrations).")
        self.base_url = self._normalize(base_url)
        self.dry_run = dry_run
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({"X-api-key": api_key, "Accept": "application/json"})

    @staticmethod
    def _normalize(base_url: str) -> str:
        base_url = base_url.strip().rstrip("/")
        # Default to http:// if no scheme given (common for homelab IP:port).
        if "://" not in base_url:
            base_url = "http://" + base_url
        # Drop a trailing /api or /api/v1 if the user pasted it.
        for suffix in ("/api/v1", "/api"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        return base_url

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    def check_connection(self) -> tuple[bool, str]:
        """Verify the base URL + key. Returns (ok, human-readable detail).

        Does not follow redirects, so an http->https bounce (Django
        SECURE_SSL_REDIRECT or a reverse proxy) is reported instead of being
        chased into a confusing TLS/404 error.
        """
        try:
            resp = self.session.get(
                self._url("/media/movie/"), timeout=20, allow_redirects=False
            )
        except requests.exceptions.SSLError:
            return False, (
                f"TLS error against {self.base_url}. If the server is http-only, "
                "use an http:// URL (not https://)."
            )
        except requests.RequestException as exc:
            return False, f"could not reach {self.base_url} ({type(exc).__name__}: {exc})"

        if resp.status_code in (301, 302, 307, 308):
            loc = resp.headers.get("Location", "?")
            return False, (
                f"server redirected to {loc}. It's likely forcing HTTPS — set the "
                "URL to match (or disable the redirect on Yamtrack)."
            )
        if resp.status_code in (401, 403):
            return False, f"authentication failed (HTTP {resp.status_code}) — check the API key"
        if resp.status_code == 404:
            # Distinguish "wrong URL / API disabled" from "endpoint differs".
            try:
                schema = self.session.get(
                    f"{self.base_url}/api/v1/openapi.json", timeout=15, allow_redirects=False
                )
            except requests.RequestException:
                schema = None
            if schema is None or schema.status_code == 404:
                return False, (
                    f"no Yamtrack API found at {self.base_url}/api/v1 (HTTP 404). "
                    "Check the base URL, or your Yamtrack may predate the REST API — "
                    "use CSV import instead."
                )
            return False, "reached the API but /media/movie/ returned 404 (unexpected)"
        if not resp.ok:
            return False, f"unexpected response HTTP {resp.status_code}"
        return True, "ok"

    def exists(self, media_type: str, source: str, media_id: str) -> bool:
        try:
            resp = self.session.get(
                self._url(f"/media/{media_type}/{source}/{media_id}/"), timeout=20
            )
        except requests.RequestException:
            return False
        return resp.status_code == 200

    def _payload(self, row: dict) -> dict:
        payload = {"media_id": str(row["media_id"]), "source": row.get("source", "tmdb")}
        for field in _TRACK_FIELDS:
            value = row.get(field, "")
            if value == "" or value is None:
                continue
            payload[field] = value
        return payload

    def create(self, row: dict) -> tuple[bool, str]:
        media_type = row["media_type"]
        payload = self._payload(row)
        if self.dry_run:
            return True, f"DRY-RUN {media_type} {payload}"
        last = "no response"
        for attempt in range(4):
            try:
                resp = self.session.post(
                    self._url(f"/media/{media_type}/"), json=payload, timeout=30
                )
            except requests.RequestException as exc:
                time.sleep(1.5 * (attempt + 1))
                last = str(exc)
                continue
            if resp.status_code == 429:
                time.sleep(int(resp.headers.get("Retry-After", "2")) + 1)
                continue
            time.sleep(self.request_delay)
            if resp.ok:
                return True, f"{resp.status_code}"
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code < 500:
                break
        return False, last
