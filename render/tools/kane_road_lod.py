#!/usr/bin/env python3
"""Build deterministic Batch 028 road levels of detail in a flat chunked container."""

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

FORMAT = "kane-condo-road-lod"
VERSION = 1
SRS_ID = 4326
DATASET_KEY = "roads"
MAGIC = b"KCRD028\n"
CHUNK_FEATURES = 256
MORTON_BITS = 16
COORDINATE_SCORE_SCALE = 10_000_000

LEVELS = (
    {
        "key": "orientation",
        "rank": 0,
        "cumulative_length_fraction": 0.35,
        "simplification_divisor": 2048.0,
        "purpose": "county-orientation",
    },
    {
        "key": "context",
        "rank": 1,
        "cumulative_length_fraction": 0.75,
        "simplification_divisor": 8192.0,
        "purpose": "regional-context",
    },
    {
        "key": "detail",
        "rank": 2,
        "cumulative_length_fraction": 1.0,
        "simplification_divisor": None,
        "purpose": "complete-exact-network",
    },
)

Position = tuple[float, float]
LineString = list[Position]
MultiLineString = list[LineString]


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
    spec = importlib.util.spec_from_file_location("_kane_condo_road_lod_geometry", module_path)
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


def simplify_line(points: Sequence[Position], tolerance: float) -> LineString:
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
    simplified = [points[index] for index in sorted(keep)]
    if len(set(simplified)) < 2:
        return [points[0], points[-1]]
    return simplified


def geometry_lines(geometry_type: str, coordinates: object) -> list[LineString]:
    if geometry_type == "LineString":
        values = [coordinates]
    elif geometry_type == "MultiLineString":
        values = coordinates
    else:
        raise RuntimeError(f"Accepted road has unsupported geometry type: {geometry_type}")
    if not isinstance(values, list) or not values:
        raise RuntimeError("Accepted road contains no line geometry")
    result: list[LineString] = []
    for line in values:
        if not isinstance(line, list) or len(line) < 2:
            raise RuntimeError("Accepted road line contains fewer than two positions")
        result.append([(float(x), float(y)) for x, y in line])
    return result


def simplify_geometry(
    geometry_type: str, coordinates: object, tolerance: float
) -> LineString | MultiLineString:
    lines = geometry_lines(geometry_type, coordinates)
    simplified = [simplify_line(line, tolerance) for line in lines]
    return simplified[0] if geometry_type == "LineString" else simplified


def iter_positions(geometry_type: str, coordinates: object) -> Iterable[Position]:
    yield from (
        position
        for line in geometry_lines(geometry_type, coordinates)
        for position in line
    )


def geometry_bounds(geometry_type: str, coordinates: object) -> tuple[float, float, float, float]:
    points = list(iter_positions(geometry_type, coordinates))
    if not points:
        raise RuntimeError("Road geometry contains no positions")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def geometry_vertex_count(geometry_type: str, coordinates: object) -> int:
    return sum(len(line) for line in geometry_lines(geometry_type, coordinates))


def coordinate_length_score(geometry_type: str, coordinates: object) -> int:
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
        raise RuntimeError("Cannot compute bounds for an empty road set")
    return (
        min(bounds[0] for bounds in values),
        min(bounds[1] for bounds in values),
        max(bounds[2] for bounds in values),
        max(bounds[3] for bounds in values),
    )


