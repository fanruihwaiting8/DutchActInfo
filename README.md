# Dutch Activity Info

Weekend activities in the Netherlands for **this month and next month**, within a
comfortable drive of Den Haag, refreshed automatically every day and published as
a static site.

Live site: https://fanruihwaiting8.github.io/DutchActInfo/

Only Friday, Saturday and Sunday dates are kept — the point is to answer
"what can I do this weekend?" without scrolling through weekday listings.

## Features

- Festivals, concerts and comedy shows across the reachable Dutch provinces
- Drive-time filter: everything is measured as a car trip from Den Haag, with
  one-hour / 1.5-hour / any-distance presets; places more than ~2 hours away
  are dropped at scrape time
- Small villages (under 15k inhabitants) are hidden unless you ask for them
- Filter by time window (next weekend / this month / next month), category,
  province, city and weekday
- Full-text search over title, venue, city and performers
- Bilingual interface (English / Chinese); event titles stay in Dutch so they
  remain searchable on the ticket sites
- Explicit "view details" button on every card, plus whole-card click
- Mobile-first dark UI, no framework, no build step
- Data refreshed daily by GitHub Actions, site redeployed on change

## Data sources

| Source | What it provides |
| --- | --- |
| festivalinfo.nl | festivals (schema.org JSON-LD) |
| podiuminfo.nl | concert agenda per day |
| cabaretinfo.nl | comedy agenda per day |
| uitagenda.nl | city -> province mapping |
| geonames.org | city coordinates and population |

Belgian listings that appear on these Dutch agendas are filtered out with a
city whitelist built from the province pages.

## Layout

```
tools/           Python scrapers and validation
  common.py        HTTP fetch, text cleanup, JSON helpers
  build_cities.py  regenerates data/cities_nl.json (city -> province)
  build_geo.py     regenerates data/geo_nl.json (city -> lat/lon/population)
  sources.py       per-source HTML/JSON-LD parsers
  fetch_events.py  main scraper -> data/events.json + web/data.js
  check_data.py    sanity checks before commit/deploy
  test_app.js      smoke tests for the frontend logic (run with jsc)
web/             static site (index.html, styles.css, app.js, i18n.js, data.js)
data/            generated dataset (events.json, cities_nl.json, geo_nl.json)
.github/workflows/
  refresh.yml      daily scrape + commit
  pages.yml        deploy web/ to GitHub Pages
```

## Running locally

```bash
# refresh the dataset (takes a few minutes, be polite to the sources)
python3 tools/fetch_events.py

# quick run while developing: only the first few weekend days
python3 tools/fetch_events.py --limit-days 3 --skip-festivals

# validate the generated dataset
python3 tools/check_data.py

# rebuild the city -> province map (rarely needed)
python3 tools/build_cities.py

# rebuild the city -> coordinates map (rarely needed)
python3 tools/build_geo.py

# serve the site
python3 -m http.server 8000 --directory web
```

No third-party Python packages are required (standard library only).

### Frontend tests

```bash
jsc=/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc
$jsc tools/jsc_shim.js web/data.js web/i18n.js web/app.js tools/test_app.js
```

## License

MIT — see [LICENSE](LICENSE). Event data belongs to the respective sources and
is only mirrored here for personal, non-commercial use.