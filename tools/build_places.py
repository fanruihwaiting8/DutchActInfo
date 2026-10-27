"""Build the places dataset used for the postcode centre and travel directions.

Outputs
  data/postcodes_nl.json  {"1011": [lat, lon, "Amsterdam"]}
  data/stations_nl.json   [["Amsterdam Centraal", lat, lon], ...]
  data/parking_nl.json    {"amsterdam": [[name, euro_per_hour|null, kind, metres], ...]}
  web/places.js           window.ACTIVITY_PLACES = {postcodes, cities, parking}

Sources
  postcodes: the free GeoNames postal-code export for the Netherlands
  stations + parking: OpenStreetMap through the public Overpass API

Parking and station lookups are cached in data/, so the daily refresh does not
have to hammer Overpass; only missing cities are fetched. Run with --force to
rebuild a cache from scratch.

Usage
  python tools/build_places.py              # fill the gaps, then write web/places.js
  python tools/build_places.py --web        # only rewrite web/places.js
  python tools/build_places.py --force      # refetch everything
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from common import DATA_DIR, WEB_DIR, normalise_city, read_json, write_json

POSTCODE_URL = "https://download.geonames.org/export/zip/NL.zip"
# A descriptive agent is required; browser-looking agents get a 406 from Overpass.
OVERPASS_AGENT = "DutchActivityInfo/1.0 (open-source weekend agenda; Overpass batch build)"
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
)
# Cities this size and up get a parking lookup even without an event right now.
PARKING_MIN_POPULATION = 20000
# Parking lots further out than this are not "at the venue" any more.
PARKING_RADIUS_M = 2500
PARKING_PER_CITY = 6
# One query per map tile is far kinder to Overpass than one query per city.
NL_BBOX = (50.70, 3.30, 53.60, 7.25)
TILE_ROWS = 3
TILE_COLS = 3
# Overlap so a lot just outside a tile still reaches the city inside it.
TILE_PAD = 0.05

POSTCODES_PATH = os.path.join(DATA_DIR, "postcodes_nl.json")
STATIONS_PATH = os.path.join(DATA_DIR, "stations_nl.json")
PARKING_PATH = os.path.join(DATA_DIR, "parking_nl.json")
PARKING_TILES_PATH = os.path.join(DATA_DIR, "parking_tiles.json")
PLACES_JS = os.path.join(WEB_DIR, "places.js")


def log(message: str) -> None:
    print(message, flush=True)


def _contexts():
    yield ssl.create_default_context()
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    yield unverified


def download(url: str, timeout: int = 120) -> bytes:
    last_error: Exception | None = None
    for ctx in _contexts():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": OVERPASS_AGENT})
            with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 - retried with the next context
            last_error = error
    raise RuntimeError(f"could not download {url}: {last_error}")


def overpass(query: str, attempts: int = 4) -> dict:
    """Run an Overpass query, rotating mirrors and backing off on congestion."""
    body = urllib.parse.urlencode({"data": query}).encode()
    last_error: Exception | None = None
    for attempt in range(attempts):
        for mirror in OVERPASS_MIRRORS:
            for ctx in _contexts():
                request = urllib.request.Request(
                    mirror,
                    data=body,
                    headers={
                        "User-Agent": OVERPASS_AGENT,
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                try:
                    with urllib.request.urlopen(request, timeout=120, context=ctx) as response:
                        return json.loads(response.read().decode("utf-8", errors="replace"))
                except ssl.SSLError as error:
                    last_error = error
                    continue  # retry the same mirror with the unverified context
                except Exception as error:  # noqa: BLE001 - try the next mirror
                    last_error = error
                    if isinstance(getattr(error, "reason", None), ssl.SSLError):
                        continue
                    break  # an SSL fallback will not fix a 429/502, move on
        wait = 8 * (attempt + 1)
        log(f"  all mirrors busy ({last_error}), retrying in {wait}s")
        time.sleep(wait)
    raise RuntimeError(f"overpass failed: {last_error}")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return radius * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- postcodes

def build_postcodes() -> dict:
    payload = download(POSTCODE_URL)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text = archive.read("NL.txt").decode("utf-8", errors="replace")

    groups: dict[str, list] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 11:
            continue
        code = parts[1].strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        try:
            lat, lon = float(parts[9]), float(parts[10])
        except ValueError:
            continue
        groups.setdefault(code, []).append((lat, lon, parts[2].strip()))

    table: dict[str, list] = {}
    for code, rows in sorted(groups.items()):
        lat = sum(row[0] for row in rows) / len(rows)
        lon = sum(row[1] for row in rows) / len(rows)
        table[code] = [round(lat, 4), round(lon, 4), rows[0][2]]
    write_json(POSTCODES_PATH, table)
    log(f"postcodes: {len(table)} PC4 areas")
    return table


# ----------------------------------------------------------------- stations

STATION_QUERY = """
[out:json][timeout:240];
area["ISO3166-1"="NL"][admin_level=2]->.nl;
nwr["railway"="station"]["train"!="no"]["name"](area.nl);
out center tags;
"""


def build_stations() -> list:
    doc = overpass(STATION_QUERY)
    seen: dict[str, list] = {}
    for element in doc.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name or tags.get("station") in ("subway", "light_rail", "monorail"):
            continue
        centre = element.get("center") or element
        try:
            lat, lon = float(centre["lat"]), float(centre["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if name not in seen:
            seen[name] = [name, round(lat, 4), round(lon, 4)]
    stations = sorted(seen.values(), key=lambda row: row[0])
    write_json(STATIONS_PATH, stations)
    log(f"stations: {len(stations)} train stations")
    return stations


# ------------------------------------------------------------------ parking

UNIT_HOURS = {
    "hour": 1.0, "hours": 1.0, "hr": 1.0, "h": 1.0, "uur": 1.0,
    "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60, "minutes": 1 / 60,
    "minuut": 1 / 60, "minuten": 1 / 60,
    "day": 24.0, "days": 24.0, "dag": 24.0, "etmaal": 24.0,
}
CHARGE_RE = re.compile(
    r"(?:eur|euro|\u20ac)?\s*(\d+(?:[.,]\d+)?)\s*(?:eur|euro|\u20ac)?\s*"
    r"(?:/|per\s+)\s*(\d+(?:[.,]\d+)?)?\s*([a-z]+)",
    re.IGNORECASE,
)
# Kinds we show to the user, derived from the OSM parking tag.
KIND_MAP = {
    "multi-storey": "garage",
    "underground": "underground",
    "garage_boxes": "garage",
    "street_side": "street",
    "lane": "street",
    "surface": "surface",
    "rooftop": "surface",
    "carports": "surface",
}


def parse_charge(raw: str) -> float | None:
    """Turn an OSM charge tag into euro per hour, or None when unreadable."""
    best: float | None = None
    for part in str(raw).split(";"):
        match = CHARGE_RE.search(part.strip())
        if not match:
            continue
        try:
            amount = float(match.group(1).replace(",", "."))
            count = float((match.group(2) or "1").replace(",", "."))
        except ValueError:
            continue
        hours = UNIT_HOURS.get(match.group(3).lower())
        if not hours or count <= 0:
            continue
        span = count * hours
        if span <= 0:
            continue
        rate = amount / span
        # Prefer the hourly rate; a day ticket is only a fallback estimate.
        if hours == 1.0:
            return round(rate, 2)
        if best is None:
            best = round(rate, 2)
    return best


def parking_of(tags: dict) -> tuple[float | None, str]:
    fee = (tags.get("fee") or "").strip().lower()
    charge = tags.get("charge") or tags.get("fee:conditional") or ""
    price = parse_charge(charge) if charge else None
    if price is None and fee in ("no", "false"):
        price = 0.0
    kind = KIND_MAP.get((tags.get("parking") or "").strip().lower(), "surface")
    if (tags.get("park_ride") or "").lower() in ("yes", "bus", "train", "tram", "metro"):
        kind = "pr"
    return price, kind


def parking_tiles() -> list[tuple[float, float, float, float]]:
    south, west, north, east = NL_BBOX
    dlat = (north - south) / TILE_ROWS
    dlon = (east - west) / TILE_COLS
    boxes = []
    for row in range(TILE_ROWS):
        for col in range(TILE_COLS):
            boxes.append((
                round(south + row * dlat - TILE_PAD, 3),
                round(west + col * dlon - TILE_PAD, 3),
                round(south + (row + 1) * dlat + TILE_PAD, 3),
                round(west + (col + 1) * dlon + TILE_PAD, 3),
            ))
    return boxes


def tile_query(box: tuple[float, float, float, float]) -> str:
    south, west, north, east = box
    return (
        "[out:json][timeout:180];"
        'nwr["amenity"="parking"]["name"]["access"!="private"]'
        f"({south},{west},{north},{east});"
        "out center tags;"
    )


def quarters(box: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    """Split one tile into four, used when a mirror keeps refusing the big box."""
    south, west, north, east = box
    mid_lat = round((south + north) / 2, 3)
    mid_lon = round((west + east) / 2, 3)
    return [
        (south, west, mid_lat, mid_lon),
        (south, mid_lon, mid_lat, east),
        (mid_lat, west, north, mid_lon),
        (mid_lat, mid_lon, north, east),
    ]


def lots_in(box: tuple[float, float, float, float]) -> list[tuple]:
    doc = overpass(tile_query(box))
    points = []
    for element in doc.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        centre = element.get("center") or element
        try:
            lat, lon = float(centre["lat"]), float(centre["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        price, kind = parking_of(tags)
        points.append((name, lat, lon, price, kind))
    return points


def merge_rows(current: list, extra: list) -> list:
    rows: dict[str, list] = {}
    for row in list(current) + list(extra):
        seen = rows.get(row[0])
        if seen is None or row[3] < seen[3]:
            rows[row[0]] = row
    # Paid spots first, most expensive on top; unknown prices last.
    ordered = sorted(
        rows.values(),
        key=lambda row: (row[1] is None, -(row[1] or 0.0), row[3]),
    )
    return ordered[:PARKING_PER_CITY]


def build_parking(targets: dict[str, list], cache: dict, force: bool) -> dict:
    boxes = parking_tiles()
    done = set(read_json(PARKING_TILES_PATH, []) or [])
    if force:
        done, cache = set(), {}
    pending = [index for index in range(len(boxes)) if index not in done]
    if not pending:
        log(f"parking: cache already covers {len(cache)} cities")
        return cache

    log(f"parking: {len(pending)} of {len(boxes)} map tiles left, {len(targets)} target cities")
    for index in pending:
        box = boxes[index]
        try:
            points = lots_in(box)
        except RuntimeError as error:
            log(f"  tile {index + 1} refused ({error}), retrying in quarters")
            points, failed = [], False
            for part in quarters(box):
                try:
                    points.extend(lots_in(part))
                except RuntimeError as sub_error:
                    log(f"  tile {index + 1} quarter gave up: {sub_error}")
                    failed = True
                    break
                time.sleep(2)
            if failed:
                # Leave the tile out of the log so a later run picks it up again.
                continue

        touched = 0
        for key, point in targets.items():
            city_lat, city_lon = point[0], point[1]
            if not (box[0] - 0.1 <= city_lat <= box[2] + 0.1
                    and box[1] - 0.15 <= city_lon <= box[3] + 0.15):
                continue
            extra = []
            for name, lat, lon, price, kind in points:
                metres = round(haversine_km(city_lat, city_lon, lat, lon) * 1000)
                if metres <= PARKING_RADIUS_M:
                    extra.append([name, price, kind, metres])
            if extra:
                cache[key] = merge_rows(cache.get(key) or [], extra)
                touched += 1
        done.add(index)
        write_json(PARKING_PATH, dict(sorted(cache.items())))
        write_json(PARKING_TILES_PATH, sorted(done))
        log(f"  tile {index + 1}/{len(boxes)}: {len(points)} lots, {touched} cities updated")
        time.sleep(2)

    if len(done) == len(boxes):
        for key in targets:
            cache.setdefault(key, [])
        write_json(PARKING_PATH, dict(sorted(cache.items())))
    return cache


# -------------------------------------------------------------------- output

def nearest_station(stations: list, lat: float, lon: float) -> list | None:
    best = None
    for name, slat, slon in stations:
        km = haversine_km(lat, lon, slat, slon)
        if best is None or km < best[1]:
            best = [name, km]
    if best is None or best[1] > 25:
        return None
    return [best[0], round(best[1], 1)]


def write_places(postcodes: dict, stations: list, parking: dict, geo: dict,
                 catalogue: dict) -> None:
    cities = catalogue.get("cities") or {}
    city_rows: dict[str, list] = {}
    for key, point in geo.items():
        place = cities.get(key)
        if not place:
            continue
        station = nearest_station(stations, point[0], point[1]) if stations else None
        city_rows[place["name"]] = [
            round(point[0], 4),
            round(point[1], 4),
            station[0] if station else "",
            station[1] if station else 0,
            parking.get(key) or [],
        ]
    payload = {
        "postcodes": postcodes,
        "cities": city_rows,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with open(PLACES_JS, "w", encoding="utf-8") as handle:
        handle.write("// Generated by tools/build_places.py - do not edit by hand.\n")
        handle.write("window.ACTIVITY_PLACES = " + body + ";\n")
    size = os.path.getsize(PLACES_JS) / 1024
    log(f"web/places.js: {len(postcodes)} postcodes, {len(city_rows)} cities, {size:.0f} KB")


def parking_targets(geo: dict, catalogue: dict) -> dict[str, list]:
    cities = catalogue.get("cities") or {}
    events = read_json(os.path.join(DATA_DIR, "events.json"), {}) or {}
    wanted = set()
    for event in events.get("events", []):
        key = normalise_city(event.get("city", ""))
        if key in geo:
            wanted.add(key)
    for key, point in geo.items():
        if key in cities and len(point) > 2 and point[2] >= PARKING_MIN_POPULATION:
            wanted.add(key)
    return {key: geo[key] for key in sorted(wanted)}


def main(argv: list[str]) -> int:
    force = "--force" in argv
    web_only = "--web" in argv

    geo = read_json(os.path.join(DATA_DIR, "geo_nl.json"), {}) or {}
    catalogue = read_json(os.path.join(DATA_DIR, "cities_nl.json"), {}) or {}
    if not geo or not catalogue.get("cities"):
        log("data/geo_nl.json or data/cities_nl.json missing - run build_geo.py first")
        return 1

    postcodes = read_json(POSTCODES_PATH, {}) or {}
    stations = read_json(STATIONS_PATH, []) or []
    parking = read_json(PARKING_PATH, {}) or {}

    if not web_only:
        if force or not postcodes:
            postcodes = build_postcodes()
        if force or not stations:
            stations = build_stations()
        parking = build_parking(parking_targets(geo, catalogue), parking, force)

    if not postcodes or not stations:
        log("postcode or station cache is empty - rerun without --web")
        return 1

    write_places(postcodes, stations, parking, geo, catalogue)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))