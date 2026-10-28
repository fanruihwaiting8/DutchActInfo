"""museum.nl adapter: art exhibitions and museum events.

museum.nl has no usable agenda page (the "what's on" view is a client side
app with no API we may call), but it publishes a complete sitemap and every
detail page embeds a schema.org Event object. So the plan is:

    sitemap.xml  ->  detail page  ->  embedded schema.org JSON  ->  row

Two sources come out of it:
    museum_expo   /<museum>/tentoonstelling/<slug>   -> category "expo"
    museum_event  /<museum>/{activiteit,evenement,workshop,lezing,
                             rondleiding}/<slug>     -> category "museum"

Permanent displays (schema startDate years ago, no end date anywhere) are
dropped: they are not weekend news and they would bury the dated events.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import re

from common import clean_text, fetch, polite_sleep

SITEMAP_URL = "https://www.museum.nl/sitemap.xml"
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
KIND_RE = re.compile(r"museum\.nl/(?:nl|en)/[^/]+/([^/]+)/", re.IGNORECASE)
SCRIPT_JSON_RE = re.compile(r"<script[^>]*>\s*(\{.*?\})\s*</script>", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EXPO_KIND = "tentoonstelling"
EVENT_KINDS = ("activiteit", "evenement", "workshop", "lezing", "rondleiding")
# Anything already running before the window and lasting longer than this is a
# permanent display rather than a dated activity.
MAX_RUN_DAYS = 365

DUTCH_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mrt": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dec": 12,
}
TM_RE = re.compile(
    r"(?:t/m|tot en met)\s+(\d{1,2})\s+([a-z]+)\.?\s+(20\d\d)",
    re.IGNORECASE,
)

MUSEUM_META = {
    "museum_expo": {
        "name": "Museum.nl exhibitions",
        "site": "https://www.museum.nl/",
        "category": "expo",
    },
    "museum_event": {
        "name": "Museum.nl museum events",
        "site": "https://www.museum.nl/",
        "category": "museum",
    },
}


def _kind(url: str) -> str:
    match = KIND_RE.search(url)
    return match.group(1).lower() if match else ""


def sitemap_urls() -> tuple[list[str], list[str]]:
    """All exhibition URLs and all museum-event URLs, Dutch pages only."""
    xml_text = fetch(SITEMAP_URL)
    expos: list[str] = []
    events: list[str] = []
    seen: set[str] = set()
    for loc in LOC_RE.findall(xml_text):
        url = html.unescape(loc.strip())
        if "/en/" in url or url in seen:
            continue
        seen.add(url)
        kind = _kind(url)
        if kind == EXPO_KIND:
            expos.append(url)
        elif kind in EVENT_KINDS:
            events.append(url)
    return expos, events


def _schema_event(page: str) -> dict | None:
    """The schema.org Event object museum.nl inlines in a plain <script>."""
    for raw in SCRIPT_JSON_RE.findall(page):
        if '"@type"' not in raw:
            continue
        try:
            node = json.loads(html.unescape(raw))
        except ValueError:
            continue
        if not isinstance(node, dict):
            continue
        if "event" in str(node.get("@type", "")).lower():
            return node
    return None


def _tm_date(page: str) -> str:
    """Fallback end date from body copy like "t/m 11 januari 2027"."""
    text = TAG_RE.sub(" ", page)
    for day, month_name, year in TM_RE.findall(text):
        month = DUTCH_MONTHS.get(month_name.lower())
        if not month:
            continue
        try:
            return dt.date(int(year), month, int(day)).isoformat()
        except ValueError:
            continue
    return ""


def _first_url(value) -> str:
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, str) and item.strip():
            return clean_text(item)
        if isinstance(item, dict):
            found = clean_text(item.get("url") or item.get("contentUrl"))
            if found:
                return found
    return ""


def _parse_iso(value: str) -> dt.date | None:
    value = clean_text(value)[:10]
    if not ISO_DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def detail_row(url: str, source: str, window_start: dt.date,
               window_end: dt.date) -> dict | None:
    page = fetch(url)
    node = _schema_event(page)
    if not node:
        return None

    title = clean_text(node.get("name"))
    start = _parse_iso(node.get("startDate", ""))
    if not (title and start):
        return None

    end = _parse_iso(node.get("endDate", "")) or _parse_iso(_tm_date(page))
    if not end:
        # No end date at all: only meaningful if it opens inside the window,
        # otherwise it is a permanent display.
        if start < window_start:
            return None
        end = start
    if end < start:
        end = start
    if end < window_start or start > window_end:
        return None
    # A run of more than a year that was already going before the window is a
    # permanent collection display or a standing tour, not weekend news.
    if start < window_start and (end - start).days > MAX_RUN_DAYS:
        return None

    location = node.get("location")
    location = location[0] if isinstance(location, list) and location else location
    venue = city = ""
    if isinstance(location, dict):
        venue = clean_text(location.get("name"))
        address = location.get("address")
        if isinstance(address, dict):
            city = clean_text(address.get("addressLocality"))
        elif isinstance(address, str):
            city = clean_text(address)
    if not venue:
        organizer = node.get("organizer")
        organizer = organizer[0] if isinstance(organizer, list) and organizer else organizer
        if isinstance(organizer, dict):
            venue = clean_text(organizer.get("name"))
    if not city:
        return None

    return {
        "title": title,
        "url": clean_text(node.get("url")) or url,
        "image": _first_url(node.get("image")),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "time": "",
        "city": city,
        "venue": venue,
        "country": "NL",
        "description": clean_text(node.get("description"))[:400],
        "performers": [],
        "source": source,
    }


def _slice(urls: list[str], limit: int) -> list[str]:
    return urls[:limit] if limit else urls


def collect_museum(window_start: dt.date, window_end: dt.date, log,
                   limit: int = 0, workers: int = 3) -> list[dict]:
    """Every exhibition / museum event that touches the window."""
    try:
        expos, events = sitemap_urls()
    except Exception as error:  # noqa: BLE001
        log(f"[warn] museum.nl sitemap: {error}")
        return []
    log(f"museum.nl sitemap: {len(expos)} exhibitions, {len(events)} museum events")

    per_kind = (limit + 1) // 2 if limit else 0
    tasks = [(url, "museum_expo") for url in _slice(expos, per_kind)]
    tasks += [(url, "museum_event") for url in _slice(events, per_kind)]
    log(f"museum.nl: fetching {len(tasks)} detail pages with {workers} workers")

    rows: list[dict] = []
    failed = 0
    done = 0

    def work(task):
        url, source = task
        polite_sleep(0.2)
        try:
            return detail_row(url, source, window_start, window_end)
        except Exception as error:  # noqa: BLE001
            return error

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(work, tasks):
            done += 1
            if isinstance(result, dict):
                rows.append(result)
            elif isinstance(result, Exception):
                failed += 1
                if failed <= 5:
                    log(f"[warn] museum.nl detail: {result}")
            if done % 200 == 0:
                log(f"museum.nl: {done}/{len(tasks)} pages, {len(rows)} in window")

    log(f"museum.nl: {len(rows)} rows inside the window ({failed} failed)")
    return rows