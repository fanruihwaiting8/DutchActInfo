"""Source adapters: festivalinfo.nl, podiuminfo.nl, cabaretinfo.nl.

Every adapter returns a list of raw dicts with these keys:
    title, url, image, start, end, time, city, venue, description,
    performers, country, source
Normalisation, Dutch-city filtering and weekend filtering happen in
fetch_events.py so the adapters stay dumb and easy to repair.
"""

from __future__ import annotations

import json
import re

from common import clean_text, fetch
from museum import MUSEUM_META

JSON_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
ROW_RE = re.compile(
    r'<section\s+class="concert_rows_info[^"]*"[^>]*>(.*?)</section>',
    re.DOTALL | re.IGNORECASE,
)
CELL_RE = {
    "time": re.compile(r'<div class="td_1[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
    "main": re.compile(r'<div class="td_2[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
    "venue": re.compile(r'<div class="td_3[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
    "city": re.compile(r'<div class="td_4[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
}
LINK_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
TIME_RE = re.compile(r"\b([0-2]?\d[:.][0-5]\d)\b")


def _cell(block: str, name: str) -> str:
    match = CELL_RE[name].search(block)
    return match.group(1) if match else ""


# --------------------------------------------------------------------------
# festivalinfo.nl - music festivals, exposes schema.org Festival JSON-LD
# --------------------------------------------------------------------------

FESTIVAL_TYPES = {"festival", "musicevent", "event"}


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _performer_names(value) -> list[str]:
    names = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = clean_text(item.get("name"))
        else:
            name = clean_text(str(item))
        if name and name not in names:
            names.append(name)
    return names[:12]


def _festival_from_ld(node: dict) -> dict | None:
    types = {str(t).lower() for t in _as_list(node.get("@type"))}
    if not types & FESTIVAL_TYPES:
        return None
    url = clean_text(node.get("url")) or clean_text(node.get("@id"))
    title = clean_text(node.get("name"))
    start = clean_text(node.get("startDate"))[:10]
    if not (title and start):
        return None

    city = venue = country = ""
    location = _as_list(node.get("location"))
    if location and isinstance(location[0], dict):
        place = location[0]
        venue = clean_text(place.get("name"))
        address = place.get("address")
        if isinstance(address, dict):
            city = clean_text(address.get("addressLocality"))
            country = clean_text(address.get("addressCountry"))
        elif isinstance(address, str):
            city = clean_text(address)

    image = _as_list(node.get("image"))
    image_url = ""
    for candidate in image:
        if isinstance(candidate, str):
            image_url = clean_text(candidate)
        elif isinstance(candidate,dict):
            image_url = clean_text(candidate.get("url"))
        if image_url:
            break

    return {
        "title": title,
        "url": url,
        "image": image_url,
        "start": start,
        "end": clean_text(node.get("endDate"))[:10] or start,
        "time": "",
        "city": city,
        "venue": venue,
        "country": country,
        "description": clean_text(node.get("description"))[:400],
        "performers": _performer_names(node.get("performer")),
        "source": "festivalinfo",
    }


def festivalinfo_page(page: int) -> list[dict]:
    """One week of festivals; page=0 is the current week, 1 the next, ..."""
    html_text = fetch(f"https://www.festivalinfo.nl/festivals/?page={page}")
    events: list[dict] = []
    for raw in JSON_LD_RE.findall(html_text):
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        for node in _as_list(payload):
            if not isinstance(node, dict) or "@graph" in node:
                continue
            event = _festival_from_ld(node)
            if event:
                events.append(event)
    return events


# --------------------------------------------------------------------------
# podiuminfo.nl / cabaretinfo.nl - identical day-agenda markup
# --------------------------------------------------------------------------


def _agenda_day(host: str, path: str, source: str, date: str) -> list[dict]:
    year, month, day = date.split("-")
    url = f"https://www.{host}/{path}/{year}/{month}/{day}/"
    html_text = fetch(url)
    events: list[dict] = []
    for block in ROW_RE.findall(html_text):
        link = LINK_RE.search(_cell(block, "main"))
        if not link:
            continue
        href, label = link.group(1), clean_text(link.group(2))
        if not label:
            continue
        time_match = TIME_RE.search(clean_text(_cell(block, "time")))
        events.append(
            {
                "title": label,
                "url": clean_text(href),
                "image": "",
                "start": date,
                "end": date,
                "time": time_match.group(1).replace(".", ":") if time_match else "",
                "city": clean_text(_cell(block, "city")),
                "venue": clean_text(_cell(block, "venue")),
                "country": "",
                "description": "",
                "performers": [],
                "source": source,
            }
        )
    return events


def podiuminfo_day(date: str) -> list[dict]:
    return _agenda_day("podiuminfo.nl", "concertagenda", "podiuminfo", date)


def cabaretinfo_day(date: str) -> list[dict]:
    return _agenda_day("cabaretinfo.nl", "cabaretagenda", "cabaretinfo", date)


SOURCE_META = {
    "festivalinfo": {
        "name": "Festivalinfo",
        "site": "https://www.festivalinfo.nl/",
        "category": "festival",
    },
    "podiuminfo": {
        "name": "Podiuminfo",
        "site": "https://www.podiuminfo.nl/",
        "category": "concert",
    },
    "cabaretinfo": {
        "name": "Cabaretinfo",
        "site": "https://www.cabaretinfo.nl/",
        "category": "comedy",
    },
}

# museum.nl lives in its own module because it needs two passes (sitemap plus
# detail pages); the metadata is merged here so the payload keeps one registry.
SOURCE_META.update(MUSEUM_META)