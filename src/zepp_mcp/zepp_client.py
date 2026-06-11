"""
Zepp Health API client with auto-refreshing auth.

Auth flow (Zepp 2025):
  1. POST AES-encrypted credentials → 303 redirect with access_token
  2. Exchange access_token → app_token + user_id
  3. Cache to ~/.zepp_mcp_token; auto-refresh on 401

Health data endpoints:
  GET api-mifit.huami.com/v1/data/band_data.json  → HR (binary), steps, sleep
  GET api-mifit.zepp.com/users/{id}/events        → native stress scores

Credit: bentasker/zepp_to_influxdb, micw/hacking-mifit-api
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import urllib.parse
import uuid
from pathlib import Path

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ── Auth constants ────────────────────────────────────────────────────────────
_AES_KEY    = b"xeNtBVqzDc6tuNTh"
_AES_IV     = b"MAAAYAAAAAAAAABg"
_URL_TOKENS = "https://api-user-us2.zepp.com/v2/registrations/tokens"
_URL_LOGIN  = "https://api-mifit-us2.zepp.com/v2/client/login"
_CACHE      = Path.home() / ".zepp_mcp_token"

# ── Data endpoints ────────────────────────────────────────────────────────────
_BAND_URL   = "https://api-mifit.huami.com/v1/data/band_data.json"
_EVENTS_URL = "https://api-mifit.zepp.com/users/{uid}/events"


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def _zepp_login(email: str, password: str) -> tuple[str, str]:
    """Full 2-step login → (app_token, user_id)."""
    # Step 1: AES-encrypt credentials, expect 303 redirect with access token
    payload   = urllib.parse.urlencode({
        "emailOrPhone": email, "password": password,
        "state": "REDIRECTION", "client_id": "HuaMi",
        "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
        "region": "us-west-2", "token": ["access", "refresh"], "country_code": "US",
    }, doseq=True).encode()
    encrypted = AES.new(_AES_KEY, AES.MODE_CBC, iv=_AES_IV).encrypt(pad(payload, AES.block_size))

    r = httpx.post(_URL_TOKENS, content=encrypted, follow_redirects=False, timeout=15, headers={
        "app_name": "com.huami.midong", "appname": "com.huami.midong",
        "cv": "151689_9.12.5", "v": "2.0", "appplatform": "android_phone",
        "vb": "202509151347", "vn": "9.12.5", "x-hm-ekv": "1",
        "user-agent": "Zepp/9.12.5 (Pixel 4; Android 12; Density/2.75)",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    if r.status_code != 303:
        raise RuntimeError(f"Zepp login step 1 failed ({r.status_code}): {r.text}")

    qs     = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    access = (qs.get("access") or [None])[0]
    if not access:
        raise RuntimeError(f"No access token in redirect: {r.headers.get('location')}")

    # Step 2: exchange access token for app_token + user_id
    r2 = httpx.post(_URL_LOGIN, timeout=15, data={
        "code": access, "device_id": str(uuid.uuid4()),
        "grant_type": "access_token", "third_name": "huami",
        "app_name": "com.huami.midong", "country_code": "US",
        "device_model": "android_phone", "app_version": "9.12.5",
        "allow_registration": "false", "lang": "en",
        "dn": "api-mifit.zepp.com,api-user.zepp.com,api-watch.zepp.com,auth.zepp.com",
        "source": "com.huami.watch.hmwatchmanager:9.12.5:151689",
    }, headers={
        "app_name": "com.huami.webapp", "appname": "com.huami.webapp",
        "origin": "https://user.zepp.com", "referer": "https://user.zepp.com/",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    })
    if r2.status_code != 200:
        raise RuntimeError(f"Zepp login step 2 failed ({r2.status_code}): {r2.text}")

    info = r2.json().get("token_info", {})
    if not info.get("app_token"):
        raise RuntimeError(f"No app_token in response: {r2.text}")
    return info["app_token"], info["user_id"]


def _load_cache() -> tuple[str, str] | None:
    try:
        d = json.loads(_CACHE.read_text())
        return d["app_token"], d["user_id"]
    except Exception:
        return None


def _save_cache(app_token: str, user_id: str) -> None:
    _CACHE.write_text(json.dumps({"app_token": app_token, "user_id": user_id}))
    _CACHE.chmod(0o600)


def _get_tokens() -> tuple[str, str]:
    """Return tokens from env, cache, or fresh login (in that order)."""
    if os.environ.get("ZEPP_ACCESS_TOKEN") and os.environ.get("ZEPP_USER_ID"):
        return os.environ["ZEPP_ACCESS_TOKEN"], os.environ["ZEPP_USER_ID"]
    if cached := _load_cache():
        return cached
    return _refresh_tokens()


def _refresh_tokens() -> tuple[str, str]:
    email    = os.environ.get("ZEPP_EMAIL")
    password = os.environ.get("ZEPP_PASSWORD")
    if not email or not password:
        raise RuntimeError("Set ZEPP_EMAIL + ZEPP_PASSWORD in your Claude Desktop config.")
    tokens = _zepp_login(email, password)
    _save_cache(*tokens)
    return tokens


# ─────────────────────────────────────────────────────────────────────────────
# API client
# ─────────────────────────────────────────────────────────────────────────────

class ZeppClient:
    def __init__(self):
        self._token, self._uid = _get_tokens()

    def _get(self, url: str, params: dict) -> dict:
        r = httpx.get(url, headers={"apptoken": self._token}, params=params, timeout=20)
        if r.status_code == 401:                       # token expired → auto-refresh
            self._token, self._uid = _refresh_tokens()
            r = httpx.get(url, headers={"apptoken": self._token}, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def _date_range(self, days: int) -> tuple[str, str]:
        end   = datetime.date.today()
        start = end - datetime.timedelta(days=days - 1)
        return start.isoformat(), end.isoformat()

    def _ts_range(self, days: int) -> tuple[str, str]:
        now   = datetime.datetime.now()
        start = datetime.datetime.combine(now.date() - datetime.timedelta(days=days - 1),
                                          datetime.time.min)
        return str(int(start.timestamp() * 1000)), str(int(now.timestamp() * 1000))

    # ── Public methods ──────────────────────────────────────────────────────

    def get_band_data(self, days: int = 7) -> list[dict]:
        """Raw per-day band data: HR blob, steps, sleep."""
        start, end = self._date_range(days)
        data = self._get(_BAND_URL, {
            "query_type": "detail", "device_type": "android_phone",
            "userid": self._uid, "from_date": start, "to_date": end,
        })
        return data.get("data", [])

    def get_stress_events(self, days: int = 7) -> list[dict]:
        """Native per-minute stress scores (0–100) from Amazfit."""
        from_ms, to_ms = self._ts_range(days)
        data = self._get(_EVENTS_URL.format(uid=self._uid), {
            "from": from_ms, "to": to_ms, "eventType": "all_day_stress", "limit": 1000,
        })
        return data.get("items", [])

    def get_heart_rate_readings(self, days: int = 7) -> list[dict]:
        """Decode HR binary blob → list of {date, hour, minute, hr}."""
        readings = []
        for day in self.get_band_data(days):
            readings.extend(_decode_hr_blob(day))
        return readings

    def get_sleep_summaries(self, days: int = 7) -> list[dict]:
        """Decoded sleep + steps per day."""
        result = []
        for day in self.get_band_data(days):
            if "summary" not in day:
                continue
            try:
                s = json.loads(base64.b64decode(day["summary"]))
                result.append({"date": day["date_time"], "sleep": s.get("slp"), "steps": s.get("stp")})
            except Exception:
                pass
        return result


def _decode_hr_blob(day: dict) -> list[dict]:
    """Decode the data_hr blob: 1440 Java shorts → HR per minute."""
    if "data_hr" not in day:
        return []
    blob, readings, b, x, minute = bytearray(base64.b64decode(day["data_hr"])), [], b"", 1, 0
    for byte_i in blob:
        b += byte_i.to_bytes(1, "big")
        x += 1
        if x == 2:
            v = int(b.hex(), 16)
            if v < 200:
                readings.append({"date": day["date_time"], "minute": minute,
                                  "hour": minute // 60, "hr": v})
            b, x, minute = b"", 1, minute + 1
    return readings
