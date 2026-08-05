#!/usr/bin/env python3
"""Strict standard-library geometry support for Kane Condo GeoPackages."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Any, Iterable

SRS_ID = 4326
WKB_LINESTRING = 2
WKB_POLYGON = 3
WKB_MULTILINESTRING = 5
WKB_MULTIPOLYGON = 6

Position = tuple[float, float]
LineString = list[Position]
MultiLineString = list[LineString]
Ring = list[Position]
Polygon = list[Ring]
MultiPolygon = list[Polygon]
GeometryCoordinates = LineString | MultiLineString | Polygon | MultiPolygon


@dataclass(frozen=True)
class DecodedGeometry:
    geometry_type: str
    coordinates: GeometryCoordinates
    srs_id: int
    envelope: tuple[float, float, float, float]
    wkb: bytes


class WkbReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self.data):
            raise RuntimeError("GeoPackage geometry WKB is truncated")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def uint32(self, endian: str) -> int:
        return struct.unpack(endian + "I", self.take(4))[0]

    def point(self, endian: str) -> Position:
        return struct.unpack(endian + "dd", self.take(16))


def normalize_position(value: Any, context: str = "Polygon") -> Position:
    if not isinstance(value, list) or len(value) != 2:
        raise RuntimeError(f"{context} coordinates must contain exactly two ordinates")
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"{context} coordinates must be numeric") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise RuntimeError(f"{context} coordinates must be finite numbers")
    if not -180.0 <= x <= 180.0 or not -90.0 <= y <= 90.0:
        raise RuntimeError(
            f"{context} coordinates must be EPSG:4326 longitude/latitude values"
        )
    return x, y


def normalize_line(value: Any) -> LineString:
    if not isinstance(value, list) or len(value) < 2:
        raise RuntimeError("LineString must contain at least two positions")
    line = [normalize_position(position, "LineString") for position in value]
    if len(set(line)) < 2:
        raise RuntimeError("LineString must contain at least two distinct positions")
    return line


def normalize_linear_geometry(
    geometry: Any,
) -> tuple[str, LineString | MultiLineString]:
    if not isinstance(geometry, dict):
        raise RuntimeError("Feature has no geometry object")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        return geometry_type, normalize_line(coordinates)
    if geometry_type == "MultiLineString":
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError("MultiLineString must contain at least one line")
        return geometry_type, [normalize_line(line) for line in coordinates]
    raise RuntimeError(f"Unsupported linear geometry type: {geometry_type!r}")


def normalize_ring(value: Any) -> Ring:
    if not isinstance(value, list):
        raise RuntimeError("Polygon ring is not an array")
    ring = [normalize_position(position) for position in value]
    if len(ring) < 4:
        raise RuntimeError("Polygon ring must contain at least four positions")
    if ring[0] != ring[-1]:
        raise RuntimeError("Polygon ring is not closed")
    if len(set(ring[:-1])) < 3:
        raise RuntimeError("Polygon ring must contain at least three distinct vertices")
    return ring


def normalize_polygon(value: Any) -> Polygon:
    if not isinstance(value, list) or not value:
        raise RuntimeError("Polygon must contain at least one ring")
    return [normalize_ring(ring) for ring in value]


def normalize_polygon_geometry(geometry: Any) -> tuple[str, Polygon | MultiPolygon]:
    if not isinstance(geometry, dict):
        raise RuntimeError("Feature has no geometry object")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return geometry_type, normalize_polygon(coordinates)
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise RuntimeError("MultiPolygon must contain at least one polygon")
        return geometry_type, [normalize_polygon(polygon) for polygon in coordinates]
    raise RuntimeError(f"Unsupported polygon geometry type: {geometry_type!r}")


def normalize_map_geometry(geometry: Any) -> tuple[str, GeometryCoordinates]:
    if not isinstance(geometry, dict):
        raise RuntimeError("Feature has no geometry object")
    geometry_type = geometry.get("type")
    if geometry_type in ("LineString", "MultiLineString"):
        return normalize_linear_geometry(geometry)
    if geometry_type in ("Polygon", "MultiPolygon"):
        return normalize_polygon_geometry(geometry)
    raise RuntimeError(f"Unsupported map geometry type: {geometry_type!r}")


def iter_polygon_positions(
    geometry_type: str, coordinates: Polygon | MultiPolygon
) -> Iterable[Position]:
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    for polygon in polygons:
        for ring in polygon:
            yield from ring


def iter_map_positions(
    geometry_type: str, coordinates: GeometryCoordinates
) -> Iterable[Position]:
    if geometry_type == "LineString":
        yield from coordinates  # type: ignore[misc]
    elif geometry_type == "MultiLineString":
        for line in coordinates:  # type: ignore[union-attr]
            yield from line
    elif geometry_type in ("Polygon", "MultiPolygon"):
        yield from iter_polygon_positions(geometry_type, coordinates)  # type: ignore[arg-type]
    else:
        raise RuntimeError(f"Unsupported geometry type for position iteration: {geometry_type!r}")


def polygon_geometry_bounds(
    geometry_type: str, coordinates: Polygon | MultiPolygon
) -> tuple[float, float, float, float]:
    positions = list(iter_polygon_positions(geometry_type, coordinates))
    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    bounds = min(xs), min(ys), max(xs), max(ys)
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise RuntimeError("Polygon geometry has empty or degenerate bounds")
    return bounds


def map_geometry_bounds(
    geometry_type: str, coordinates: GeometryCoordinates
) -> tuple[float, float, float, float]:
    if geometry_type in ("Polygon", "MultiPolygon"):
        return polygon_geometry_bounds(geometry_type, coordinates)  # type: ignore[arg-type]
    positions = list(iter_map_positions(geometry_type, coordinates))
    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    bounds = min(xs), min(ys), max(xs), max(ys)
    if bounds[0] == bounds[2] and bounds[1] == bounds[3]:
        raise RuntimeError("Linear geometry has empty or degenerate bounds")
    return bounds


def pack_line(line: LineString) -> bytes:
    return struct.pack("<I", len(line)) + b"".join(
        struct.pack("<dd", x, y) for x, y in line
    )


def line_wkb(line: LineString) -> bytes:
    return struct.pack("<BI", 1, WKB_LINESTRING) + pack_line(line)


def pack_ring(ring: Ring) -> bytes:
    return struct.pack("<I", len(ring)) + b"".join(
        struct.pack("<dd", x, y) for x, y in ring
    )


def polygon_wkb(polygon: Polygon) -> bytes:
    return (
        struct.pack("<BI", 1, WKB_POLYGON)
        + struct.pack("<I", len(polygon))
        + b"".join(pack_ring(ring) for ring in polygon)
    )


def map_geometry_wkb(geometry_type: str, coordinates: GeometryCoordinates) -> bytes:
    if geometry_type == "LineString":
        return line_wkb(coordinates)  # type: ignore[arg-type]
    if geometry_type == "MultiLineString":
        return (
            struct.pack("<BI", 1, WKB_MULTILINESTRING)
            + struct.pack("<I", len(coordinates))
            + b"".join(line_wkb(line) for line in coordinates)  # type: ignore[union-attr]
        )
    if geometry_type == "Polygon":
        return polygon_wkb(coordinates)  # type: ignore[arg-type]
    if geometry_type == "MultiPolygon":
        return (
            struct.pack("<BI", 1, WKB_MULTIPOLYGON)
            + struct.pack("<I", len(coordinates))
            + b"".join(polygon_wkb(polygon) for polygon in coordinates)  # type: ignore[union-attr]
        )
    raise RuntimeError(f"Unsupported geometry type for WKB: {geometry_type!r}")


def encode_geopackage_geometry(
    geometry_type: str, coordinates: GeometryCoordinates
) -> tuple[bytes, bytes, tuple[float, float, float, float]]:
    bounds = map_geometry_bounds(geometry_type, coordinates)
    wkb = map_geometry_wkb(geometry_type, coordinates)
    flags = 0b00000011  # little endian, XY envelope, standard non-empty geometry
    header = b"GP" + bytes((0, flags)) + struct.pack("<i", SRS_ID)
    header += struct.pack("<dddd", bounds[0], bounds[2], bounds[1], bounds[3])
    return header + wkb, wkb, bounds


def encode_geopackage_polygon(
    geometry_type: str, coordinates: Polygon | MultiPolygon
) -> tuple[bytes, bytes, tuple[float, float, float, float]]:
    if geometry_type not in ("Polygon", "MultiPolygon"):
        raise RuntimeError(f"Unsupported polygon geometry type: {geometry_type!r}")
    return encode_geopackage_geometry(geometry_type, coordinates)


def _read_header(reader: WkbReader) -> tuple[str, int]:
    order = reader.take(1)[0]
    if order not in (0, 1):
        raise RuntimeError("GeoPackage geometry WKB has an invalid byte order")
    endian = "<" if order == 1 else ">"
    return endian, reader.uint32(endian)


def _read_line(reader: WkbReader, *, nested: bool = False) -> LineString:
    endian, geometry_type = _read_header(reader)
    if geometry_type != WKB_LINESTRING:
        label = "nested " if nested else ""
        raise RuntimeError(f"GeoPackage geometry WKB {label}type is not LineString")
    points = [reader.point(endian) for _ in range(reader.uint32(endian))]
    line = [normalize_position(list(point), "LineString") for point in points]
    if len(line) < 2:
        raise RuntimeError("GeoPackage LineString contains fewer than two positions")
    if len(set(line)) < 2:
        raise RuntimeError("GeoPackage LineString has fewer than two distinct positions")
    return line


def _read_ring(reader: WkbReader, endian: str) -> Ring:
    ring = [reader.point(endian) for _ in range(reader.uint32(endian))]
    normalized = [normalize_position(list(point)) for point in ring]
    if len(normalized) < 4:
        raise RuntimeError("GeoPackage Polygon ring contains fewer than four positions")
    if normalized[0] != normalized[-1]:
        raise RuntimeError("GeoPackage Polygon ring is not closed")
    if len(set(normalized[:-1])) < 3:
        raise RuntimeError("GeoPackage Polygon ring has fewer than three distinct vertices")
    return normalized


def _read_polygon(reader: WkbReader, *, nested: bool = False) -> Polygon:
    endian, geometry_type = _read_header(reader)
    if geometry_type != WKB_POLYGON:
        label = "nested " if nested else ""
        raise RuntimeError(f"GeoPackage geometry WKB {label}type is not Polygon")
    polygon = [_read_ring(reader, endian) for _ in range(reader.uint32(endian))]
    if not polygon:
        raise RuntimeError("GeoPackage Polygon contains no rings")
    return polygon


def _split_geopackage_blob(
    blob: bytes,
) -> tuple[int, tuple[float, float, float, float], bytes, WkbReader, str, int]:
    if len(blob) <= 40 or blob[:2] != b"GP":
        raise RuntimeError("Geometry has an invalid GeoPackage header")
    if blob[2] != 0:
        raise RuntimeError("Geometry uses an unsupported GeoPackage binary version")
    flags = blob[3]
    if flags != 0b00000011:
        raise RuntimeError("Geometry must use a little-endian XY envelope")
    srs_id = struct.unpack("<i", blob[4:8])[0]
    if srs_id != SRS_ID:
        raise RuntimeError(f"Geometry uses unexpected SRS {srs_id}; expected {SRS_ID}")
    envelope_raw = struct.unpack("<dddd", blob[8:40])
    envelope = envelope_raw[0], envelope_raw[2], envelope_raw[1], envelope_raw[3]
    wkb = blob[40:]
    reader = WkbReader(wkb)
    start = reader.offset
    endian, geometry_code = _read_header(reader)
    reader.offset = start
    return srs_id, envelope, wkb, reader, endian, geometry_code


def decode_geopackage_geometry(blob: bytes) -> DecodedGeometry:
    srs_id, envelope, wkb, reader, endian, geometry_code = _split_geopackage_blob(blob)
    if geometry_code == WKB_LINESTRING:
        geometry_type = "LineString"
        coordinates: GeometryCoordinates = _read_line(reader)
    elif geometry_code == WKB_MULTILINESTRING:
        _read_header(reader)
        coordinates = [_read_line(reader, nested=True) for _ in range(reader.uint32(endian))]
        if not coordinates:
            raise RuntimeError("GeoPackage MultiLineString contains no lines")
        geometry_type = "MultiLineString"
    elif geometry_code == WKB_POLYGON:
        geometry_type = "Polygon"
        coordinates = _read_polygon(reader)
    elif geometry_code == WKB_MULTIPOLYGON:
        _read_header(reader)
        coordinates = [_read_polygon(reader, nested=True) for _ in range(reader.uint32(endian))]
        if not coordinates:
            raise RuntimeError("GeoPackage MultiPolygon contains no polygons")
        geometry_type = "MultiPolygon"
    else:
        raise RuntimeError(f"Unsupported GeoPackage WKB geometry type: {geometry_code}")
    if reader.offset != len(reader.data):
        raise RuntimeError("GeoPackage geometry WKB has trailing bytes")
    actual_bounds = map_geometry_bounds(geometry_type, coordinates)
    if actual_bounds != envelope:
        raise RuntimeError("GeoPackage geometry envelope does not match WKB bounds")
    return DecodedGeometry(geometry_type, coordinates, srs_id, envelope, wkb)


def decode_geopackage_polygon(blob: bytes) -> DecodedGeometry:
    decoded = decode_geopackage_geometry(blob)
    if decoded.geometry_type not in ("Polygon", "MultiPolygon"):
        raise RuntimeError(
            f"Unsupported GeoPackage polygon geometry type: {decoded.geometry_type}"
        )
    return decoded
