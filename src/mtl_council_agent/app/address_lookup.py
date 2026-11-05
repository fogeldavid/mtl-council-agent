"""Uncached address geocoding and local electoral boundary lookup."""
from __future__ import annotations

import math
import re
import unicodedata

import httpx

from mtl_council_agent.app.district_map import boundaries

ENDPOINT = ("https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/"
            "Territoire/AQ_ADRESSES_WMS/MapServer/0/query")
SOURCE = ENDPOINT.removesuffix("/0/query")
# One building can have hundreds of unit rows; this is the service's own maximum.
MAX_ROWS = 1000
_STREET_TYPES = {"RUE", "AVENUE", "AVE", "AV", "BOULEVARD", "BOUL", "BLVD", "BD", "CHEMIN", "CH"}
_SAINTS = {"ST": "SAINT", "STE": "SAINTE"}
# The service spells these out, and only after the street name.
_DIRECTIONS = {
    "E": "EST", "EAST": "EST", "O": "OUEST", "W": "OUEST", "WEST": "OUEST",
    "N": "NORD", "NORTH": "NORD", "S": "SUD", "SOUTH": "SUD",
}


def _fold(text: str) -> str:
    """Uppercase ASCII, so a typed "Cote" and a stored "Côte" compare equal."""
    text = unicodedata.normalize("NFKD", text).replace("œ", "oe").replace("Œ", "OE")
    return "".join(c for c in text if not unicodedata.combining(c)).upper()


def _street_words(street: str) -> list[str]:
    """The words of a typed street, with its abbreviations spelled as the service does."""
    words = re.findall(r"[^\W_]+", _fold(street), re.UNICODE)
    words = [w for w in words if w not in _STREET_TYPES]
    # A last "ST" is English for street ("Main St"), not the start of a saint's name.
    if len(words) > 1 and words[-1] == "ST":
        words.pop()
    if len(words) > 1:
        words[-1] = _DIRECTIONS.get(words[-1], words[-1])
    return [_SAINTS.get(w, w) for w in words]


def _like_word(word: str) -> str:
    """The service's LIKE is accent-sensitive, so any letter that can carry an
    accent matches one character. lookup() then compares the results exactly."""
    return re.sub(r"[AEIOUYC]", "_", word)


def _fetch(params: dict) -> httpx.Response:
    # The service resets connections offering only HTTP/1.1, httpx's default.
    with httpx.Client(http2=True, timeout=15) as client:
        return client.get(
            ENDPOINT, params=params, headers={"User-Agent": "MTLCouncilDistrictFinder/1.0"},
        )


def valid_address(text: str) -> bool:
    text = text.strip()
    return (5 <= len(text) <= 200 and bool(re.search(r"\d", text))
            and bool(re.search(r"[a-zA-ZÀ-ÿ]", text))
            and not bool(re.fullmatch(r"[A-Za-z]\d[A-Za-z](?:\s?\d[A-Za-z]\d)?", text)))


def _ring_contains(x: float, y: float, ring: list) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
        ax, ay = a[:2]
        bx, by = b[:2]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-12 and min(ax, bx) <= x <= max(ax, bx) \
                and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def district_at(longitude: float, latitude: float) -> str | None:
    """Return only an unambiguous district; respect holes and multipart polygons."""
    matches = set()
    for feature in boundaries()["features"]:
        geometry = feature["geometry"]
        polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                    else [geometry["coordinates"]])
        for polygon in polygons:
            if _ring_contains(longitude, latitude, polygon[0]) and not any(
                _ring_contains(longitude, latitude, hole) for hole in polygon[1:]
            ):
                matches.add(feature["properties"]["CODE_DISTRICT"])
    return next(iter(matches)) if len(matches) == 1 else None


def lookup(address: str) -> list[dict]:
    """No address logging, persistent storage, autocomplete, or shared caching."""
    if not valid_address(address):
        raise ValueError("Enter a full street address")
    match = re.fullmatch(r"\s*(\d{1,6})[\s,]+(.{2,150})\s*", address)
    if not match:
        raise ValueError("Enter civic number followed by street name")
    number, street = match.groups()
    # Restrict generated SQL to letters/digits and fixed operators; never insert raw input.
    words = _street_words(street)
    if not words or any(not w.isascii() or not w.isalnum() for w in words):
        raise ValueError("Enter a street name")
    pattern = "%" + "%".join(_like_word(w) for w in words) + "%"
    response = _fetch({
        "f": "json",
        "where": f"NoCivq = {int(number)} AND UPPER(AdresseFormatee) LIKE '{pattern}'",
        "outFields": "AdresseFormatee,NoCivq", "outSR": "4326",
        "geometry": "-73.99,45.40,-73.47,45.72", "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true", "resultRecordCount": str(MAX_ROWS),
    })
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "error" in payload or "features" not in payload:
        raise ValueError("Unexpected address service response")
    if payload.get("exceededTransferLimit"):
        raise ValueError("Street name is too broad")
    results = []
    seen = set()
    for item in payload["features"]:
        geometry = item.get("geometry") or {}
        coordinates = [geometry.get("x"), geometry.get("y")]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in coordinates):
            continue
        code = district_at(*coordinates)
        title = str((item.get("attributes") or {}).get("AdresseFormatee") or "")
        start = re.search(rf"(?<!\d){int(number)}\s", title)
        if start:
            title = title[start.start():]
        title_words = re.findall(r"[^\W_]+", _fold(title))
        if not all(word in title_words for word in words):
            continue
        if code and title and (title, code) not in seen:
            results.append({"title": title, "code": code})
            seen.add((title, code))
    return results
