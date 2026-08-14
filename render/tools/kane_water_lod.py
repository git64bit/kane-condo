#!/usr/bin/env python3
"""Build deterministic Batch 029 water levels of detail in a flat chunked container."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sqlite3
import struct
import sys
import zlib
from pathlib import Path
from typing import Iterable, Mapping, Sequence

FORMAT = "kane-condo-water-lod"
VERSION = 1
SRS_ID = 4326
FOX_DATASET_KEY = "water-fox-river"
CREEK_DATASET_KEY = "water-creeks"
MAGIC = b"KCRW029\n"
CHUNK_FEATURES = 256
MORTON_BITS = 16
COORDINATE_SCORE_SCALE = 10_000_000

LEVELS = (
    {
        "key": "overview",
        "rank": 0,
        "creek_length_fraction": 0.0,
        "simplification_divisor": 2048.0,
        "purpose": "major-water",
    },
    {
        "key": "context",
        "rank": 1,
        "creek_length_fraction": 0.60,
        "simplification_divisor": 8192.0,
        "purpose": "regional-water-context",
    },
    {
        "key": "detail",
        "rank": 2,
        "creek_length_fraction": 1.0,
        "simplification_divisor": None,
        "purpose": "complete-exact-water-context",
    },
)

Position = tuple[float, float]
LineString = list[Position]
MultiLineString = list[LineString]
Ring = list[Position]
Polygon = list[Ring]
MultiPolygon = list[Polygon]


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_geometry_module():
    module_path = Path(__file__).resolve().parents[2] / "database/tools/kane_geometry.py"
    spec = importlib.util.spec_from_file_location("_kane_condo_water_lod_geometry", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load geometry support: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _distance_sq(point: Position, start: Position, end: Position) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0.0 and dy == 0.0:
        px = point[0] - start[0]
        py = point[1] - start[1]
        return px * px + py * py
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    qx = start[0] + t * dx
    qy = start[1] + t * dy
    px = point[0] - qx
    py = point[1] - qy
    return px * px + py * py


def simplify_open(points: Sequence[Position], tolerance: float) -> list[Position]:
    if len(points) <= 2 or tolerance <= 0.0:
        return list(points)
    threshold = tolerance * tolerance
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best_index = -1
        best_distance = -1.0
        for index in range(first + 1, last):
            distance = _distance_sq(points[index], points[first], points[last])
            if distance > best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance > threshold:
            keep.add(best_index)
            stack.append((first, best_index))
            stack.append((best_index, last))
    return [points[index] for index in sorted(keep)]


def simplify_line(points: Sequence[Position], tolerance: float) -> LineString:
    simplified = simplify_open(points, tolerance)
    if len(set(simplified)) < 2:
        return [points[0], points[-1]]
    return simplified


def simplify_ring(ring: Sequence[Position], tolerance: float) -> Ring:
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise RuntimeError("Accepted water polygon ring is not a valid closed ring")
    points = list(ring[:-1])
    if tolerance <= 0.0 or len(points) <= 3:
        return points + [points[0]]

    anchor_index = min(
        range(len(points)), key=lambda index: (points[index][0], points[index][1], index)
    )
    rotated = points[anchor_index:] + points[:anchor_index]
    anchor = rotated[0]
    split_index = max(
        range(1, len(rotated)),
        key=lambda index: (
            _distance_sq(rotated[index], anchor, anchor),
            -index,
        ),
    )
    first = simplify_open(rotated[: split_index + 1], tolerance)
    second_path = rotated[split_index:] + [anchor]
    second = simplify_open(second_path, tolerance)
    simplified = first[:-1] + second[:-1]
    if len(set(simplified)) < 3:
        return points + [points[0]]
    return simplified + [simplified[0]]


def geometry_lines(geometry_type: str, coordinates: object) -> list[LineString]:
    if geometry_type == "LineString":
        values = [coordinates]
    elif geometry_type == "MultiLineString":
        values = coordinates
    else:
        raise RuntimeError(f"Water line has unsupported geometry type: {geometry_type}")
    if not isinstance(values, list) or not values:
        raise RuntimeError("Water line geometry contains no components")
    result: list[LineString] = []
    for line in values:
        if not isinstance(line, list) or len(line) < 2:
            raise RuntimeError("Water line component contains fewer than two positions")
        result.append([(float(x), float(y)) for x, y in line])
    return result


def geometry_polygons(geometry_type: str, coordinates: object) -> list[Polygon]:
    if geometry_type == "Polygon":
        values = [coordinates]
    elif geometry_type == "MultiPolygon":
        values = coordinates
    else:
        raise RuntimeError(f"Water polygon has unsupported geometry type: {geometry_type}")
    if not isinstance(values, list) or not values:
        raise RuntimeError("Water polygon geometry contains no polygons")
    polygons: list[Polygon] = []
    for polygon in values:
        if not isinstance(polygon, list) or not polygon:
            raise RuntimeError("Water polygon contains no rings")
        rings: Polygon = []
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise RuntimeError("Water polygon ring contains fewer than four positions")
            normalized = [(float(x), float(y)) for x, y in ring]
            if normalized[0] != normalized[-1]:
                raise RuntimeError("Water polygon ring is not closed")
            rings.append(normalized)
        polygons.append(rings)
    return polygons


def simplify_geometry(geometry_type: str, coordinates: object, tolerance: float) -> object:
    if geometry_type in ("LineString", "MultiLineString"):
        lines = [simplify_line(line, tolerance) for line in geometry_lines(geometry_type, coordinates)]
        return lines[0] if geometry_type == "LineString" else lines
    if geometry_type in ("Polygon", "MultiPolygon"):
        polygons = [
            [simplify_ring(ring, tolerance) for ring in polygon]
            for polygon in geometry_polygons(geometry_type, coordinates)
        ]
        return polygons[0] if geometry_type == "Polygon" else polygons
    raise RuntimeError(f"Accepted water has unsupported geometry type: {geometry_type}")


def iter_positions(geometry_type: str, coordinates: object) -> Iterable[Position]:
    if geometry_type in ("LineString", "MultiLineString"):
        for line in geometry_lines(geometry_type, coordinates):
            yield from line
        return
    if geometry_type in ("Polygon", "MultiPolygon"):
        for polygon in geometry_polygons(geometry_type, coordinates):
            for ring in polygon:
                yield from ring
        return
    raise RuntimeError(f"Accepted water has unsupported geometry type: {geometry_type}")


def geometry_bounds(geometry_type: str, coordinates: object) -> tuple[float, float, float, float]:
    points = list(iter_positions(geometry_type, coordinates))
    if not points:
        raise RuntimeError("Water geometry contains no positions")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def geometry_vertex_count(geometry_type: str, coordinates: object) -> int:
    return sum(1 for _ in iter_positions(geometry_type, coordinates))


def coordinate_length_score(geometry_type: str, coordinates: object) -> int:
    if geometry_type not in ("LineString", "MultiLineString"):
        raise RuntimeError("Coordinate-length score is only defined for creek linework")
    score = 0
    for line in geometry_lines(geometry_type, coordinates):
        for start, end in zip(line, line[1:]):
            dx = round((end[0] - start[0]) * COORDINATE_SCORE_SCALE)
            dy = round((end[1] - start[1]) * COORDINATE_SCORE_SCALE)
            score += math.isqrt(dx * dx + dy * dy)
    return max(1, score)


def union_bounds(bounds_values: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = [tuple(float(item) for item in bounds) for bounds in bounds_values]
    if not values:
        raise RuntimeError("Cannot compute bounds for an empty water set")
    return (
        min(bounds[0] for bounds in values),
        min(bounds[1] for bounds in values),
        max(bounds[2] for bounds in values),
        max(bounds[3] for bounds in values),
    )


def _load_accepted_dataset(
    connection: sqlite3.Connection,
    geometry_module: object,
    dataset_key: str,
    allowed_geometry_types: set[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    releases = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count, "
        "d.dataset_key, c.county_key, c.name AS county_name, c.state_code, c.fips_code "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN county c ON c.county_id = d.county_id "
        "WHERE d.dataset_key = ? AND sr.lifecycle_status = 'accepted' "
        "ORDER BY sr.source_release_id",
        (dataset_key,),
    ).fetchall()
    if len(releases) != 1:
        raise RuntimeError(
            f"Accepted {dataset_key} release count is {len(releases)}; expected 1"
        )
    release = releases[0]
    rows = connection.execute(
        "SELECT source_feature_id, source_ordinal, geometry, geometry_type, geometry_sha256, "
        "min_x, min_y, max_x, max_y "
        "FROM source_map_feature WHERE source_release_id = ? ORDER BY source_ordinal",
        (release["source_release_id"],),
    ).fetchall()
    if release["feature_count"] != len(rows):
        raise RuntimeError(
            f"Accepted {dataset_key} release feature_count is {release['feature_count']}; "
            f"stored feature count is {len(rows)}"
        )
    if not rows:
        raise RuntimeError(f"Accepted {dataset_key} release contains no stored features")

    features: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for expected_ordinal, row in enumerate(rows, 1):
        source_id = str(row["source_feature_id"])
        if source_id in seen_ids:
            raise RuntimeError(f"Accepted {dataset_key} source identity is duplicated: {source_id}")
        seen_ids.add(source_id)
        if row["source_ordinal"] != expected_ordinal:
            raise RuntimeError(
                f"Accepted {dataset_key} source ordinals are not contiguous at {source_id}: "
                f"expected {expected_ordinal}, found {row['source_ordinal']}"
            )
        decoded = geometry_module.decode_geopackage_geometry(row["geometry"])
        if decoded.geometry_type not in allowed_geometry_types:
            raise RuntimeError(
                f"Accepted {dataset_key} {source_id} has unsupported geometry type: "
                f"{decoded.geometry_type}"
            )
        if decoded.geometry_type != row["geometry_type"]:
            raise RuntimeError(f"Accepted {dataset_key} {source_id} geometry type is inconsistent")
        if sha256_bytes(decoded.wkb) != row["geometry_sha256"]:
            raise RuntimeError(f"Accepted {dataset_key} {source_id} geometry SHA-256 is invalid")
        stored_bounds = (row["min_x"], row["min_y"], row["max_x"], row["max_y"])
        if decoded.envelope != stored_bounds:
            raise RuntimeError(f"Accepted {dataset_key} {source_id} stored bounds are inconsistent")
        feature = {
            "dataset_key": dataset_key,
            "source_feature_id": source_id,
            "source_ordinal": expected_ordinal,
            "geometry_type": decoded.geometry_type,
            "coordinates": decoded.coordinates,
            "bounds": decoded.envelope,
            "source_vertex_count": geometry_vertex_count(
                decoded.geometry_type, decoded.coordinates
            ),
        }
        if dataset_key == CREEK_DATASET_KEY:
            feature["length_score"] = coordinate_length_score(
                decoded.geometry_type, decoded.coordinates
            )
        features.append(feature)

    source = {
        "dataset_key": release["dataset_key"],
        "release_key": release["release_key"],
        "release_content_sha256": release["content_sha256"],
        "feature_count": release["feature_count"],
        "county_key": release["county_key"],
        "county_name": release["county_name"],
        "state_code": release["state_code"],
        "fips_code": release["fips_code"],
    }
    return source, features


def load_accepted_water(
    database: Path,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    geometry_module = load_geometry_module()
    try:
        fox_source, fox_features = _load_accepted_dataset(
            connection,
            geometry_module,
            FOX_DATASET_KEY,
            {"Polygon", "MultiPolygon"},
        )
        creek_source, creek_features = _load_accepted_dataset(
            connection,
            geometry_module,
            CREEK_DATASET_KEY,
            {"LineString", "MultiLineString"},
        )
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read accepted water context: {exc}") from exc
    finally:
        connection.close()

    county_fields = ("county_key", "county_name", "state_code", "fips_code")
    if any(fox_source[field] != creek_source[field] for field in county_fields):
        raise RuntimeError("Accepted Fox River and creek releases do not belong to the same county")
    source = {
        "county": {
            "county_key": fox_source["county_key"],
            "fips_code": fox_source["fips_code"],
            "name": fox_source["county_name"],
            "state_code": fox_source["state_code"],
        },
        "datasets": {
            "fox_river": {
                "dataset_key": fox_source["dataset_key"],
                "feature_count": fox_source["feature_count"],
                "release_content_sha256": fox_source["release_content_sha256"],
                "release_key": fox_source["release_key"],
            },
            "creeks": {
                "dataset_key": creek_source["dataset_key"],
                "feature_count": creek_source["feature_count"],
                "release_content_sha256": creek_source["release_content_sha256"],
                "release_key": creek_source["release_key"],
            },
        },
    }
    return source, fox_features, creek_features


def selected_creek_ids_by_fraction(
    features: Sequence[Mapping[str, object]], fraction: float
) -> set[str]:
    if not 0.0 <= fraction <= 1.0:
        raise RuntimeError(f"Invalid creek LOD cumulative length fraction: {fraction}")
    if fraction == 0.0:
        return set()
    ranked = sorted(
        features,
        key=lambda feature: (
            -int(feature["length_score"]),
            str(feature["source_feature_id"]),
        ),
    )
    if fraction >= 1.0:
        return {str(feature["source_feature_id"]) for feature in ranked}
    total = sum(int(feature["length_score"]) for feature in ranked)
    target = total * fraction
    selected: set[str] = set()
    cumulative = 0
    for feature in ranked:
        selected.add(str(feature["source_feature_id"]))
        cumulative += int(feature["length_score"])
        if cumulative >= target:
            break
    return selected


def _quantize(value: float, minimum: float, maximum: float) -> int:
    if maximum <= minimum:
        return 0
    scaled = (value - minimum) / (maximum - minimum)
    scaled = min(1.0, max(0.0, scaled))
    return min((1 << MORTON_BITS) - 1, int(scaled * ((1 << MORTON_BITS) - 1)))


def _spread_16(value: int) -> int:
    value &= 0xFFFF
    value = (value | (value << 8)) & 0x00FF00FF
    value = (value | (value << 4)) & 0x0F0F0F0F
    value = (value | (value << 2)) & 0x33333333
    value = (value | (value << 1)) & 0x55555555
    return value


def morton_key(bounds: Sequence[float], full_bounds: Sequence[float]) -> int:
    cx = (float(bounds[0]) + float(bounds[2])) / 2.0
    cy = (float(bounds[1]) + float(bounds[3])) / 2.0
    x = _quantize(cx, float(full_bounds[0]), float(full_bounds[2]))
    y = _quantize(cy, float(full_bounds[1]), float(full_bounds[3]))
    return _spread_16(x) | (_spread_16(y) << 1)


def record_for_level(feature: Mapping[str, object], tolerance: float) -> dict[str, object]:
    geometry_type = str(feature["geometry_type"])
    coordinates = simplify_geometry(geometry_type, feature["coordinates"], tolerance)
    return {
        "bounds": list(geometry_bounds(geometry_type, coordinates)),
        "coordinates": coordinates,
        "dataset_key": feature["dataset_key"],
        "geometry_type": geometry_type,
        "source_feature_id": feature["source_feature_id"],
    }


def build_level_records(
    fox_features: Sequence[Mapping[str, object]],
    creek_features: Sequence[Mapping[str, object]],
    *,
    selected_creek_ids: set[str],
    tolerance: float,
    full_bounds: Sequence[float],
) -> list[dict[str, object]]:
    selected = list(fox_features) + [
        feature
        for feature in creek_features
        if str(feature["source_feature_id"]) in selected_creek_ids
    ]
    selected.sort(
        key=lambda feature: (
            morton_key(feature["bounds"], full_bounds),
            str(feature["dataset_key"]),
            str(feature["source_feature_id"]),
        )
    )
    return [record_for_level(feature, tolerance) for feature in selected]


def build_chunks(
    records: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[bytes]]:
    chunks: list[dict[str, object]] = []
    payloads: list[bytes] = []
    offset = 0
    for start in range(0, len(records), CHUNK_FEATURES):
        group = list(records[start : start + CHUNK_FEATURES])
        raw = canonical_json_bytes(group)
        compressed = zlib.compress(raw, level=9)
        bounds = union_bounds(record["bounds"] for record in group)
        chunk = {
            "bounds": list(bounds),
            "feature_count": len(group),
            "length": len(compressed),
            "offset": offset,
            "payload_sha256": sha256_bytes(compressed),
            "records_sha256": sha256_bytes(raw),
            "uncompressed_length": len(raw),
        }
        chunks.append(chunk)
        payloads.append(compressed)
        offset += len(compressed)
    return chunks, payloads


def build_container(database: Path) -> tuple[dict[str, object], bytes]:
    source, fox_features, creek_features = load_accepted_water(database)
    all_features = fox_features + creek_features
    full_bounds = union_bounds(feature["bounds"] for feature in all_features)
    extent = max(full_bounds[2] - full_bounds[0], full_bounds[3] - full_bounds[1])
    if extent <= 0.0:
        raise RuntimeError("Accepted water bounds are empty or degenerate")

    payloads: list[bytes] = []
    payload_offset = 0
    level_documents: list[dict[str, object]] = []
    previous_creek_ids: set[str] = set()

    for level in LEVELS:
        selected_creek_ids = selected_creek_ids_by_fraction(
            creek_features, float(level["creek_length_fraction"])
        )
        if previous_creek_ids and not previous_creek_ids.issubset(selected_creek_ids):
            raise RuntimeError("Water LOD creek selection is not monotonic")
        previous_creek_ids = selected_creek_ids
        divisor = level["simplification_divisor"]
        tolerance = 0.0 if divisor is None else extent / float(divisor)
        records = build_level_records(
            fox_features,
            creek_features,
            selected_creek_ids=selected_creek_ids,
            tolerance=tolerance,
            full_bounds=full_bounds,
        )
        chunks, level_payloads = build_chunks(records)
        for chunk in chunks:
            chunk["offset"] = int(chunk["offset"]) + payload_offset
        payloads.extend(level_payloads)
        payload_offset += sum(len(payload) for payload in level_payloads)

        selected_features = list(fox_features) + [
            feature
            for feature in creek_features
            if str(feature["source_feature_id"]) in selected_creek_ids
        ]
        source_vertex_count = sum(
            int(feature["source_vertex_count"]) for feature in selected_features
        )
        output_vertex_count = sum(
            geometry_vertex_count(str(record["geometry_type"]), record["coordinates"])
            for record in records
        )
        if tolerance == 0.0 and output_vertex_count != source_vertex_count:
            raise RuntimeError("Exact water LOD changed source vertex count")
        if output_vertex_count > source_vertex_count:
            raise RuntimeError("Water LOD simplification increased vertex count")

        level_documents.append(
            {
                "chunks": chunks,
                "creek_feature_count": len(selected_creek_ids),
                "creek_length_fraction": level["creek_length_fraction"],
                "feature_count": len(records),
                "fox_river_feature_count": len(fox_features),
                "key": level["key"],
                "purpose": level["purpose"],
                "rank": level["rank"],
                "simplification_tolerance_degrees": tolerance,
                "source_vertex_count": source_vertex_count,
                "vertex_count": output_vertex_count,
            }
        )

    if len(previous_creek_ids) != len(creek_features):
        raise RuntimeError("Detail water LOD does not contain the complete accepted creek network")

    index = {
        "chunk_feature_limit": CHUNK_FEATURES,
        "format": FORMAT,
        "levels": level_documents,
        "selection": {
            "creek_basis": "deterministic-coordinate-length-score",
            "coordinate_score_scale": COORDINATE_SCORE_SCALE,
            "fox_river_rule": "all-accepted-features-in-every-level",
            "note": (
                "Accepted creek data exposes only source identity; context membership is geometric "
                "rather than a claimed hydrologic importance class."
            ),
        },
        "source": source,
        "srs_id": SRS_ID,
        "version": VERSION,
        "water_bounds": list(full_bounds),
    }
    index_bytes = canonical_json_bytes(index)
    container = MAGIC + struct.pack(">Q", len(index_bytes)) + index_bytes + b"".join(payloads)
    return index, container


def read_container_bytes(
    data: bytes,
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    if len(data) < len(MAGIC) + 8 or not data.startswith(MAGIC):
        raise RuntimeError("Water LOD container has an invalid magic header")
    index_length = struct.unpack(">Q", data[len(MAGIC) : len(MAGIC) + 8])[0]
    index_start = len(MAGIC) + 8
    index_end = index_start + index_length
    if index_end > len(data):
        raise RuntimeError("Water LOD container index is truncated")
    index_bytes = data[index_start:index_end]
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Water LOD container index is invalid JSON: {exc}") from exc
    if canonical_json_bytes(index) != index_bytes:
        raise RuntimeError("Water LOD container index is not canonical JSON")
    if index.get("format") != FORMAT or index.get("version") != VERSION:
        raise RuntimeError("Water LOD container format/version is unsupported")

    payload_area = data[index_end:]
    expected_offset = 0
    levels: dict[str, list[dict[str, object]]] = {}
    for level in index.get("levels", []):
        key = str(level["key"])
        records: list[dict[str, object]] = []
        for chunk in level.get("chunks", []):
            offset = int(chunk["offset"])
            length = int(chunk["length"])
            if offset != expected_offset:
                raise RuntimeError("Water LOD payload offsets are not contiguous")
            end = offset + length
            if end > len(payload_area):
                raise RuntimeError("Water LOD payload is truncated")
            compressed = payload_area[offset:end]
            if sha256_bytes(compressed) != chunk["payload_sha256"]:
                raise RuntimeError("Water LOD payload SHA-256 is invalid")
            try:
                raw = zlib.decompress(compressed)
            except zlib.error as exc:
                raise RuntimeError(f"Water LOD payload compression is invalid: {exc}") from exc
            if len(raw) != chunk["uncompressed_length"]:
                raise RuntimeError("Water LOD uncompressed payload length is invalid")
            if sha256_bytes(raw) != chunk["records_sha256"]:
                raise RuntimeError("Water LOD record SHA-256 is invalid")
            try:
                chunk_records = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Water LOD records are invalid JSON: {exc}") from exc
            if canonical_json_bytes(chunk_records) != raw:
                raise RuntimeError("Water LOD records are not canonical JSON")
            if not isinstance(chunk_records, list) or len(chunk_records) != chunk["feature_count"]:
                raise RuntimeError("Water LOD chunk feature count is invalid")
            records.extend(chunk_records)
            expected_offset = end
        if len(records) != level["feature_count"]:
            raise RuntimeError(f"Water LOD level {key} feature count is invalid")
        levels[key] = records
    if expected_offset != len(payload_area):
        raise RuntimeError("Water LOD container has trailing payload bytes")
    return index, levels


def write_container(database: Path, output: Path) -> dict[str, object]:
    database = database.resolve()
    output = output.resolve()
    if output == database:
        raise RuntimeError("Water LOD output path must not replace the authoritative database")
    index, payload = build_container(database)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    level_counts = {
        str(level["key"]): int(level["feature_count"])
        for level in index["levels"]
    }
    return {
        "byte_length": len(payload),
        "level_feature_counts": level_counts,
        "output_file": str(output),
        "sha256": sha256_bytes(payload),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build deterministic water LOD container")
    build.add_argument("database", type=Path)
    build.add_argument("output", type=Path)
    inspect = subparsers.add_parser("inspect", help="validate and summarize a water LOD container")
    inspect.add_argument("container", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = write_container(args.database, args.output)
        else:
            data = args.container.resolve().read_bytes()
            index, levels = read_container_bytes(data)
            result = {
                "byte_length": len(data),
                "level_feature_counts": {key: len(records) for key, records in levels.items()},
                "sha256": sha256_bytes(data),
                "source_releases": {
                    "creeks": index["source"]["datasets"]["creeks"]["release_key"],
                    "fox_river": index["source"]["datasets"]["fox_river"]["release_key"],
                },
            }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
