"""Collect Dutch weekend activities for this month and next month.

Writes:
    data/events.json  - machine readable dataset
    web/data.js       - same payload inlined so the page works offline / file://

Usage:
    python3 tools/fetch_events.py              # full refresh
    python3 tools/fetch_events.py --limit-days 3   # quick smoke test
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import sys

from common import DATA_DIR, WEB_DIR, clean_text, normalise_city, polite_sleep, read_json, write_json
from sources import SOURCE_META, cabaretinfo_day, festivalinfo_page, podiuminfo_day

WEEKEND = (4, 5, 6)  # Friday, Saturday, Sunday
MAX_FESTIVAL_PAGES = 12
MAX_PER_DAY_PER_SOURCE = 400

CITY_ALIASES = {
    "s-hertogenbosch": "den bosch",
    "'s-hertogenbosch": "den bosch",
    "'s hertogenbosch": "den bosch",
    "hertogenbosch": "den bosch",
    "the hague": "den haag",
    "'s-gravenhage": "den haag",
    "s-gravenhage": "den haag",
    "la haye": "den haag",
    "amsterdam-noord": "amsterdam",
    "amsterdam noord": "amsterdam",
    "amsterdam zuidoost": "amsterdam",
    "amsterdam-zuidoost": "amsterdam",
    "rotterdam-zuid": "rotterdam",
    "hoek van holland": "rotterdam",
    "den haag-scheveningen": "scheveningen",
}


def month_window(today: dt.date) -> tuple[dt.date, dt.date]:
    """First day of the current month .. last day of next month."""
    start = today.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    if next_month.month == 12:
        following = next_month.replace(year=next_month.year + 1, month=1)
    else:
        following = next_month.replace(month=next_month.month + 1)
    return start, following - dt.timedelta(days=1)


def weekend_days(start: dt.date, end: dt.date) -> list[dt.date]:
    days, cursor = [], start
    while cursor <= end:
        if cursor.weekday() in WEEKEND:
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    return days


def parse_date(value: str) -> dt.date | None:
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


class CityIndex:
    def __init__(self, payload: dict | None):
        payload = payload or {}
        self.cities: dict[str, dict] = payload.get("cities", {})
        self.provinces: list[str] = payload.get("provinces", [])

    def lookup(self, raw_city: str) -> dict | None:
        key = normalise_city(raw_city)
        if not key:
            return None
        for candidate in (key, CITY_ALIASES.get(key, ""), key.split(" - ")[0].strip()):
            if candidate and candidate in self.cities:
                return self.cities[candidate]
        return None


def event_id(url: str, title: str, start: str) -> str:
    seed = url or f"{title}|{start}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def collect_festivals(window_start: dt.date, window_end: dt.date, log) -> list[dict]:
    collected: list[dict] = []
    for page in range(MAX_FESTIVAL_PAGES):
        try:
            rows = festivalinfo_page(page)
        except Exception as error:  # noqa: BLE001
            log(f"[warn] festivalinfo page {page}: {error}")
            break
        if not rows:
            log(f"festivalinfo page {page}: 0 rows, stopping")
            break
        starts = [parse_date(row["start"]) for row in rows]
        starts = [value for value in starts if value]
        collected.extend(rows)
        log(f"festivalinfo page {page}: {len(rows)} rows")
        if starts and min(starts) > window_end:
            break
        polite_sleep(1.0)
    return collected


def collect_day_sources(days: list[dt.date], log) -> list[dict]:
    collected: list[dict] = []
    for day in days:
        iso = day.isoformat()
        for label, loader in (("podiuminfo", podiuminfo_day), ("cabaretinfo", cabaretinfo_day)):
            try:
                rows = loader(iso)
            except Exception as error:  # noqa: BLE001
                log(f"[warn] {label} {iso}: {error}")
                continue
            log(f"{label} {iso}: {len(rows)} rows")
            collected.extend(rows[:MAX_PER_DAY_PER_SOURCE])
            polite_sleep(0.8)
    return collected


def normalise(rows: list[dict], cities: CityIndex, weekend_set: set[str],
              window_start: dt.date, window_end: dt.date, log) -> list[dict]:
    merged: dict[str, dict] = {}
    skipped_foreign = skipped_window = 0

    for row in rows:
        start = parse_date(row.get("start", ""))
        if not start:
            continue
        end = parse_date(row.get("end", "")) or start
        if end < start:
            end = start
        if end < window_start or start > window_end:
            skipped_window += 1
            continue

        country = (row.get("country") or "").upper()
        place = cities.lookup(row.get("city", ""))
        if country and country not in ("NL", "NETHERLANDS", "NEDERLAND"):
            skipped_foreign += 1
            continue
        if not place:
            skipped_foreign += 1
            continue

        # keep only the weekend dates this event actually covers
        dates, cursor = [], max(start, window_start)
        last = min(end, window_end)
        while cursor <= last:
            if cursor.isoformat() in weekend_set:
                dates.append(cursor.isoformat())
            cursor += dt.timedelta(days=1)
        if not dates:
            skipped_window += 1
            continue

        source = row.get("source", "")
        key = row.get("url") or f"{row.get('title')}|{dates[0]}"
        record = merged.get(key)
        if record:
            record["dates"] = sorted(set(record["dates"]) | set(dates))
            continue

        title = clean_text(row.get("title"))
        venue = clean_text(row.get("venue"))
        if venue.lower() == title.lower():
            venue = ""
        description = clean_text(row.get("description"))
        if len(description) > 240:
            description = description[:237].rstrip() + "..."

        merged[key] = {
            "id": event_id(row.get("url", ""), row.get("title", ""), dates[0]),
            "title": title,
            "url": row.get("url", ""),
            "image": row.get("image", ""),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "dates": dates,
            "time": row.get("time", ""),
            "city": place["name"],
            "province": place["province"],
            "venue": venue,
            "description": description,
            "performers": (row.get("performers") or [])[:8],
            "category": SOURCE_META.get(source, {}).get("category", "other"),
            "source": source,
        }

    log(f"kept {len(merged)} events (skipped {skipped_foreign} non-NL, {skipped_window} out of window)")
    return sorted(merged.values(), key=lambda item: (item["dates"][0], item["city"], item["title"]))


def build_payload(events: list[dict], window_start: dt.date, window_end: dt.date,
                  weekends: list[dt.date], cities: CityIndex) -> dict:
    counts: dict[str, int] = {}
    for event in events:
        counts[event["source"]] = counts.get(event["source"], 0) + 1
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"from": window_start.isoformat(), "to": window_end.isoformat()},
        "weekend_days": [day.isoformat() for day in weekends],
        "provinces": cities.provinces,
        "sources": [
            {
                "id": key,
                "name": meta["name"],
                "site": meta["site"],
                "category": meta["category"],
                "count": counts.get(key, 0),
            }
            for key, meta in SOURCE_META.items()
        ],
        "total": len(events),
        "events": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Dutch weekend activities")
    parser.add_argument("--limit-days", type=int, default=0,
                        help="only scrape the first N weekend days (smoke test)")
    parser.add_argument("--skip-festivals", action="store_true")
    parser.add_argument("--today", default="", help="override today's date (YYYY-MM-DD)")
    args = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    today = parse_date(args.today) or dt.date.today()
    window_start, window_end = month_window(today)
    weekends = weekend_days(window_start, window_end)
    upcoming = [day for day in weekends if day >= today]
    scrape_days = upcoming[: args.limit_days] if args.limit_days else upcoming
    log(f"window {window_start} .. {window_end}; {len(weekends)} weekend days, scraping {len(scrape_days)}")

    cities = CityIndex(read_json(os.path.join(DATA_DIR, "cities_nl.json")))
    if not cities.cities:
        log("[error] data/cities_nl.json missing - run tools/build_cities.py first")
        return 1

    rows: list[dict] = []
    if not args.skip_festivals:
        rows += collect_festivals(window_start, window_end, log)
    rows += collect_day_sources(scrape_days, log)
    log(f"raw rows: {len(rows)}")

    weekend_set = {day.isoformat() for day in weekends}
    events = normalise(rows, cities, weekend_set, window_start, window_end, log)
    if not events:
        log("[error] no events collected, keeping the previous dataset")
        return 1

    payload = build_payload(events, window_start, window_end, weekends, cities)
    json_path = os.path.join(DATA_DIR, "events.json")
    write_json(json_path, payload)

    os.makedirs(WEB_DIR, exist_ok=True)
    js_path = os.path.join(WEB_DIR, "data.js")
    with open(json_path, encoding="utf-8") as handle:
        body = handle.read().strip()
    with open(js_path, "w", encoding="utf-8") as handle:
        handle.write("// Generated by tools/fetch_events.py - do not edit by hand.\n")
        handle.write("window.ACTIVITY_DATA = ")
        handle.write(body)
        handle.write(";\n")

    log(f"wrote {len(events)} events -> {json_path} and {js_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())