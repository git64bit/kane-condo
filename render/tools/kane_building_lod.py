#!/usr/bin/env python3
"""Build deterministic Batch 030 building levels of detail in a flat chunked container."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import struct
import sys
import zlib
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Mapping, Sequence

FORMAT = "kane-condo-building-lod"
VERSION = 1
SRS_ID = 4326
DATASET_KEY = "buildings"
MAGIC = b"KCBD030\n"
CHUNK_FEATURES = 512
MORTON_BITS = 16
COORDINATE_SCORE_SCALE = 10_000_000

LEVELS = (
    {
        "key": "context",
        "rank": 0,
        "cumulative_area_fraction": 0.35,
        "simplification_divisor": 8192.0,
        "purpose": "large-building-context",
    },
    {
        "key": "neighborhood",
        "rank": 1,
        "cumulative_area_fraction": 1.0,
        "simplification_divisor": 32768.0,
        "purpose": "complete-neighborhood-buildings",
    },
    {
        "key": "editing",
        "rank": 2,
        "cumulative_area_fraction": 1.0,
        "simplification_divisor": None,
        "purpose": "complete-exact-editing-footprints",
    },
)

Position = tuple[float, float]
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
    spec = importlib.util.spec_from_file_location("_kane_condo_building_lod_geometry", module_path)
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


def simplify_ring(ring: Sequence[Position], tolerance: float) -> Ring:
    if len(ring) < 4 or ring[0] != ring[-1]:
        raise RuntimeError("Accepted building polygon ring is not a valid closed ring")
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
        key=lambda index: (_distance_sq(rotated[index], anchor, anchor), -index),
    )
    first = simplify_open(rotated[: split_index + 1], tolerance)
    second = simplify_open(rotated[split_index:] + [anchor], tolerance)
    simplified = first[:-1] + second[:-1]
    if len(set(simplified)) < 3:
        return points + [points[0]]
    return simplified + [simplified[0]]


def geometry_polygons(geometry_type: str, coordinates: object) -> list[Polygon]:
    if geometry_type == "Polygon":
        values = [coordinates]
    elif geometry_type == "MultiPolygon":
        values = coordinates
    else:
        raise RuntimeError(f"Building has unsupported geometry type: {geometry_type}")
    if not isinstance(values, list) or not values:
        raise RuntimeError("Building geometry contains no polygons")
    result: list[Polygon] = []
    for polygon in values:
        if not isinstance(polygon, list) or not polygon:
            raise RuntimeError("Building polygon contains no rings")
        rings: Polygon = []
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise RuntimeError("Building polygon ring contains fewer than four positions")
            normalized = [(float(x), float(y)) for x, y in ring]
            if normalized[0] != normalized[-1]:
                raise RuntimeError("Building polygon ring is not closed")
            if len(set(normalized[:-1])) < 3:
                raise RuntimeError("Building polygon ring has fewer than three distinct vertices")
            rings.append(normalized)
        result.append(rings)
    return result


def simplify_geometry(geometry_type: str, coordinates: object, tolerance: float) -> object:
    polygons = [
        [simplify_ring(ring, tolerance) for ring in polygon]
        for polygon in geometry_polygons(geometry_type, coordinates)
    ]
    return polygons[0] if geometry_type == "Polygon" else polygons


def iter_positions(geometry_type: str, coordinates: object) -> Iterable[Position]:
    for polygon in geometry_polygons(geometry_type, coordinates):
        for ring in polygon:
            yield from ring


def geometry_bounds(geometry_type: str, coordinates: object) -> tuple[float, float, float, float]:
    points = list(iter_positions(geometry_type, coordinates))
    if not points:
        raise RuntimeError("Building geometry contains no positions")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def geometry_vertex_count(geometry_type: str, coordinates: object) -> int:
    return sum(1 for _ in iter_positions(geometry_type, coordinates))


def _ring_area_score(ring: Sequence[Position]) -> int:
    scaled = [
        (
            round(point[0] * COORDINATE_SCORE_SCALE),
            round(point[1] * COORDINATE_SCORE_SCALE),
        )
        for point in ring
    ]
    total = 0
    for start, end in zip(scaled, scaled[1:]):
        total += start[0] * end[1] - end[0] * start[1]
    return abs(total)


def coordinate_area_score(geometry_type: str, coordinates: object) -> int:
    score = 0
    for polygon in geometry_polygons(geometry_type, coordinates):
        outer = _ring_area_score(polygon[0])
        holes = sum(_ring_area_score(ring) for ring in polygon[1:])
        score += max(0, outer - holes)
    return max(1, score)


def union_bounds(bounds_values: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = [tuple(float(item) for item in bounds) for bounds in bounds_values]
    if not values:
        raise RuntimeError("Cannot compute bounds for an empty building set")
    return (
        min(bounds[0] for bounds in values),
        min(bounds[1] for bounds in values),
        max(bounds[2] for bounds in values),
        max(bounds[3] for bounds in values),
    )


def load_accepted_buildings(database: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    geometry_module = load_geometry_module()
    try:
        releases = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count, "
            "d.dataset_key, c.county_key, c.name AS county_name, c.state_code, c.fips_code "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN county c ON c.county_id = d.county_id "
            "WHERE d.dataset_key = ? AND sr.lifecycle_status = 'accepted' "
            "ORDER BY sr.source_release_id",
            (DATASET_KEY,),
        ).fetchall()
        if len(releases) != 1:
            raise RuntimeError(f"Accepted building-release count is {len(releases)}; expected 1")
        release = releases[0]
        rows = connection.execute(
            "SELECT sb.source_building_id, sb.source_feature_id, sb.source_ordinal, "
            "sb.geometry, sb.geometry_type, sb.geometry_sha256, "
            "sb.min_x, sb.min_y, sb.max_x, sb.max_y, "
            "COUNT(DISTINCT m.project_building_id) AS confirmed_mapping_count, "
            "MIN(pb.project_building_id) AS project_building_id, "
            "MIN(pb.building_key) AS building_key, "
            "MIN(pb.lifecycle_status) AS lifecycle_status "
            "FROM source_building sb "
            "LEFT JOIN project_building_source_mapping m "
            "ON m.source_building_id = sb.source_building_id AND m.mapping_status = 'confirmed' "
            "LEFT JOIN project_building pb ON pb.project_building_id = m.project_building_id "
            "WHERE sb.source_release_id = ? "
            "GROUP BY sb.source_building_id "
            "ORDER BY sb.source_ordinal",
            (release["source_release_id"],),
        )

        features: list[dict[str, object]] = []
        seen_source_ids: set[str] = set()
        seen_building_keys: set[str] = set()
        expected_ordinal = 1
        for row in rows:
            source_id = str(row["source_feature_id"])
            if source_id in seen_source_ids:
                raise RuntimeError(f"Accepted building source identity is duplicated: {source_id}")
            seen_source_ids.add(source_id)
            if int(row["source_ordinal"]) != expected_ordinal:
                raise RuntimeError(
                    f"Accepted building source ordinals are not contiguous at {source_id}: "
                    f"expected {expected_ordinal}, found {row['source_ordinal']}"
                )
            expected_ordinal += 1
            mapping_count = int(row["confirmed_mapping_count"])
            if mapping_count != 1:
                raise RuntimeError(
                    f"Accepted building {source_id} has {mapping_count} confirmed project mappings; expected 1"
                )
            if str(row["lifecycle_status"]) != "active":
                raise RuntimeError(
                    f"Accepted building {source_id} maps to non-active project building "
                    f"{row['building_key']}"
                )
            building_key = str(row["building_key"])
            if building_key in seen_building_keys:
                raise RuntimeError(f"Accepted project building is mapped more than once: {building_key}")
            seen_building_keys.add(building_key)

            geometry_blob = bytes(row["geometry"])
            decoded = geometry_module.decode_geopackage_polygon(geometry_blob)
            if decoded.geometry_type != row["geometry_type"]:
                raise RuntimeError(f"Accepted building {source_id} geometry type is inconsistent")
            if sha256_bytes(decoded.wkb) != row["geometry_sha256"]:
                raise RuntimeError(f"Accepted building {source_id} geometry SHA-256 is invalid")
            stored_bounds = (row["min_x"], row["min_y"], row["max_x"], row["max_y"])
            if decoded.envelope != stored_bounds:
                raise RuntimeError(f"Accepted building {source_id} stored bounds are inconsistent")
            features.append(
                {
                    "area_score": coordinate_area_score(decoded.geometry_type, decoded.coordinates),
                    "bounds": decoded.envelope,
                    "building_key": building_key,
                    "geometry": geometry_blob,
                    "geometry_type": decoded.geometry_type,
                    "project_building_id": int(row["project_building_id"]),
                    "source_feature_id": source_id,
                    "source_ordinal": int(row["source_ordinal"]),
                    "source_vertex_count": geometry_vertex_count(
                        decoded.geometry_type, decoded.coordinates
                    ),
                }
            )
        if int(release["feature_count"]) != len(features):
            raise RuntimeError(
                f"Accepted building release feature_count is {release['feature_count']}; "
                f"stored feature count is {len(features)}"
            )
        if not features:
            raise RuntimeError("Accepted building release contains no stored features")
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read accepted buildings: {exc}") from exc
    finally:
        connection.close()

    source = {
        "dataset_key": release["dataset_key"],
        "release_key": release["release_key"],
        "release_content_sha256": release["content_sha256"],
        "feature_count": int(release["feature_count"]),
        "county_key": release["county_key"],
        "county_name": release["county_name"],
        "state_code": release["state_code"],
        "fips_code": release["fips_code"],
    }
    return source, features


def selected_features_by_fraction(
    features: Sequence[Mapping[str, object]], fraction: float
) -> list[Mapping[str, object]]:
    if not 0.0 < fraction <= 1.0:
        raise RuntimeError(f"Invalid building LOD cumulative area fraction: {fraction}")
    if fraction >= 1.0:
        return list(features)
    ranked = sorted(
        features,
        key=lambda feature: (
            -int(feature["area_score"]),
            str(feature["building_key"]),
        ),
    )
    total = sum(int(feature["area_score"]) for feature in ranked)
    ratio = Fraction(str(fraction))
    selected: list[Mapping[str, object]] = []
    cumulative = 0
    for feature in ranked:
        selected.append(feature)
        cumulative += int(feature["area_score"])
        if cumulative * ratio.denominator >= total * ratio.numerator:
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


def record_for_level(
    feature: Mapping[str, object], tolerance: float, geometry_module: object
) -> dict[str, object]:
    decoded = geometry_module.decode_geopackage_polygon(feature["geometry"])
    geometry_type = str(feature["geometry_type"])
    if decoded.geometry_type != geometry_type:
        raise RuntimeError(
            f"Accepted building {feature['source_feature_id']} geometry changed during LOD build"
        )
    coordinates = simplify_geometry(geometry_type, decoded.coordinates, tolerance)
    return {
        "bounds": list(geometry_bounds(geometry_type, coordinates)),
        "building_key": feature["building_key"],
        "coordinates": coordinates,
        "geometry_type": geometry_type,
        "source_feature_id": feature["source_feature_id"],
    }


def build_level_chunks(
    features: Sequence[Mapping[str, object]],
    *,
    tolerance: float,
    full_bounds: Sequence[float],
    payload_offset: int,
    geometry_module: object,
) -> tuple[list[dict[str, object]], list[bytes], int, int]:
    ordered = sorted(
        features,
        key=lambda feature: (
            morton_key(feature["bounds"], full_bounds),
            str(feature["building_key"]),
        ),
    )
    chunks: list[dict[str, object]] = []
    payloads: list[bytes] = []
    offset = payload_offset
    output_vertex_count = 0
    for start in range(0, len(ordered), CHUNK_FEATURES):
        group = ordered[start : start + CHUNK_FEATURES]
        records = [record_for_level(feature, tolerance, geometry_module) for feature in group]
        output_vertex_count += sum(
            geometry_vertex_count(str(record["geometry_type"]), record["coordinates"])
            for record in records
        )
        raw = canonical_json_bytes(records)
        compressed = zlib.compress(raw, level=9)
        bounds = union_bounds(record["bounds"] for record in records)
        chunks.append(
            {
                "bounds": list(bounds),
                "feature_count": len(records),
                "length": len(compressed),
                "offset": offset,
                "payload_sha256": sha256_bytes(compressed),
                "records_sha256": sha256_bytes(raw),
                "uncompressed_length": len(raw),
            }
        )
        payloads.append(compressed)
        offset += len(compressed)
    return chunks, payloads, output_vertex_count, offset


def build_container(database: Path) -> tuple[dict[str, object], bytes]:
    source, features = load_accepted_buildings(database)
    full_bounds = union_bounds(feature["bounds"] for feature in features)
    extent = max(full_bounds[2] - full_bounds[0], full_bounds[3] - full_bounds[1])
    if extent <= 0.0:
        raise RuntimeError("Accepted building bounds are degenerate")
    geometry_module = load_geometry_module()

    level_documents: list[dict[str, object]] = []
    payloads: list[bytes] = []
    payload_offset = 0
    previous_keys: set[str] = set()

    for level in LEVELS:
        selected = selected_features_by_fraction(
            features, float(level["cumulative_area_fraction"])
        )
        selected_keys = {str(feature["building_key"]) for feature in selected}
        if previous_keys and not previous_keys.issubset(selected_keys):
            raise RuntimeError("Building LOD selection is not monotonic")
        previous_keys = selected_keys
        divisor = level["simplification_divisor"]
        tolerance = 0.0 if divisor is None else extent / float(divisor)
        chunks, level_payloads, output_vertex_count, payload_offset = build_level_chunks(
            selected,
            tolerance=tolerance,
            full_bounds=full_bounds,
            payload_offset=payload_offset,
            geometry_module=geometry_module,
        )
        payloads.extend(level_payloads)
        source_vertex_count = sum(int(feature["source_vertex_count"]) for feature in selected)
        if tolerance == 0.0 and output_vertex_count != source_vertex_count:
            raise RuntimeError("Exact building LOD changed source vertex count")
        if output_vertex_count > source_vertex_count:
            raise RuntimeError("Building LOD simplification increased vertex count")
        level_documents.append(
            {
                "chunks": chunks,
                "cumulative_area_fraction": level["cumulative_area_fraction"],
                "feature_count": len(selected),
                "key": level["key"],
                "purpose": level["purpose"],
                "rank": level["rank"],
                "simplification_tolerance_degrees": tolerance,
                "source_vertex_count": source_vertex_count,
                "vertex_count": output_vertex_count,
            }
        )

    if len(previous_keys) != len(features):
        raise RuntimeError("Editing building LOD does not contain the complete accepted building set")

    index = {
        "building_bounds": list(full_bounds),
        "chunk_feature_limit": CHUNK_FEATURES,
        "format": FORMAT,
        "identity": {
            "field": "building_key",
            "kind": "kane-condo-project-building",
            "note": "Project-owned identity; county source identity is provenance only.",
        },
        "levels": level_documents,
        "selection": {
            "basis": "deterministic-footprint-coordinate-area-score",
            "coordinate_score_scale": COORDINATE_SCORE_SCALE,
            "note": (
                "Broader levels rank accepted footprints by geometric area only; no building-use "
                "semantics are inferred."
            ),
        },
        "source": {
            "county": {
                "county_key": source["county_key"],
                "fips_code": source["fips_code"],
                "name": source["county_name"],
                "state_code": source["state_code"],
            },
            "dataset_key": source["dataset_key"],
            "feature_count": source["feature_count"],
            "release_content_sha256": source["release_content_sha256"],
            "release_key": source["release_key"],
        },
        "srs_id": SRS_ID,
        "version": VERSION,
    }
    index_bytes = canonical_json_bytes(index)
    container = MAGIC + struct.pack(">Q", len(index_bytes)) + index_bytes + b"".join(payloads)
    return index, container


def read_container_bytes(data: bytes) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    if len(data) < len(MAGIC) + 8 or not data.startswith(MAGIC):
        raise RuntimeError("Building LOD container has an invalid magic header")
    index_length = struct.unpack(">Q", data[len(MAGIC) : len(MAGIC) + 8])[0]
    index_start = len(MAGIC) + 8
    index_end = index_start + index_length
    if index_end > len(data):
        raise RuntimeError("Building LOD container index is truncated")
    index_bytes = data[index_start:index_end]
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Building LOD container index is invalid JSON: {exc}") from exc
    if canonical_json_bytes(index) != index_bytes:
        raise RuntimeError("Building LOD container index is not canonical JSON")
    if index.get("format") != FORMAT or index.get("version") != VERSION:
        raise RuntimeError("Building LOD container format/version is unsupported")

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
                raise RuntimeError("Building LOD payload offsets are not contiguous")
            end = offset + length
            if end > len(payload_area):
                raise RuntimeError("Building LOD payload is truncated")
            compressed = payload_area[offset:end]
            if sha256_bytes(compressed) != chunk["payload_sha256"]:
                raise RuntimeError("Building LOD payload SHA-256 is invalid")
            try:
                raw = zlib.decompress(compressed)
            except zlib.error as exc:
                raise RuntimeError(f"Building LOD payload compression is invalid: {exc}") from exc
            if len(raw) != chunk["uncompressed_length"]:
                raise RuntimeError("Building LOD uncompressed payload length is invalid")
            if sha256_bytes(raw) != chunk["records_sha256"]:
                raise RuntimeError("Building LOD record SHA-256 is invalid")
            try:
                chunk_records = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Building LOD records are invalid JSON: {exc}") from exc
            if canonical_json_bytes(chunk_records) != raw:
                raise RuntimeError("Building LOD records are not canonical JSON")
            if not isinstance(chunk_records, list) or len(chunk_records) != chunk["feature_count"]:
                raise RuntimeError("Building LOD chunk feature count is invalid")
            records.extend(chunk_records)
            expected_offset = end
        if len(records) != level["feature_count"]:
            raise RuntimeError(f"Building LOD level {key} feature count is invalid")
        identities = [record.get("building_key") for record in records]
        if len(identities) != len(set(identities)):
            raise RuntimeError(f"Building LOD level {key} contains duplicate project identity")
        levels[key] = records
    if expected_offset != len(payload_area):
        raise RuntimeError("Building LOD container has trailing payload bytes")
    return index, levels


def write_container(database: Path, output: Path) -> dict[str, object]:
    database = database.resolve()
    output = output.resolve()
    if output == database:
        raise RuntimeError("Building LOD output path must not replace the authoritative database")
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
    build = subparsers.add_parser("build", help="build deterministic building LOD container")
    build.add_argument("database", type=Path)
    build.add_argument("output", type=Path)
    inspect = subparsers.add_parser("inspect", help="validate and summarize a building LOD container")
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
                "source_release": index["source"]["release_key"],
            }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
