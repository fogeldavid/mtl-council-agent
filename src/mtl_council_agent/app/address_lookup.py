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
    match = re.fullmatch(r"\s*(\d{1,6})\s+(.{2,150})\s*", address)
    if not match:
        raise ValueError("Enter civic number followed by street name")
    number, street = match.groups()
    # Restrict generated SQL to letters/digits and fixed operators; never insert raw input.
    street = unicodedata.normalize("NFC", street).upper()
    words = re.findall(r"[^\W_]+", street, re.UNICODE)
    words = [w for w in words if w not in {"RUE", "AVENUE", "BOULEVARD", "AV", "BOUL"}]
    if not words or any(not w.isalnum() for w in words):
        raise ValueError("Enter a street name")
    pattern = "%" + "%".join(words) + "%"
    response = httpx.get(
        ENDPOINT, params={
            "f": "json",
            "where": f"NoCivq = {int(number)} AND UPPER(AdresseFormatee) LIKE '{pattern}'",
            "outFields": "AdresseFormatee,NoCivq", "outSR": "4326",
            "geometry": "-73.99,45.40,-73.47,45.72", "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "true", "resultRecordCount": "100",
        }, timeout=15, headers={"User-Agent": "MTLCouncilDistrictFinder/1.0"},
    )
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
        title_words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", title).upper())
        if not all(word in title_words for word in words):
            continue
        if code and title and (title, code) not in seen:
            results.append({"title": title, "code": code})
            seen.add((title, code))
    return results
