# Official map and roster snapshots

Downloaded on October 30, 2026, from Ville de Montréal open data.

## District boundaries

- Dataset: https://donnees.montreal.ca/dataset/districts-electoraux
- Resource: https://donnees.montreal.ca/dataset/70acec75-c2b4-4d26-a399-facc7b0ad9bf/resource/fa1f8cfc-cdbf-42fd-9979-32c16b68b5ca/download/districts-electoraux-2025.json
- Publisher: Ville de Montréal (Service du greffe / Élections Montréal / Géomatique).
- License: Creative Commons Attribution 4.0 International, as reported by the dataset metadata: https://creativecommons.org/licenses/by/4.0/
- 58 electoral districts for the 2025 election; WGS84 longitude/latitude coordinates.
- Local file: `districts-2025.geojson.gz`. JSON whitespace was removed and gzip compression applied; coordinates and feature properties were not simplified or changed.
- District selection is by the official `CODE_DISTRICT`. Representative matching requires both district and borough, normalizing only accents and punctuation.

## Roster

- Dataset: https://donnees.montreal.ca/dataset/liste-des-elus-de-la-ville-de-montreal
- Exact source URL is recorded in `roster-snapshot.json` and in `roster.py`.
- The existing project parser selects the 65 city council members. Borough-only councillors are not represented.
- Only public names, roles, boroughs, districts and parties are bundled; contact information is not copied.
- A missing database uses this dated snapshot for the preview. An available database supplies its own imported roster and recorded votes. Neither source is described as live data.

Boundaries are served from this package, without a city API call on page load. The optional Carto street basemap fetches external map tiles. Turn off the street background to render district polygons without basemap tile requests. Streamlit still needs to serve the app and its frontend assets.

## Saved English translations

`english-translations.json` contains English derivatives of the original Ville de
Montréal council titles and CONTEXTE excerpts, keyed by the exact French source
text's SHA-256. Generated locally with Helsinki-NLP/opus-mt-fr-en (Apache 2.0),
using CTranslate2. They are machine translations, not official English records.
Original French text and PDF source links remain available in the app.

October 31, 2026 preparation: 1,894 saved text fields; 43 additional fields failed
numeric/reference validation and remain in French pending review. Model files
and the review queue live in ignored scratch/, not in the deployed package.
