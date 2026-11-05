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
_POSTAL_CODE = re.compile(r"\b[A-Za-z]\d[A-Za-z](?:[\s-]?\d[A-Za-z]\d)?\b")
_UNIT = re.compile(
    r"\b(?:apt|app|appt|appartement|apartment|unit|unité|unite|suite|bureau)\.?\s*#?\s*"
    r"[\w-]*\d[\w-]*|#\s*\w+",
    re.IGNORECASE,
)
# "3-275" is unit 3 at number 275, and "275A" is number 275.
_CIVIC = re.compile(r"(?:\w+-)?(\d{1,6})[A-Za-z]?[\s,]+(.{2,150})")
# One building can have hundreds of unit rows; this is the service's own maximum.
MAX_ROWS = 1000
_STREET_TYPES = {"RUE", "AVENUE", "AVE", "AV", "BOULEVARD", "BOUL", "BLVD", "BD", "CHEMIN", "CH"}
_SAINTS = {"ST": "SAINT", "STE": "SAINTE"}
_REGION = {"QC", "QUEBEC", "CANADA"}
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
    while len(words) > 1 and words[-1] in _REGION:
        words.pop()
    # A city after the street, but not a street named for it ("rue de Montréal").
    if len(words) > 1 and words[-1] == "MONTREAL" and words[-2] not in {"DE", "D", "DU"}:
        words.pop()
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


class NumberNotFound(ValueError):
    """The street exists, but the service has no address at that civic number."""


def _parse(address: str) -> tuple[int, str] | None:
    """Civic number and street from however someone typed or pasted the address."""
    text = _POSTAL_CODE.sub(" ", _UNIT.sub(" ", address)).strip(" ,")
    match = _CIVIC.fullmatch(text)
    return (int(match[1]), match[2].split(",")[0]) if match else None


def valid_address(text: str) -> bool:
    parsed = _parse(text) if 5 <= len(text.strip()) <= 200 else None
    return parsed is not None and bool(_street_words(parsed[1]))


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


def _query(where: str) -> dict:
    response = _fetch({
        "f": "json", "where": where,
        "outFields": "AdresseFormatee,NoCivq", "outSR": "4326",
        "geometry": "-73.99,45.40,-73.47,45.72", "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true", "resultRecordCount": str(MAX_ROWS),
    })
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "error" in payload or "features" not in payload:
        raise ValueError("Unexpected address service response")
    return payload


def _street_exists(pattern: str, words: list[str]) -> bool:
    """Only tells two failures apart, so a failed check just means the general message."""
    try:
        features = _query(f"UPPER(AdresseFormatee) LIKE '{pattern}'")["features"]
    except (ValueError, httpx.HTTPError):
        return False
    return any(
        all(word in re.findall(r"[^\W_]+", _fold(str(
            (item.get("attributes") or {}).get("AdresseFormatee") or "",
        ))) for word in words)
        for item in features
    )


def lookup(address: str) -> list[dict]:
    """No address logging, persistent storage, autocomplete, or shared caching."""
    if not valid_address(address):
        raise ValueError("Enter a civic number and street name")
    number, street = _parse(address)
    # Restrict generated SQL to letters/digits and fixed operators; never insert raw input.
    words = _street_words(street)
    if not words or any(not w.isascii() or not w.isalnum() for w in words):
        raise ValueError("Enter a street name")
    pattern = "%" + "%".join(_like_word(w) for w in words) + "%"
    payload = _query(f"NoCivq = {number} AND UPPER(AdresseFormatee) LIKE '{pattern}'")
    if payload.get("exceededTransferLimit"):
        raise ValueError("Street name is too broad")
    results = []
    seen = set()
    found_address = False
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
        found_address = True
        # One building can span many postal codes; list it once.
        place = (_POSTAL_CODE.sub("", title).strip(), code)
        if code and title and place not in seen:
            results.append({"title": title, "code": code})
            seen.add(place)
    if not found_address and _street_exists(pattern, words):
        raise NumberNotFound
    return results
