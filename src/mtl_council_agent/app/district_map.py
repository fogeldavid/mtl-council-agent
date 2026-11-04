"""Official, locally bundled electoral geography and deterministic roster matching."""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")
BOUNDARY_SOURCE = "https://donnees.montreal.ca/dataset/districts-electoraux"
MAP_LAYER_ID = "electoral-districts-2025"


def _identity(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").casefold()
    text = text.replace("œ", "oe").replace("æ", "ae")
    return re.sub(r"[^a-z0-9]", "", text)


@lru_cache(maxsize=1)
def boundaries() -> dict:
    """2025 official polygons in WGS84; no network access or geometry guessing."""
    with gzip.open(DATA_DIR / "districts-2025.geojson.gz", "rt", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def roster_snapshot() -> dict:
    return json.loads((DATA_DIR / "roster-snapshot.json").read_text(encoding="utf-8"))


def district_properties() -> dict[str, dict]:
    return {f["properties"]["CODE_DISTRICT"]: f["properties"] for f in boundaries()["features"]}


def representatives(properties: dict, members: list[dict]) -> list[dict]:
    """The district's councillor, then members elected for the whole borough:
    borough mayors, and city councillors in boroughs without city districts.
    Names must match exactly. Never use a fuzzy geographic match."""
    borough = _identity(properties["NOM_ARR"])
    district = _identity(properties["NOM_DISTRICT"])
    in_borough = [m for m in members if _identity(m.get("borough")) == borough]
    return [
        *(m for m in in_borough if _identity(m.get("district")) == district),
        *(m for m in in_borough if not m.get("district")),
    ]


def map_geojson(selected: str) -> dict:
    """Attach display colours to copies, without mutating the cached source."""
    features = []
    for feature in boundaries()["features"]:
        properties = feature["properties"]
        features.append({
            **feature,
            "properties": {
                **properties,
                "fill": [52, 93, 80, 185] if properties["CODE_DISTRICT"] == selected
                else [125, 151, 137, 65],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def selected_code(event: dict, valid_codes: set[str]) -> str | None:
    """Accept only an ID present in the official bundled boundary dataset."""
    objects = event.get("selection", {}).get("objects", {}).get(MAP_LAYER_ID, [])
    if not objects:
        return None
    code = objects[0].get("properties", {}).get("CODE_DISTRICT")
    return code if code in valid_codes else None
