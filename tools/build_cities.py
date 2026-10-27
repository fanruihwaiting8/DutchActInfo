"""Build data/cities_nl.json: a Dutch city -> province lookup table.

Source: uitagenda.nl province pages, which list every place inside a province
in a "Plaatsen in <province>" block. The result is a static artefact: it only
needs to be regenerated once in a while, not on every event refresh.

Usage:  python3 tools/build_cities.py
"""

from __future__ import annotations

import os
import re

from common import DATA_DIR, clean_text, fetch, normalise_city, polite_sleep, write_json

PROVINCES = {
    "drenthe": "Drenthe",
    "flevoland": "Flevoland",
    "friesland": "Friesland",
    "gelderland": "Gelderland",
    "groningen": "Groningen",
    "limburg": "Limburg",
    "noord-brabant": "Noord-Brabant",
    "noord-holland": "Noord-Holland",
    "overijssel": "Overijssel",
    "utrecht": "Utrecht",
    "zeeland": "Zeeland",
    "zuid-holland": "Zuid-Holland",
}

PLACE_RE = re.compile(r'title="Uitgaan in ([^"]+)"')


def places_for(slug: str) -> list[str]:
    url = f"https://www.uitagenda.nl/provincie/{slug}"
    page = fetch(url)
    marker = page.find("Plaatsen in")
    if marker < 0:
        return []
    block = page[marker : marker + 40000]
    found = [clean_text(name) for name in PLACE_RE.findall(block)]
    return [name for name in found if name]


def main() -> None:
    cities: dict[str, dict[str, str]] = {}
    for slug, province in PROVINCES.items():
        try:
            names = places_for(slug)
        except Exception as error:  # noqa: BLE001 - one bad province must not stop the run
            print(f"[warn] {slug}: {error}")
            names = []
        print(f"{province:16s} {len(names):4d} places")
        for name in names:
            key = normalise_city(name)
            if key and key not in cities:
                cities[key] = {"name": name, "province": province}
        polite_sleep(1.0)

    if len(cities) < 500:
        raise SystemExit(f"only {len(cities)} cities found, refusing to overwrite the dataset")

    payload = {
        "provinces": sorted(PROVINCES.values()),
        "cities": dict(sorted(cities.items())),
    }
    path = os.path.join(DATA_DIR, "cities_nl.json")
    write_json(path, payload)
    print(f"wrote {len(cities)} cities -> {path}")


if __name__ == "__main__":
    main()