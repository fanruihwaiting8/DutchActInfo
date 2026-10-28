"""Validate the generated dataset before it gets committed/deployed.

Exits non-zero when something looks broken, so a bad scrape never reaches
GitHub Pages. Run with: python tools/check_data.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

from common import DATA_DIR, WEB_DIR, read_json

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_EVENTS = 200
# The dataset is clipped to a drivable radius, so the far-flung provinces
# (Groningen, Drenthe, Limburg) legitimately drop out.
MIN_PROVINCES = 6
MIN_RECOMMENDED = 100
TRAVEL_TIERS = {"near", "hour", "ninety", "far", "unknown"}
WITHIN_90 = {"near", "hour", "ninety"}
# Events are no longer dropped when they sit far from the default centre, so
# the ceiling only has to cover the longest drive inside the Netherlands.
MAX_TRAVEL_MINUTES = 300
# web/places.js feeds the postcode box and the per-event travel guides.
MIN_POSTCODES = 3000
MIN_GUIDE_CITIES = 500
MIN_PARKING_CITIES = 100


def fail(problems: list[str], message: str) -> None:
    problems.append(message)


def main() -> int:
    problems: list[str] = []
    events_path = os.path.join(DATA_DIR, "events.json")
    data_js = os.path.join(WEB_DIR, "data.js")

    if not os.path.exists(events_path):
        print(f"missing {events_path}")
        return 1
    if not os.path.exists(data_js):
        print(f"missing {data_js}")
        return 1

    payload = read_json(events_path, {})
    events = payload.get("events") or []

    if len(events) < MIN_EVENTS:
        fail(problems, f"only {len(events)} events (expected at least {MIN_EVENTS})")

    window = payload.get("window") or {}
    start, end = window.get("from", ""), window.get("to", "")
    if not (ISO.match(start) and ISO.match(end)) or start >= end:
        fail(problems, f"bad window {window!r}")

    provinces = {event.get("province") for event in events if event.get("province")}
    if len(provinces) < MIN_PROVINCES:
        fail(problems, f"only {len(provinces)} provinces represented: {sorted(provinces)}")

    categories = {event.get("category") for event in events}
    if not categories or categories == {"other"}:
        fail(problems, f"suspicious categories {categories!r}")

    home = payload.get("home") or {}
    if not home.get("city"):
        fail(problems, "payload has no home city")

    recommended = sum(1 for event in events
                      if event.get("travel") in WITHIN_90 and not event.get("local"))
    if recommended < MIN_RECOMMENDED:
        fail(problems, f"only {recommended} events within 90 minutes of {home.get('city')} "
                       f"(expected at least {MIN_RECOMMENDED})")

    seen_ids: set[str] = set()
    for event in events:
        label = event.get("title") or event.get("url") or "<untitled>"
        if not event.get("title"):
            fail(problems, f"event without title: {event.get('url')}")
        if not event.get("city") or not event.get("province"):
            fail(problems, f"event without city/province: {label}")
        dates = event.get("dates") or []
        if not dates:
            fail(problems, f"event without dates: {label}")
        for date in dates:
            if not ISO.match(str(date)):
                fail(problems, f"bad date {date!r} on {label}")
                continue
            if not (start <= date <= end):
                fail(problems, f"date {date} outside window on {label}")
            if dt.date.fromisoformat(date).weekday() not in (4, 5, 6):
                fail(problems, f"date {date} is not Fri/Sat/Sun on {label}")
        tier = event.get("travel")
        if tier not in TRAVEL_TIERS:
            fail(problems, f"unknown travel tier {tier!r} on {label}")
        minutes = event.get("travel_minutes")
        if minutes is not None and (not isinstance(minutes, int) or minutes > MAX_TRAVEL_MINUTES):
            fail(problems, f"travel_minutes {minutes!r} out of range on {label}")
        if not isinstance(event.get("local"), bool):
            fail(problems, f"local flag missing on {label}")
        if not isinstance(event.get("seasonal"), bool):
            fail(problems, f"seasonal flag missing on {label}")
        event_id = event.get("id")
        if event_id in seen_ids:
            fail(problems, f"duplicate id {event_id} on {label}")
        seen_ids.add(event_id)
        if len(problems) > 20:
            break

    with open(data_js, encoding="utf-8") as handle:
        head = handle.read(400)
    if "window.ACTIVITY_DATA" not in head:
        fail(problems, "web/data.js does not assign window.ACTIVITY_DATA")

    # The postcode centre and the travel guides both read web/places.js, so a
    # missing or truncated file would silently disable those features.
    places_js = os.path.join(WEB_DIR, "places.js")
    places = {}
    if not os.path.exists(places_js):
        fail(problems, "web/places.js is missing - run tools/build_places.py")
    else:
        with open(places_js, encoding="utf-8") as handle:
            body = handle.read()
        marker = "window.ACTIVITY_PLACES = "
        start_at = body.find(marker)
        if start_at < 0:
            fail(problems, "web/places.js does not assign window.ACTIVITY_PLACES")
        else:
            try:
                places = json.loads(body[start_at + len(marker):].strip().rstrip(";"))
            except ValueError as error:
                fail(problems, f"web/places.js is not valid JSON: {error}")
    if places:
        if len(places.get("postcodes") or {}) < MIN_POSTCODES:
            fail(problems, f"only {len(places.get('postcodes') or {})} postcodes in web/places.js")
        guide_cities = places.get("cities") or {}
        if len(guide_cities) < MIN_GUIDE_CITIES:
            fail(problems, f"only {len(guide_cities)} cities in web/places.js")
        with_parking = sum(1 for row in guide_cities.values() if len(row) > 4 and row[4])
        if with_parking < MIN_PARKING_CITIES:
            fail(problems, f"only {with_parking} cities carry car parks in web/places.js")
        for name, row in guide_cities.items():
            lots = row[4] if len(row) > 4 else []
            metres = [lot[3] for lot in lots]
            if metres != sorted(metres):
                fail(problems, f"car parks for {name} are not sorted nearest first")
                break
            if any(len(lot) < 4 for lot in lots):
                fail(problems, f"a car park for {name} is missing its price or distance")
                break

    if problems:
        print("dataset validation FAILED:")
        for problem in problems[:20]:
            print(f"  - {problem}")
        return 1

    print(f"dataset OK: {len(events)} events ({recommended} recommended within 90 min of "
          f"{home.get('city')}), {len(provinces)} provinces, window {start}..{end}, "
          f"categories {sorted(c for c in categories if c)}, "
          f"{sum(1 for e in events if e.get('seasonal'))} seasonal")
    return 0


if __name__ == "__main__":
    sys.exit(main())