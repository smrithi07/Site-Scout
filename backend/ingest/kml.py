"""Minimal KML reader: Placemark attributes + polygon geometry as MULTIPOLYGON WKT."""
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

NS = {"k": "http://www.opengis.net/kml/2.2"}


def _ring(coords_el: ET.Element) -> str:
    pts = [c.split(",")[:2] for c in coords_el.text.split()]
    return "(" + ", ".join(f"{x} {y}" for x, y in pts) + ")"


def _polygon(poly: ET.Element) -> str:
    rings = [_ring(poly.find("k:outerBoundaryIs/k:LinearRing/k:coordinates", NS))]
    rings += [_ring(c) for c in poly.findall("k:innerBoundaryIs/k:LinearRing/k:coordinates", NS)]
    return "(" + ", ".join(rings) + ")"


def placemarks(path: Path) -> Iterator[tuple[dict, str | None, str]]:
    """Yields (SimpleData attributes, <name>, MULTIPOLYGON WKT) for each Placemark with polygons."""
    root = ET.parse(path).getroot()
    for pm in root.iterfind(".//k:Placemark", NS):
        polys = pm.findall(".//k:Polygon", NS)
        if not polys:
            continue
        attrs = {sd.get("name"): (sd.text or "").strip() for sd in pm.iterfind(".//k:SimpleData", NS)}
        name_el = pm.find("k:name", NS)
        name = name_el.text.strip() if name_el is not None and name_el.text else None
        yield attrs, name, "MULTIPOLYGON(" + ", ".join(_polygon(p) for p in polys) + ")"
