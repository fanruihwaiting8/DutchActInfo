"""Shared helpers for DutchActivityInfo scrapers (standard library only)."""

from __future__ import annotations

import gzip
import html
import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
WEB_DIR = os.path.join(ROOT, "web")


def _contexts():
    """Verified context first, then an unverified fallback.

    Some local Python builds (python.org installers on macOS) ship without a
    usable CA bundle. CI runners are fine, so we only fall back when needed.
    """
    yield ssl.create_default_context()
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    yield unverified


def fetch(url: str, retries: int = 3, timeout: int = 30) -> str:
    """Download a URL and return decoded text, or raise the last error."""
    last_error: Exception | None = None
    for attempt in range(retries):
        for ctx in _contexts():
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "nl,en;q=0.8",
                    "Accept-Encoding": "gzip",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return raw.decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as error:
                last_error = error
                if isinstance(error, urllib.error.HTTPError) and error.code in (404, 410):
                    raise
        time.sleep(1.5 * (attempt + 1) + random.random())
    raise last_error if last_error else RuntimeError("fetch failed: " + url)


def polite_sleep(seconds: float = 1.0) -> None:
    time.sleep(seconds + random.random() * 0.5)


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Strip tags/entities and collapse whitespace."""
    if not value:
        return ""
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")


def read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def normalise_city(name: str) -> str:
    """Lowercase key used to match city names across sources."""
    text = clean_text(name).lower()
    text = text.replace("'", "'").replace("`", "'")
    text = re.sub(r"\s*\(.*?\)\s*", " ", text)
    text = re.sub(r"[^a-z0-9àáâäèéêëìíîïòóôöùúûüçñ' -]", " ", text)
    return WS_RE.sub(" ", text).strip()