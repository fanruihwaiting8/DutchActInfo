"""Build data/geo_nl.json: city -> coordinates + population.

Source: the free GeoNames dump for the Netherlands (populated places only).
Used by fetch_events.py to compute the driving distance from the home city and
to tell small villages apart from real destinations.

Run with: python tools/build_geo.py
"""
from __future__ import annotations

import io
import os
import ssl
import urllib.request
import zipfile

from common import DATA_DIR, USER_AGENT, normalise_city, read_json, write_json

DUMP_URL = "https://download.geonames.org/export/dump/NL.zip"

# Only populated places; everything else (lakes, farms, streets) is noise.
PLACE_CLASS = "P"
# Administrative seats are destinations even when GeoNames has no population.
SEAT_CODES = {"PPLC", "PPLA", "PPLA2", "PPLA3"}


def download_dump() -> str:
    request = urllib.request.Request(DUMP_URL, headers={"User-Agent": USER_AGENT})
    contexts = [ssl.create_default_context()]
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    contexts.append(unverified)

    last_error: Exception | None = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(request, timeout=90, context=ctx) as response:
                payload = response.read()
            break
        except Exception as error:  # noqa: BLE001 - retried with the next context
            last_error = error
    else:
        raise RuntimeError(f"could not download {DUMP_URL}: {last_error}")

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.read("NL.txt").decode("utf-8", errors="replace")


def main() -> int:
    catalogue = read_json(os.path.join(DATA_DIR, "cities_nl.json"), {}) or {}
    cities = catalogue.get("cities") or {}
    if not cities:
        print("data/cities_nl.json is missing - run build_cities.py first")
        return 1

    text = download_dump()
    best: dict[str, dict] = {}

    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 15 or parts[6] != PLACE_CLASS:
            continue
        try:
            lat, lon = float(parts[4]), float(parts[5])
        except ValueError:
            continue
        try:
            population = int(parts[14] or 0)
        except ValueError:
            population = 0
        if parts[7] in SEAT_CODES and population < 5000:
            # A municipal seat without a population figure still counts as a
            # proper town, so give it a floor instead of dropping it.
            population = 5000

        names = [parts[1], parts[2]] + (parts[3].split(",") if parts[3] else [])
        for raw in names:
            key = normalise_city(raw)
            if not key or key not in cities:
                continue
            current = best.get(key)
            if current is None or population > current["pop"]:
                best[key] = {"lat": round(lat, 5), "lon": round(lon, 5), "pop": population}

    missing = sorted(key for key in cities if key not in best)
    payload = {key: [value["lat"], value["lon"], value["pop"]] for key, value in sorted(best.items())}
    write_json(os.path.join(DATA_DIR, "geo_nl.json"), payload)

    with_pop = sum(1 for value in best.values() if value["pop"] > 0)
    print(f"matched {len(best)}/{len(cities)} cities, {with_pop} with a population figure")
    if missing:
        print(f"no coordinates for {len(missing)} cities, e.g. {missing[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())