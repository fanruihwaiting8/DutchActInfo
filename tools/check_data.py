"""Validate the generated dataset before it gets committed/deployed.

Exits non-zero when something looks broken, so a bad scrape never reaches
GitHub Pages. Run with: python tools/check_data.py
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys

from common import DATA_DIR, WEB_DIR, read_json

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_EVENTS = 200
MIN_PROVINCES = 8


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

    if problems:
        print("dataset validation FAILED:")
        for problem in problems[:20]:
            print(f"  - {problem}")
        return 1

    print(f"dataset OK: {len(events)} events, {len(provinces)} provinces, "
          f"window {start}..{end}, categories {sorted(c for c in categories if c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())