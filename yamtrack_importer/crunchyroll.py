"""Minimal Crunchyroll watch-history client.

Authenticates with the browser ``etp_rt`` session cookie (Crunchyroll dropped
password login) and pages through the account's watch history. The flow and the
public web-client credentials below are the same ones used by the open-source
crunchyexporter-cli and crunchyroll-downloader tools; update the constants here
if Crunchyroll ever rotates them.

No password is used or stored. The etp_rt cookie expires with the browser
session; if auth returns 401, grab a fresh cookie.
"""

from __future__ import annotations

import logging
import uuid

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://www.crunchyroll.com"
# Public web client (Basic auth). Widely documented in CR open-source tools.
CLIENT_ID = "noaihdevm_6iyg0a8l0q"
CLIENT_SECRET = ""  # public client — no secret


class CrunchyrollError(RuntimeError):
    pass


class CrunchyrollClient:
    def __init__(self, etp_rt: str, locale: str = "en-US"):
        if not etp_rt or not etp_rt.strip():
            raise CrunchyrollError("Missing Crunchyroll etp_rt cookie.")
        self.etp_rt = etp_rt.strip()
        self.locale = locale
        self.device_id = str(uuid.uuid4())
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"
        )
        self.access_token: str | None = None
        self.account_id: str | None = None

    def authenticate(self) -> None:
        try:
            resp = self.session.post(
                f"{API_BASE}/auth/v1/token",
                auth=(CLIENT_ID, CLIENT_SECRET),
                cookies={"etp_rt": self.etp_rt, "device_id": self.device_id},
                data={
                    "grant_type": "etp_rt_cookie",
                    "scope": "offline_access",
                    "device_id": self.device_id,
                    "device_name": "yamtrack-importer",
                    "device_type": "com.crunchyroll.desktop",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise CrunchyrollError(f"Could not reach Crunchyroll: {exc}") from exc
        if resp.status_code == 401:
            raise CrunchyrollError(
                "Crunchyroll rejected the etp_rt cookie (401). Get a fresh cookie "
                "from your browser (DevTools → Application → Cookies → etp_rt)."
            )
        if not resp.ok:
            raise CrunchyrollError(
                f"Crunchyroll auth failed (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        self.access_token = resp.json().get("access_token")
        if not self.access_token:
            raise CrunchyrollError("Crunchyroll auth response had no access_token.")
        self.session.headers["Authorization"] = f"Bearer {self.access_token}"
        self.account_id = self._fetch_account_id()

    def _fetch_account_id(self) -> str:
        resp = self.session.get(f"{API_BASE}/accounts/v1/me", timeout=20)
        if not resp.ok:
            raise CrunchyrollError(
                f"Could not read Crunchyroll account (HTTP {resp.status_code})."
            )
        account_id = resp.json().get("account_id") or resp.json().get("external_id")
        if not account_id:
            raise CrunchyrollError("Crunchyroll account response missing account_id.")
        return account_id

    def iter_history(self, page_size: int = 100):
        """Yield raw watch-history items across all pages."""
        if not self.access_token:
            self.authenticate()
        url = f"{API_BASE}/content/v2/{self.account_id}/watch-history"
        page = 1
        while True:
            try:
                resp = self.session.get(
                    url,
                    params={"page_size": page_size, "page": page, "locale": self.locale},
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise CrunchyrollError(f"History request failed: {exc}") from exc
            if not resp.ok:
                raise CrunchyrollError(
                    f"History request failed (HTTP {resp.status_code}): {resp.text[:200]}"
                )
            items = resp.json().get("data") or []
            if not items:
                break
            yield from items
            if len(items) < page_size:
                break
            page += 1