def load_accepted_roads(database: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
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
            raise RuntimeError(f"Accepted road-release count is {len(releases)}; expected 1")
        release = releases[0]
        rows = connection.execute(
            "SELECT source_feature_id, source_ordinal, geometry, geometry_type, geometry_sha256, "
            "min_x, min_y, max_x, max_y "
            "FROM source_map_feature WHERE source_release_id = ? ORDER BY source_ordinal",
            (release["source_release_id"],),
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read accepted roads: {exc}") from exc
    finally:
        connection.close()

    if release["feature_count"] != len(rows):
        raise RuntimeError(
            f"Accepted road release feature_count is {release['feature_count']}; "
            f"stored feature count is {len(rows)}"
        )
    if not rows:
        raise RuntimeError("Accepted road release contains no stored features")

    geometry_module = load_geometry_module()
    features: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for expected_ordinal, row in enumerate(rows, 1):
        source_id = str(row["source_feature_id"])
        if source_id in seen_ids:
            raise RuntimeError(f"Accepted road source identity is duplicated: {source_id}")
        seen_ids.add(source_id)
        if row["source_ordinal"] != expected_ordinal:
            raise RuntimeError(
                f"Accepted road source ordinals are not contiguous at {source_id}: "
                f"expected {expected_ordinal}, found {row['source_ordinal']}"
            )
        decoded = geometry_module.decode_geopackage_geometry(row["geometry"])
        if decoded.geometry_type not in ("LineString", "MultiLineString"):
            raise RuntimeError(
                f"Accepted road {source_id} has unsupported geometry type: {decoded.geometry_type}"
            )
        if decoded.geometry_type != row["geometry_type"]:
            raise RuntimeError(f"Accepted road {source_id} geometry type is inconsistent")
        if sha256_bytes(decoded.wkb) != row["geometry_sha256"]:
            raise RuntimeError(f"Accepted road {source_id} geometry SHA-256 is invalid")
        stored_bounds = (row["min_x"], row["min_y"], row["max_x"], row["max_y"])
        if decoded.envelope != stored_bounds:
            raise RuntimeError(f"Accepted road {source_id} stored bounds are inconsistent")
        features.append(
            {
                "source_feature_id": source_id,
                "source_ordinal": expected_ordinal,
                "geometry_type": decoded.geometry_type,
                "coordinates": decoded.coordinates,
                "bounds": decoded.envelope,
                "length_score": coordinate_length_score(decoded.geometry_type, decoded.coordinates),
                "source_vertex_count": geometry_vertex_count(
                    decoded.geometry_type, decoded.coordinates
                ),
            }
        )

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


def selected_ids_by_fraction(
    features: Sequence[Mapping[str, object]], fraction: float
) -> set[str]:
    if not 0.0 < fraction <= 1.0:
        raise RuntimeError(f"Invalid road LOD cumulative length fraction: {fraction}")
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


def record_for_level(
    feature: Mapping[str, object], tolerance: float
) -> dict[str, object]:
    geometry_type = str(feature["geometry_type"])
    coordinates = simplify_geometry(geometry_type, feature["coordinates"], tolerance)
    bounds = geometry_bounds(geometry_type, coordinates)
    return {
        "bounds": list(bounds),
        "coordinates": coordinates,
        "geometry_type": geometry_type,
        "source_feature_id": feature["source_feature_id"],
    }


def build_level_records(
    features: Sequence[Mapping[str, object]],
    *,
    selected_ids: set[str],
    tolerance: float,
    full_bounds: Sequence[float],
) -> list[dict[str, object]]:
    selected = [
        feature for feature in features if str(feature["source_feature_id"]) in selected_ids
    ]
    selected.sort(
        key=lambda feature: (
            morton_key(feature["bounds"], full_bounds),
            str(feature["source_feature_id"]),
        )
    )
    return [record_for_level(feature, tolerance) for feature in selected]


def build_chunks(records: Sequence[Mapping[str, object]]) -> tuple[list[dict[str, object]], list[bytes]]:
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
    source, features = load_accepted_roads(database)
    full_bounds = union_bounds(feature["bounds"] for feature in features)
    extent = max(full_bounds[2] - full_bounds[0], full_bounds[3] - full_bounds[1])
    if extent <= 0.0:
        raise RuntimeError("Accepted road bounds are degenerate")

    level_documents: list[dict[str, object]] = []
    payloads: list[bytes] = []
    payload_offset = 0
    previous_ids: set[str] = set()

    for level in LEVELS:
        selected_ids = selected_ids_by_fraction(
            features, float(level["cumulative_length_fraction"])
        )
        if previous_ids and not previous_ids.issubset(selected_ids):
            raise RuntimeError("Road LOD selection is not monotonic")
        previous_ids = selected_ids
        divisor = level["simplification_divisor"]
        tolerance = 0.0 if divisor is None else extent / float(divisor)
        records = build_level_records(
            features,
            selected_ids=selected_ids,
            tolerance=tolerance,
            full_bounds=full_bounds,
        )
        chunks, level_payloads = build_chunks(records)
        for chunk in chunks:
            chunk["offset"] = int(chunk["offset"]) + payload_offset
        payloads.extend(level_payloads)
        payload_offset += sum(len(payload) for payload in level_payloads)

        source_vertex_count = sum(
            int(feature["source_vertex_count"])
            for feature in features
            if str(feature["source_feature_id"]) in selected_ids
        )
        output_vertex_count = sum(
            geometry_vertex_count(str(record["geometry_type"]), record["coordinates"])
            for record in records
        )
        if tolerance == 0.0 and output_vertex_count != source_vertex_count:
            raise RuntimeError("Exact road LOD changed source vertex count")
        if output_vertex_count > source_vertex_count:
            raise RuntimeError("Road LOD simplification increased vertex count")

        level_documents.append(
            {
                "chunks": chunks,
                "cumulative_length_fraction": level["cumulative_length_fraction"],
                "feature_count": len(records),
                "key": level["key"],
                "purpose": level["purpose"],
                "rank": level["rank"],
                "simplification_tolerance_degrees": tolerance,
                "source_vertex_count": source_vertex_count,
                "vertex_count": output_vertex_count,
            }
        )

    if len(previous_ids) != len(features):
        raise RuntimeError("Detail road LOD does not contain the complete accepted network")

    index = {
        "chunk_feature_limit": CHUNK_FEATURES,
        "format": FORMAT,
        "levels": level_documents,
        "road_bounds": list(full_bounds),
        "selection": {
            "basis": "deterministic-coordinate-length-score",
            "coordinate_score_scale": COORDINATE_SCORE_SCALE,
            "note": (
                "Accepted roads expose only source identity; overview/context membership is "
                "therefore geometric rather than a claimed functional road class."
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
        raise RuntimeError("Road LOD container has an invalid magic header")
    index_length = struct.unpack(">Q", data[len(MAGIC) : len(MAGIC) + 8])[0]
    index_start = len(MAGIC) + 8
    index_end = index_start + index_length
    if index_end > len(data):
        raise RuntimeError("Road LOD container index is truncated")
    index_bytes = data[index_start:index_end]
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Road LOD container index is invalid JSON: {exc}") from exc
    if canonical_json_bytes(index) != index_bytes:
        raise RuntimeError("Road LOD container index is not canonical JSON")
    if index.get("format") != FORMAT or index.get("version") != VERSION:
        raise RuntimeError("Road LOD container format/version is unsupported")

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
                raise RuntimeError("Road LOD payload offsets are not contiguous")
            end = offset + length
            if end > len(payload_area):
                raise RuntimeError("Road LOD payload is truncated")
            compressed = payload_area[offset:end]
            if sha256_bytes(compressed) != chunk["payload_sha256"]:
                raise RuntimeError("Road LOD payload SHA-256 is invalid")
            try:
                raw = zlib.decompress(compressed)
            except zlib.error as exc:
                raise RuntimeError(f"Road LOD payload compression is invalid: {exc}") from exc
            if len(raw) != chunk["uncompressed_length"]:
                raise RuntimeError("Road LOD uncompressed payload length is invalid")
            if sha256_bytes(raw) != chunk["records_sha256"]:
                raise RuntimeError("Road LOD record SHA-256 is invalid")
            try:
                chunk_records = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Road LOD records are invalid JSON: {exc}") from exc
            if canonical_json_bytes(chunk_records) != raw:
                raise RuntimeError("Road LOD records are not canonical JSON")
            if not isinstance(chunk_records, list) or len(chunk_records) != chunk["feature_count"]:
                raise RuntimeError("Road LOD chunk feature count is invalid")
            records.extend(chunk_records)
            expected_offset = end
        if len(records) != level["feature_count"]:
            raise RuntimeError(f"Road LOD level {key} feature count is invalid")
        levels[key] = records
    if expected_offset != len(payload_area):
        raise RuntimeError("Road LOD container has trailing payload bytes")
    return index, levels


def write_container(database: Path, output: Path) -> dict[str, object]:
    database = database.resolve()
    output = output.resolve()
    if output == database:
        raise RuntimeError("Road LOD output path must not replace the authoritative database")
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
    build = subparsers.add_parser("build", help="build deterministic road LOD container")
    build.add_argument("database", type=Path)
    build.add_argument("output", type=Path)
    inspect = subparsers.add_parser("inspect", help="validate and summarize a road LOD container")
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
