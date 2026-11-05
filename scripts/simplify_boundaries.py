"""Build the lightweight district outlines the map draws.

The official file has 161,000 points. Sending them on every map update cost
about 19 MB, so the map uses this copy, accurate to about 6 metres. Address
lookup keeps using the official file.

Run: python scripts/simplify_boundaries.py
"""
from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src/mtl_council_agent/app/data"
SOURCE = DATA / "districts-2025.geojson.gz"
TARGET = DATA / "districts-2025-display.geojson.gz"
TOLERANCE = 0.00005  # Degrees: about 6 metres at Montreal's latitude.
DECIMALS = 5  # About 1 metre.
KEPT = ("CODE_DISTRICT", "NOM_DISTRICT", "NOM_ARR")


def simplify_line(points: list, tolerance: float) -> list:
    """Douglas-Peucker: keep only the points that bend the line more than tolerance."""
    keep = {0, len(points) - 1}
    spans = [(0, len(points) - 1)]
    while spans:
        start, end = spans.pop()
        ax, ay = points[start][:2]
        bx, by = points[end][:2]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        farthest, distance = None, tolerance
        for i in range(start + 1, end):
            px, py = points[i][:2]
            d = (abs(dy * (px - ax) - dx * (py - ay)) / length if length
                 else math.hypot(px - ax, py - ay))
            if d > distance:
                farthest, distance = i, d
        if farthest is not None:
            keep.add(farthest)
            spans += [(start, farthest), (farthest, end)]
    return [points[i] for i in sorted(keep)]


def simplify_ring(ring: list, tolerance: float = TOLERANCE) -> list:
    # A ring starts and ends on one point, so split it at the point farthest away.
    x, y = ring[0][:2]
    far = max(range(len(ring)), key=lambda i: math.hypot(ring[i][0] - x, ring[i][1] - y))
    points = simplify_line(ring[:far + 1], tolerance)[:-1] + simplify_line(ring[far:], tolerance)
    return [[round(p[0], DECIMALS), round(p[1], DECIMALS)] for p in points]


def simplify_feature(feature: dict) -> dict:
    geometry = feature["geometry"]
    polygons = (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
                else [geometry["coordinates"]])
    simplified = []
    for polygon in polygons:
        rings = [simplify_ring(ring) for ring in polygon]
        # Drop specks too small to survive; an outer ring is always kept.
        simplified.append(rings[:1] + [ring for ring in rings[1:] if len(ring) >= 4])
    return {
        "type": "Feature",
        "properties": {key: feature["properties"][key] for key in KEPT},
        "geometry": {"type": "MultiPolygon", "coordinates": simplified},
    }


def main() -> None:
    with gzip.open(SOURCE, "rt", encoding="utf-8") as handle:
        source = json.load(handle)
    result = {
        "type": "FeatureCollection",
        "features": [simplify_feature(feature) for feature in source["features"]],
    }
    # mtime=0 keeps the file identical between runs, so it only shows in a diff if it changed.
    with TARGET.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
        handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"{TARGET.name}: {TARGET.stat().st_size / 1000:.0f} KB")


if __name__ == "__main__":
    main()
