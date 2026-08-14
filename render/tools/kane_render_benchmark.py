#!/usr/bin/env python3
"""Batch 025 controlled offline render-container benchmark.

This module benchmarks container mechanics only. It does not implement renderer,
LOD, visible tiling, classification snapshots, or the final package manifest.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import sqlite3
import statistics
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
DATABASE_TOOLS = ROOT / "database" / "tools"
if str(DATABASE_TOOLS) not in sys.path:
    sys.path.insert(0, str(DATABASE_TOOLS))

import kane_boundary  # noqa: E402
import kane_buildings  # noqa: E402
import kane_classifications  # noqa: E402
import kane_db  # noqa: E402
import kane_geometry  # noqa: E402
import kane_map_layers  # noqa: E402
import kane_project_buildings  # noqa: E402
import kane_provenance  # noqa: E402

SSOT_COMMIT = "8446dec1345625d28437748b77bdbe377033b61e"
PROTOCOL_VERSION = "kane-condo-render-container-benchmark-v3"
REPORT_SCHEMA = 1
EXPECTED_DATASET_KEYS = (
    "buildings",
    "county-boundary",
    "roads",
    "water-creeks",
    "water-fox-river",
)
CHUNK_SIZES = (256, 512, 2048)
CANDIDATE_FORMATS = ("directory", "sqlite", "flat")
STARTUP_REPETITIONS = 9
VIEWPORT_REPETITIONS = 3
HIT_TEST_SAMPLES = 128
FLAT_MAGIC = b"KCRF025\n"
CLASS_COLORS = {
    "Unclassified": "gray",
    "Other": "red",
    "Condominium": "green",
    "Apartments": "yellow",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_sha256(path: Path) -> str:
    """Deterministic digest for one file or a directory artifact."""
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise RuntimeError(f"Benchmark artifact does not exist: {path}")
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(struct.pack(">I", len(relative)))
        digest.update(relative)
        data = item.read_bytes()
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
    return digest.hexdigest()


def artifact_size_and_files(path: Path) -> tuple[int, int]:
    if path.is_file():
        return path.stat().st_size, 1
    files = [item for item in path.rglob("*") if item.is_file()]
    return sum(item.stat().st_size for item in files), len(files)


def quantile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise RuntimeError("Cannot calculate quantile of an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def timing_summary(samples: Sequence[float]) -> dict[str, Any]:
    if not samples:
        raise RuntimeError("Timing sample list is empty")
    return {
        "samples_ms": [round(value, 6) for value in samples],
        "median_ms": round(statistics.median(samples), 6),
        "p95_ms": round(quantile(samples, 0.95), 6),
    }


def bounds_intersect(
    a: Sequence[float], b: Sequence[float]
) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def morton16(x: float, y: float, bounds: Sequence[float]) -> int:
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0.0 or height <= 0.0:
        raise RuntimeError("County bounds are degenerate")
    ix = max(0, min(65535, int(((x - min_x) / width) * 65535.0)))
    iy = max(0, min(65535, int(((y - min_y) / height) * 65535.0)))

    def spread(value: int) -> int:
        value &= 0xFFFF
        value = (value | (value << 8)) & 0x00FF00FF
        value = (value | (value << 4)) & 0x0F0F0F0F
        value = (value | (value << 2)) & 0x33333333
        value = (value | (value << 1)) & 0x55555555
        return value

    return spread(ix) | (spread(iy) << 1)


def decode_mount_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def storage_environment(workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    resolved = workspace.resolve()
    stat_result = resolved.stat()
    major_minor = f"{os.major(stat_result.st_dev)}:{os.minor(stat_result.st_dev)}"
    mount_point = None
    filesystem_type = None
    mountinfo = Path("/proc/self/mountinfo")
    if mountinfo.is_file():
        candidates: list[tuple[int, str, str]] = []
        for line in mountinfo.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) < 10 or fields[2] != major_minor or "-" not in fields:
                continue
            separator = fields.index("-")
            point = decode_mount_field(fields[4])
            fs_type = fields[separator + 1] if separator + 1 < len(fields) else "unknown"
            try:
                if os.path.commonpath([str(resolved), point]) == point:
                    candidates.append((len(point), point, fs_type))
            except ValueError:
                continue
        if candidates:
            _, mount_point, filesystem_type = max(candidates)
    return {
        "workspace_path": str(resolved),
        "measurement_context": "development-orchestrator",
        "deployment_validation_status": "deferred-until-application-complete",
        "device_major_minor": major_minor,
        "filesystem_type": filesystem_type or "unknown",
        "mount_point": mount_point or "unknown",
        "cache_policy": (
            "warm-cache/index-open and warm query measurements only; candidates are built "
            "before timing and the benchmark does not evict operating-system caches"
        ),
        "cold_start_measured": False,
    }


def compatibility_matrix() -> dict[str, dict[str, Any]]:
    return {
        "directory": {
            "windows": "supported by ordinary file/directory APIs",
            "ubuntu": "supported by ordinary file/directory APIs",
            "runtime_dependency": "filesystem + zlib/JSON parser",
            "artifact_shape": "directory tree with one file per compressed chunk plus metadata",
            "replacement_characteristic": "multi-file tree replacement",
            "browser_runtime_decision": "not evaluated in Batch 025",
        },
        "sqlite": {
            "windows": "SQLite is broadly available; exact application bundling is deferred",
            "ubuntu": "SQLite is broadly available; exact application bundling is deferred",
            "runtime_dependency": "SQLite + zlib/JSON parser",
            "artifact_shape": "single SQLite file containing index and compressed chunks",
            "replacement_characteristic": "single-file replacement",
            "browser_runtime_decision": "not evaluated in Batch 025",
        },
        "flat": {
            "windows": "supported by ordinary seek/read file APIs",
            "ubuntu": "supported by ordinary seek/read file APIs",
            "runtime_dependency": "custom binary index reader + zlib/JSON parser",
            "artifact_shape": "single flat file with embedded canonical index and compressed chunks",
            "replacement_characteristic": "single-file replacement",
            "browser_runtime_decision": "not evaluated in Batch 025",
        },
    }


def protocol_summary() -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "accepted_ssot": SSOT_COMMIT,
        "candidate_formats": list(CANDIDATE_FORMATS),
        "chunk_sizes_records": list(CHUNK_SIZES),
        "startup_metric": "warm_startup_index_open_ms",
        "startup_repetitions": STARTUP_REPETITIONS,
        "startup_order": "deterministic rotating interleave across candidate formats",
        "viewport_repetitions": VIEWPORT_REPETITIONS,
        "viewport_semantics": (
            "complete record-bounds intersection after reading every intersecting chunk; no cap"
        ),
        "viewport_regimes": [
            "county-overview",
            "dense-buildings",
            "medium-buildings",
            "sparse-buildings",
            "road-heavy",
            "water-heavy",
            "editing-scale-building",
        ],
        "hit_test_samples": HIT_TEST_SAMPLES,
        "hit_test_semantics": (
            "deterministic county-spanning functional/performance probes; descriptive median/p95 "
            "are not claimed as a stable production latency distribution"
        ),
        "classification_overlay": (
            "external project-building-key mappings resolve colors without changing base artifacts"
        ),
        "scoring_rule": (
            "No weighted composite score and no automatic format selection. Final selection is a "
            "human-audited Batch 025 decision after real-dataset orchestrator evidence, "
            "compatibility analysis, and replacement-complexity analysis. Physical deployment "
            "validation is deferred until the application is complete."
        ),
    }


def validate_authoritative_database(database: Path) -> dict[str, Any]:
    database = database.resolve()
    validators = (
        ("database", kane_db.validate_database),
        ("provenance", kane_provenance.validate_database),
        ("boundary", kane_boundary.validate_database),
        ("map_layers", kane_map_layers.validate_database),
        ("buildings", kane_buildings.validate_database),
        ("project_buildings", kane_project_buildings.validate_database),
        ("classifications", kane_classifications.validate_database),
    )
    completed = []
    for name, validator in validators:
        errors = validator(database)
        if errors:
            raise RuntimeError(f"Established {name} validation failed: {'; '.join(errors)}")
        completed.append(name)
    return {"validators": completed, "all_passed": True}


def connect_read_only(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def accepted_release_identity(database: Path) -> list[dict[str, Any]]:
    with contextlib.closing(connect_read_only(database)) as connection:
        rows = connection.execute(
            "SELECT d.dataset_key, d.data_kind, sr.source_release_id, sr.release_key, "
            "sr.content_sha256, sr.feature_count "
            "FROM dataset d JOIN source_release sr ON sr.dataset_id = d.dataset_id "
            "WHERE sr.lifecycle_status = 'accepted' ORDER BY d.dataset_key"
        ).fetchall()
        keys = tuple(row["dataset_key"] for row in rows)
        if keys != EXPECTED_DATASET_KEYS:
            raise RuntimeError(
                "Accepted dataset identity mismatch: expected "
                f"{EXPECTED_DATASET_KEYS!r}, found {keys!r}"
            )
        output: list[dict[str, Any]] = []
        for row in rows:
            release_id = row["source_release_id"]
            if row["data_kind"] == "boundary":
                stored = connection.execute(
                    "SELECT COUNT(*) FROM source_county_boundary WHERE source_release_id = ?",
                    (release_id,),
                ).fetchone()[0]
            elif row["data_kind"] == "buildings":
                stored = connection.execute(
                    "SELECT COUNT(*) FROM source_building WHERE source_release_id = ?",
                    (release_id,),
                ).fetchone()[0]
            else:
                stored = connection.execute(
                    "SELECT COUNT(*) FROM source_map_feature WHERE source_release_id = ?",
                    (release_id,),
                ).fetchone()[0]
            if stored != row["feature_count"]:
                raise RuntimeError(
                    f"Accepted feature-count mismatch for {row['dataset_key']}: "
                    f"release declares {row['feature_count']}, storage has {stored}"
                )
            output.append(
                {
                    "dataset_key": row["dataset_key"],
                    "data_kind": row["data_kind"],
                    "release_key": row["release_key"],
                    "content_sha256": row["content_sha256"],
                    "feature_count": row["feature_count"],
                }
            )
        building_release_id = next(
            row["source_release_id"] for row in rows if row["dataset_key"] == "buildings"
        )
        anomalies = connection.execute(
            "SELECT sb.source_building_id, COUNT(m.mapping_id) AS mapping_count "
            "FROM source_building sb "
            "LEFT JOIN project_building_source_mapping m "
            "ON m.source_building_id = sb.source_building_id AND m.mapping_status = 'confirmed' "
            "LEFT JOIN project_building pb ON pb.project_building_id = m.project_building_id "
            "WHERE sb.source_release_id = ? "
            "GROUP BY sb.source_building_id "
            "HAVING COUNT(m.mapping_id) <> 1 OR MAX(pb.lifecycle_status) <> 'active' "
            "LIMIT 1",
            (building_release_id,),
        ).fetchone()
        if anomalies is not None:
            raise RuntimeError(
                "Accepted building release lacks exactly one confirmed active project-building "
                f"mapping at source_building_id={anomalies['source_building_id']}"
            )
    return output


def county_bounds(database: Path) -> tuple[float, float, float, float]:
    with contextlib.closing(connect_read_only(database)) as connection:
        row = connection.execute(
            "SELECT b.min_x, b.min_y, b.max_x, b.max_y "
            "FROM source_county_boundary b "
            "JOIN source_release sr ON sr.source_release_id = b.source_release_id "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "WHERE sr.lifecycle_status = 'accepted' AND d.dataset_key = 'county-boundary'"
        ).fetchone()
        if row is None:
            raise RuntimeError("Accepted county boundary is missing")
        return tuple(float(row[key]) for key in ("min_x", "min_y", "max_x", "max_y"))  # type: ignore[return-value]


def _record_from_row(dataset_key: str, row: sqlite3.Row, building_key: str | None) -> dict[str, Any]:
    decoded = kane_geometry.decode_geopackage_geometry(row["geometry"])
    if decoded.geometry_type != row["geometry_type"]:
        raise RuntimeError(f"Geometry type mismatch while staging {dataset_key}:{row['source_feature_id']}")
    attributes = json.loads(row["attributes_json"])
    if not isinstance(attributes, dict):
        raise RuntimeError("Feature attributes are not a JSON object")
    record_id = (
        f"buildings:{building_key}" if building_key is not None else f"{dataset_key}:{row['source_feature_id']}"
    )
    return {
        "record_id": record_id,
        "dataset_key": dataset_key,
        "source_feature_id": row["source_feature_id"],
        "building_key": building_key,
        "geometry_type": decoded.geometry_type,
        "coordinates": decoded.coordinates,
        "attributes": attributes,
        "bounds": [float(row[k]) for k in ("min_x", "min_y", "max_x", "max_y")],
    }


def prepare_canonical_staging(database: Path, staging: Path) -> dict[str, Any]:
    if staging.exists():
        staging.unlink()
    bounds = county_bounds(database)
    target = sqlite3.connect(staging)
    target.execute("PRAGMA journal_mode = OFF")
    target.execute("PRAGMA synchronous = OFF")
    target.executescript(
        "CREATE TABLE record ("
        "record_id TEXT PRIMARY KEY, dataset_key TEXT NOT NULL, building_key TEXT, "
        "min_x REAL NOT NULL, min_y REAL NOT NULL, max_x REAL NOT NULL, max_y REAL NOT NULL, "
        "morton INTEGER NOT NULL, record_json BLOB NOT NULL);"
        "CREATE INDEX ix_record_order ON record(morton, dataset_key, record_id);"
        "CREATE INDEX ix_record_dataset_order ON record(dataset_key, morton, record_id);"
    )
    counts = {key: 0 for key in EXPECTED_DATASET_KEYS}
    source = connect_read_only(database)
    try:
        release_rows = source.execute(
            "SELECT d.dataset_key, d.data_kind, sr.source_release_id "
            "FROM dataset d JOIN source_release sr ON sr.dataset_id = d.dataset_id "
            "WHERE sr.lifecycle_status = 'accepted' ORDER BY d.dataset_key"
        ).fetchall()
        for release in release_rows:
            dataset_key = release["dataset_key"]
            release_id = release["source_release_id"]
            if release["data_kind"] == "boundary":
                query = (
                    "SELECT source_feature_id, geometry, geometry_type, attributes_json, "
                    "min_x, min_y, max_x, max_y, NULL AS building_key "
                    "FROM source_county_boundary WHERE source_release_id = ? ORDER BY source_ordinal"
                )
            elif release["data_kind"] == "buildings":
                query = (
                    "SELECT sb.source_feature_id, sb.geometry, sb.geometry_type, sb.attributes_json, "
                    "sb.min_x, sb.min_y, sb.max_x, sb.max_y, pb.building_key "
                    "FROM source_building sb "
                    "JOIN project_building_source_mapping m ON m.source_building_id = sb.source_building_id "
                    "AND m.mapping_status = 'confirmed' "
                    "JOIN project_building pb ON pb.project_building_id = m.project_building_id "
                    "WHERE sb.source_release_id = ? ORDER BY sb.source_ordinal"
                )
            else:
                query = (
                    "SELECT source_feature_id, geometry, geometry_type, attributes_json, "
                    "min_x, min_y, max_x, max_y, NULL AS building_key "
                    "FROM source_map_feature WHERE source_release_id = ? ORDER BY source_ordinal"
                )
            insert_rows = []
            for row in source.execute(query, (release_id,)):
                record = _record_from_row(dataset_key, row, row["building_key"])
                rb = record["bounds"]
                cx = (rb[0] + rb[2]) / 2.0
                cy = (rb[1] + rb[3]) / 2.0
                insert_rows.append(
                    (
                        record["record_id"],
                        dataset_key,
                        record["building_key"],
                        *rb,
                        morton16(cx, cy, bounds),
                        canonical_bytes(record),
                    )
                )
                counts[dataset_key] += 1
                if len(insert_rows) >= 1000:
                    target.executemany(
                        "INSERT INTO record VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", insert_rows
                    )
                    insert_rows.clear()
            if insert_rows:
                target.executemany(
                    "INSERT INTO record VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", insert_rows
                )
        target.commit()
        target.execute("VACUUM")
    finally:
        source.close()
        target.close()
    return {
        "path": str(staging),
        "sha256": sha256_file(staging),
        "record_count": sum(counts.values()),
        "dataset_counts": counts,
        "county_bounds": list(bounds),
    }


def _chunk_stream(staging: Path, chunk_size: int) -> Iterator[dict[str, Any]]:
    connection = sqlite3.connect(staging)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            "SELECT record_json, min_x, min_y, max_x, max_y "
            "FROM record ORDER BY morton, dataset_key, record_id"
        )
        chunk_id = 0
        while True:
            rows = cursor.fetchmany(chunk_size)
            if not rows:
                break
            payload_raw = b"[" + b",".join(bytes(row["record_json"]) for row in rows) + b"]"
            payload = zlib.compress(payload_raw, level=9)
            yield {
                "chunk_id": chunk_id,
                "record_count": len(rows),
                "bounds": [
                    min(row["min_x"] for row in rows),
                    min(row["min_y"] for row in rows),
                    max(row["max_x"] for row in rows),
                    max(row["max_y"] for row in rows),
                ],
                "payload": payload,
                "payload_sha256": sha256_bytes(payload),
                "uncompressed_bytes": len(payload_raw),
            }
            chunk_id += 1
    finally:
        connection.close()


def candidate_paths(output: Path, chunk_size: int) -> dict[str, Path]:
    return {
        "directory": output / f"directory-{chunk_size}",
        "sqlite": output / f"sqlite-{chunk_size}.sqlite",
        "flat": output / f"flat-{chunk_size}.krf",
    }


def build_candidates(staging: Path, output: Path, chunk_size: int) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = candidate_paths(output, chunk_size)
    directory = paths["directory"]
    sqlite_path = paths["sqlite"]
    flat_path = paths["flat"]
    if directory.exists():
        for item in sorted(directory.rglob("*"), reverse=True):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        directory.rmdir()
    for path in (sqlite_path, flat_path):
        if path.exists():
            path.unlink()
    directory.mkdir()
    (directory / "chunks").mkdir()

    staging_connection = sqlite3.connect(staging)
    record_count = staging_connection.execute("SELECT COUNT(*) FROM record").fetchone()[0]
    staging_connection.close()
    common_meta = {
        "protocol_version": PROTOCOL_VERSION,
        "chunk_size_records": chunk_size,
        "record_count": record_count,
        "payload_encoding": "canonical-json-array+zlib-9",
        "spatial_order": "morton16-centroid",
    }

    sql = sqlite3.connect(sqlite_path)
    sql.execute("PRAGMA page_size = 4096")
    sql.execute("PRAGMA journal_mode = OFF")
    sql.execute("PRAGMA synchronous = OFF")
    sql.executescript(
        "CREATE TABLE metadata(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);"
        "CREATE TABLE chunk("
        "chunk_id INTEGER PRIMARY KEY, record_count INTEGER NOT NULL, "
        "min_x REAL NOT NULL, min_y REAL NOT NULL, max_x REAL NOT NULL, max_y REAL NOT NULL, "
        "payload BLOB NOT NULL, payload_sha256 TEXT NOT NULL, uncompressed_bytes INTEGER NOT NULL);"
        "CREATE INDEX ix_chunk_bounds ON chunk(min_x, max_x, min_y, max_y);"
    )
    for key, value in common_meta.items():
        sql.execute(
            "INSERT INTO metadata VALUES (?, ?)",
            (key, canonical_bytes(value).decode("utf-8")),
        )

    flat_payload = output / f".flat-{chunk_size}.payload.tmp"
    flat_handle = flat_payload.open("wb")
    index_rows: list[dict[str, Any]] = []
    try:
        for chunk in _chunk_stream(staging, chunk_size):
            chunk_name = f"{chunk['chunk_id']:06d}.bin"
            (directory / "chunks" / chunk_name).write_bytes(chunk["payload"])
            offset = flat_handle.tell()
            flat_handle.write(chunk["payload"])
            index_row = {
                "chunk_id": chunk["chunk_id"],
                "record_count": chunk["record_count"],
                "bounds": chunk["bounds"],
                "payload_sha256": chunk["payload_sha256"],
                "payload_bytes": len(chunk["payload"]),
                "uncompressed_bytes": chunk["uncompressed_bytes"],
                "flat_offset": offset,
                "directory_file": f"chunks/{chunk_name}",
            }
            index_rows.append(index_row)
            sql.execute(
                "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk["chunk_id"],
                    chunk["record_count"],
                    *chunk["bounds"],
                    chunk["payload"],
                    chunk["payload_sha256"],
                    chunk["uncompressed_bytes"],
                ),
            )
        sql.commit()
        sql.execute("VACUUM")
    finally:
        sql.close()
        flat_handle.close()

    manifest = {**common_meta, "candidate_format": "directory", "chunk_count": len(index_rows)}
    (directory / "manifest.json").write_bytes(canonical_bytes(manifest))
    (directory / "index.json").write_bytes(canonical_bytes(index_rows))

    flat_index = {
        **common_meta,
        "candidate_format": "flat",
        "chunk_count": len(index_rows),
        "chunks": [
            {key: value for key, value in row.items() if key != "directory_file"}
            for row in index_rows
        ],
    }
    flat_index_bytes = canonical_bytes(flat_index)
    with flat_path.open("wb") as output_handle:
        output_handle.write(FLAT_MAGIC)
        output_handle.write(struct.pack(">Q", len(flat_index_bytes)))
        output_handle.write(flat_index_bytes)
        with flat_payload.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                output_handle.write(block)
    flat_payload.unlink()
    return paths


@dataclass(frozen=True)
class ChunkIndex:
    chunk_id: int
    record_count: int
    bounds: tuple[float, float, float, float]
    payload_sha256: str
    payload_bytes: int
    locator: Any


class CandidateReader:
    format_name = "base"

    def __init__(self, path: Path):
        self.path = path
        self.chunk_size = 0
        self.record_count = 0
        self.chunks: list[ChunkIndex] = []

    def read_payload(self, chunk: ChunkIndex) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def viewport(self, bounds: Sequence[float]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        records: list[dict[str, Any]] = []
        payload_bytes = 0
        chunk_count = 0
        for chunk in self.chunks:
            if not bounds_intersect(chunk.bounds, bounds):
                continue
            payload = self.read_payload(chunk)
            payload_bytes += len(payload)
            chunk_count += 1
            try:
                decoded = zlib.decompress(payload)
                chunk_records = json.loads(decoded)
            except (zlib.error, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError(
                    f"{self.format_name} chunk {chunk.chunk_id} payload is invalid"
                ) from exc
            if not isinstance(chunk_records, list) or len(chunk_records) != chunk.record_count:
                raise RuntimeError(
                    f"{self.format_name} chunk {chunk.chunk_id} record count is invalid"
                )
            for record in chunk_records:
                if not isinstance(record, dict) or not bounds_intersect(record["bounds"], bounds):
                    continue
                records.append(record)
        records.sort(key=lambda item: item["record_id"])
        return records, {"chunks_read": chunk_count, "payload_bytes_read": payload_bytes}

    def hit_test(self, point: tuple[float, float]) -> tuple[list[str], dict[str, int]]:
        records, stats = self.viewport((point[0], point[1], point[0], point[1]))
        keys = sorted(
            record["building_key"]
            for record in records
            if record["dataset_key"] == "buildings"
            and record["building_key"] is not None
            and point_in_geometry(point, record["geometry_type"], record["coordinates"])
        )
        return keys, stats


class DirectoryReader(CandidateReader):
    format_name = "directory"

    def __init__(self, path: Path):
        super().__init__(path)
        try:
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            index = json.loads((path / "index.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Directory candidate metadata is invalid") from exc
        if manifest.get("protocol_version") != PROTOCOL_VERSION:
            raise RuntimeError("Directory candidate protocol version mismatch")
        self.chunk_size = int(manifest["chunk_size_records"])
        self.record_count = int(manifest["record_count"])
        if not isinstance(index, list) or len(index) != manifest.get("chunk_count"):
            raise RuntimeError("Directory candidate index count mismatch")
        for row in index:
            self.chunks.append(
                ChunkIndex(
                    int(row["chunk_id"]),
                    int(row["record_count"]),
                    tuple(float(v) for v in row["bounds"]),
                    str(row["payload_sha256"]),
                    int(row["payload_bytes"]),
                    path / row["directory_file"],
                )
            )

    def read_payload(self, chunk: ChunkIndex) -> bytes:
        try:
            payload = Path(chunk.locator).read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Directory chunk {chunk.chunk_id} is missing") from exc
        if len(payload) != chunk.payload_bytes or sha256_bytes(payload) != chunk.payload_sha256:
            raise RuntimeError(f"Directory chunk {chunk.chunk_id} payload integrity failure")
        return payload


class SQLiteReader(CandidateReader):
    format_name = "sqlite"

    def __init__(self, path: Path):
        super().__init__(path)
        self.connection = connect_read_only(path)
        meta = {
            row["key"]: json.loads(row["value_json"])
            for row in self.connection.execute("SELECT key, value_json FROM metadata")
        }
        if meta.get("protocol_version") != PROTOCOL_VERSION:
            self.connection.close()
            raise RuntimeError("SQLite candidate protocol version mismatch")
        self.chunk_size = int(meta["chunk_size_records"])
        self.record_count = int(meta["record_count"])
        for row in self.connection.execute(
            "SELECT chunk_id, record_count, min_x, min_y, max_x, max_y, "
            "length(payload) AS payload_bytes, payload_sha256 FROM chunk ORDER BY chunk_id"
        ):
            self.chunks.append(
                ChunkIndex(
                    int(row["chunk_id"]),
                    int(row["record_count"]),
                    tuple(float(row[key]) for key in ("min_x", "min_y", "max_x", "max_y")),
                    str(row["payload_sha256"]),
                    int(row["payload_bytes"]),
                    int(row["chunk_id"]),
                )
            )

    def read_payload(self, chunk: ChunkIndex) -> bytes:
        row = self.connection.execute(
            "SELECT payload, payload_sha256 FROM chunk WHERE chunk_id = ?", (chunk.locator,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"SQLite chunk {chunk.chunk_id} is missing")
        payload = bytes(row["payload"])
        if len(payload) != chunk.payload_bytes or row["payload_sha256"] != chunk.payload_sha256:
            raise RuntimeError(f"SQLite chunk {chunk.chunk_id} index integrity failure")
        if sha256_bytes(payload) != chunk.payload_sha256:
            raise RuntimeError(f"SQLite chunk {chunk.chunk_id} payload integrity failure")
        return payload

    def close(self) -> None:
        self.connection.close()


class FlatReader(CandidateReader):
    format_name = "flat"

    def __init__(self, path: Path):
        super().__init__(path)
        self.handle = path.open("rb")
        try:
            if self.handle.read(len(FLAT_MAGIC)) != FLAT_MAGIC:
                raise RuntimeError("Flat candidate magic mismatch")
            raw_length = self.handle.read(8)
            if len(raw_length) != 8:
                raise RuntimeError("Flat candidate index length is truncated")
            index_length = struct.unpack(">Q", raw_length)[0]
            if index_length <= 0 or index_length > path.stat().st_size:
                raise RuntimeError("Flat candidate index length is invalid")
            index_bytes = self.handle.read(index_length)
            if len(index_bytes) != index_length:
                raise RuntimeError("Flat candidate index is truncated")
            index = json.loads(index_bytes)
        except Exception:
            self.handle.close()
            raise
        if index.get("protocol_version") != PROTOCOL_VERSION:
            self.handle.close()
            raise RuntimeError("Flat candidate protocol version mismatch")
        self.chunk_size = int(index["chunk_size_records"])
        self.record_count = int(index["record_count"])
        self.payload_start = len(FLAT_MAGIC) + 8 + index_length
        chunks = index.get("chunks")
        if not isinstance(chunks, list) or len(chunks) != index.get("chunk_count"):
            self.handle.close()
            raise RuntimeError("Flat candidate chunk index count mismatch")
        expected_offset = 0
        file_size = path.stat().st_size
        for row in chunks:
            offset = int(row["flat_offset"])
            length = int(row["payload_bytes"])
            if offset != expected_offset or length <= 0:
                self.handle.close()
                raise RuntimeError("Flat candidate chunk offsets are malformed")
            if self.payload_start + offset + length > file_size:
                self.handle.close()
                raise RuntimeError("Flat candidate payload is truncated")
            self.chunks.append(
                ChunkIndex(
                    int(row["chunk_id"]),
                    int(row["record_count"]),
                    tuple(float(v) for v in row["bounds"]),
                    str(row["payload_sha256"]),
                    length,
                    offset,
                )
            )
            expected_offset += length
        if self.payload_start + expected_offset != file_size:
            self.handle.close()
            raise RuntimeError("Flat candidate has trailing or unindexed payload bytes")

    def read_payload(self, chunk: ChunkIndex) -> bytes:
        self.handle.seek(self.payload_start + int(chunk.locator))
        payload = self.handle.read(chunk.payload_bytes)
        if len(payload) != chunk.payload_bytes or sha256_bytes(payload) != chunk.payload_sha256:
            raise RuntimeError(f"Flat chunk {chunk.chunk_id} payload integrity failure")
        return payload

    def close(self) -> None:
        self.handle.close()


def open_reader(format_name: str, path: Path) -> CandidateReader:
    if format_name == "directory":
        return DirectoryReader(path)
    if format_name == "sqlite":
        return SQLiteReader(path)
    if format_name == "flat":
        return FlatReader(path)
    raise RuntimeError(f"Unknown candidate format: {format_name}")


def point_on_segment(point: tuple[float, float], a: Sequence[float], b: Sequence[float]) -> bool:
    px, py = point
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    tolerance = 1e-12 * max(1.0, abs(px), abs(py), abs(ax), abs(ay), abs(bx), abs(by))
    if abs(cross) > tolerance:
        return False
    return min(ax, bx) - tolerance <= px <= max(ax, bx) + tolerance and min(ay, by) - tolerance <= py <= max(ay, by) + tolerance


def point_in_ring(point: tuple[float, float], ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    px, py = point
    for index in range(len(ring) - 1):
        a = ring[index]
        b = ring[index + 1]
        if point_on_segment(point, a, b):
            return True
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        intersects = ((ay > py) != (by > py)) and (
            px < (bx - ax) * (py - ay) / (by - ay) + ax
        )
        if intersects:
            inside = not inside
    return inside


def point_in_polygon(point: tuple[float, float], polygon: Sequence[Sequence[Sequence[float]]]) -> bool:
    if not polygon or not point_in_ring(point, polygon[0]):
        return False
    for hole in polygon[1:]:
        if point_in_ring(point, hole):
            return False
    return True


def point_in_geometry(point: tuple[float, float], geometry_type: str, coordinates: Any) -> bool:
    if geometry_type == "Polygon":
        return point_in_polygon(point, coordinates)
    if geometry_type == "MultiPolygon":
        return any(point_in_polygon(point, polygon) for polygon in coordinates)
    return False


def canonical_viewport_ids(staging: Path, bounds: Sequence[float]) -> list[str]:
    connection = sqlite3.connect(staging)
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT record_id FROM record WHERE min_x <= ? AND max_x >= ? "
                "AND min_y <= ? AND max_y >= ? ORDER BY record_id",
                (bounds[2], bounds[0], bounds[3], bounds[1]),
            )
        ]
    finally:
        connection.close()


def canonical_hit_test(staging: Path, point: tuple[float, float]) -> list[str]:
    connection = sqlite3.connect(staging)
    try:
        keys = []
        for building_key, record_json in connection.execute(
            "SELECT building_key, record_json FROM record WHERE dataset_key = 'buildings' "
            "AND min_x <= ? AND max_x >= ? AND min_y <= ? AND max_y >= ?",
            (point[0], point[0], point[1], point[1]),
        ):
            record = json.loads(bytes(record_json))
            if point_in_geometry(point, record["geometry_type"], record["coordinates"]):
                keys.append(building_key)
        return sorted(keys)
    finally:
        connection.close()


def derive_viewports(staging: Path, bounds: Sequence[float]) -> list[dict[str, Any]]:
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    grid = 8
    building_counts = [[0 for _ in range(grid)] for _ in range(grid)]
    road_counts = [[0 for _ in range(grid)] for _ in range(grid)]
    water_counts = [[0 for _ in range(grid)] for _ in range(grid)]
    connection = sqlite3.connect(staging)
    try:
        for dataset_key, rminx, rminy, rmaxx, rmaxy in connection.execute(
            "SELECT dataset_key, min_x, min_y, max_x, max_y FROM record"
        ):
            cx = (rminx + rmaxx) / 2.0
            cy = (rminy + rmaxy) / 2.0
            ix = max(0, min(grid - 1, int(((cx - min_x) / width) * grid)))
            iy = max(0, min(grid - 1, int(((cy - min_y) / height) * grid)))
            if dataset_key == "buildings":
                building_counts[iy][ix] += 1
            elif dataset_key == "roads":
                road_counts[iy][ix] += 1
            elif str(dataset_key).startswith("water-"):
                water_counts[iy][ix] += 1

        def cell_bounds(ix: int, iy: int) -> list[float]:
            return [
                min_x + width * ix / grid,
                min_y + height * iy / grid,
                min_x + width * (ix + 1) / grid,
                min_y + height * (iy + 1) / grid,
            ]

        building_cells = sorted(
            (building_counts[iy][ix], ix, iy)
            for iy in range(grid)
            for ix in range(grid)
            if building_counts[iy][ix] > 0
        )
        if not building_cells:
            raise RuntimeError("No building density cells are available")
        sparse = building_cells[0]
        medium = building_cells[len(building_cells) // 2]
        dense = building_cells[-1]
        road = max(
            (road_counts[iy][ix], ix, iy)
            for iy in range(grid)
            for ix in range(grid)
        )
        water = max(
            (water_counts[iy][ix], ix, iy)
            for iy in range(grid)
            for ix in range(grid)
        )

        dense_bounds = cell_bounds(dense[1], dense[2])
        building_row = connection.execute(
            "SELECT record_json FROM record WHERE dataset_key = 'buildings' "
            "AND ((min_x + max_x) / 2.0) >= ? AND ((min_x + max_x) / 2.0) <= ? "
            "AND ((min_y + max_y) / 2.0) >= ? AND ((min_y + max_y) / 2.0) <= ? "
            "ORDER BY morton, record_id LIMIT 1",
            (dense_bounds[0], dense_bounds[2], dense_bounds[1], dense_bounds[3]),
        ).fetchone()
        if building_row is None:
            raise RuntimeError("Unable to derive editing-scale building probe")
        building = json.loads(bytes(building_row[0]))
        bb = building["bounds"]
        pad_x = max((bb[2] - bb[0]) * 4.0, width / 2000.0)
        pad_y = max((bb[3] - bb[1]) * 4.0, height / 2000.0)
        edit_bounds = [
            max(min_x, bb[0] - pad_x),
            max(min_y, bb[1] - pad_y),
            min(max_x, bb[2] + pad_x),
            min(max_y, bb[3] + pad_y),
        ]
    finally:
        connection.close()

    return [
        {"name": "county-overview", "bounds": list(bounds), "basis": "accepted county boundary"},
        {"name": "dense-buildings", "bounds": cell_bounds(dense[1], dense[2]), "basis_count": dense[0]},
        {"name": "medium-buildings", "bounds": cell_bounds(medium[1], medium[2]), "basis_count": medium[0]},
        {"name": "sparse-buildings", "bounds": cell_bounds(sparse[1], sparse[2]), "basis_count": sparse[0]},
        {"name": "road-heavy", "bounds": cell_bounds(road[1], road[2]), "basis_count": road[0]},
        {"name": "water-heavy", "bounds": cell_bounds(water[1], water[2]), "basis_count": water[0]},
        {"name": "editing-scale-building", "bounds": edit_bounds, "basis": building["record_id"]},
    ]


def sample_hit_points(staging: Path, sample_count: int = HIT_TEST_SAMPLES) -> list[dict[str, Any]]:
    connection = sqlite3.connect(staging)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM record WHERE dataset_key = 'buildings'"
        ).fetchone()[0]
        if total == 0:
            raise RuntimeError("No buildings are available for hit-test samples")
        count = min(sample_count, total)
        if count == 1:
            offsets = [0]
        else:
            offsets = sorted(
                set(round(index * (total - 1) / (count - 1)) for index in range(count))
            )
        samples = []
        for offset in offsets:
            row = connection.execute(
                "SELECT record_json FROM record WHERE dataset_key = 'buildings' "
                "ORDER BY morton, record_id LIMIT 1 OFFSET ?",
                (offset,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Hit-test sampling offset failed")
            record = json.loads(bytes(row[0]))
            coordinates = record["coordinates"]
            polygon = coordinates if record["geometry_type"] == "Polygon" else coordinates[0]
            point = (float(polygon[0][0][0]), float(polygon[0][0][1]))
            samples.append(
                {
                    "building_key": record["building_key"],
                    "point": [point[0], point[1]],
                    "morton_rank_offset": offset,
                }
            )
        return samples
    finally:
        connection.close()


def benchmark_startup(paths: dict[str, Path]) -> dict[str, Any]:
    samples = {name: [] for name in CANDIDATE_FORMATS}
    names = list(CANDIDATE_FORMATS)
    for repetition in range(STARTUP_REPETITIONS):
        order = names[repetition % len(names):] + names[: repetition % len(names)]
        for name in order:
            start = time.perf_counter_ns()
            reader = open_reader(name, paths[name])
            reader.close()
            elapsed = (time.perf_counter_ns() - start) / 1_000_000.0
            samples[name].append(elapsed)
    return {name: timing_summary(samples[name]) for name in CANDIDATE_FORMATS}


def benchmark_viewports(
    staging: Path,
    paths: dict[str, Path],
    probes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {name: [] for name in CANDIDATE_FORMATS}
    readers = {name: open_reader(name, paths[name]) for name in CANDIDATE_FORMATS}
    try:
        for probe in probes:
            expected = canonical_viewport_ids(staging, probe["bounds"])
            candidate_sets: dict[str, list[str]] = {}
            samples: dict[str, list[float]] = {name: [] for name in CANDIDATE_FORMATS}
            stats: dict[str, dict[str, int]] = {}
            for repetition in range(VIEWPORT_REPETITIONS):
                names = list(CANDIDATE_FORMATS)
                order = names[repetition % len(names):] + names[: repetition % len(names)]
                for name in order:
                    start = time.perf_counter_ns()
                    records, read_stats = readers[name].viewport(probe["bounds"])
                    elapsed = (time.perf_counter_ns() - start) / 1_000_000.0
                    ids = [record["record_id"] for record in records]
                    if ids != expected:
                        raise RuntimeError(
                            f"Viewport {probe['name']} result mismatch for {name}: "
                            f"expected {len(expected)} records, got {len(ids)}"
                        )
                    if name in candidate_sets and candidate_sets[name] != ids:
                        raise RuntimeError(f"Viewport {probe['name']} is nondeterministic for {name}")
                    candidate_sets[name] = ids
                    samples[name].append(elapsed)
                    stats[name] = read_stats
            if len({tuple(values) for values in candidate_sets.values()}) != 1:
                raise RuntimeError(f"Viewport {probe['name']} differs across candidates")
            for name in CANDIDATE_FORMATS:
                result[name].append(
                    {
                        "probe": probe,
                        "feature_count": len(expected),
                        "result_sha256": sha256_bytes(canonical_bytes(expected)),
                        "timing": timing_summary(samples[name]),
                        **stats[name],
                    }
                )
    finally:
        for reader in readers.values():
            reader.close()
    return result


def benchmark_hit_tests(
    staging: Path,
    paths: dict[str, Path],
    samples: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    readers = {name: open_reader(name, paths[name]) for name in CANDIDATE_FORMATS}
    times: dict[str, list[float]] = {name: [] for name in CANDIDATE_FORMATS}
    detailed = []
    try:
        for sample_index, sample in enumerate(samples):
            point = (float(sample["point"][0]), float(sample["point"][1]))
            expected = canonical_hit_test(staging, point)
            if sample["building_key"] not in expected:
                raise RuntimeError("Derived hit-test point does not resolve its sampled building")
            per_candidate = {}
            names = list(CANDIDATE_FORMATS)
            order = names[sample_index % len(names):] + names[: sample_index % len(names)]
            for name in order:
                start = time.perf_counter_ns()
                keys, read_stats = readers[name].hit_test(point)
                elapsed = (time.perf_counter_ns() - start) / 1_000_000.0
                if keys != expected:
                    raise RuntimeError(
                        f"Hit-test identity mismatch for {name} at sample {sample_index}"
                    )
                times[name].append(elapsed)
                per_candidate[name] = {
                    "elapsed_ms": round(elapsed, 6),
                    **read_stats,
                }
            detailed.append(
                {
                    **sample,
                    "resolved_building_keys_sha256": sha256_bytes(canonical_bytes(expected)),
                    "resolved_count": len(expected),
                    "candidate_measurements": per_candidate,
                }
            )
    finally:
        for reader in readers.values():
            reader.close()
    return {
        "sample_count": len(detailed),
        "samples": detailed,
        "summary": {name: timing_summary(times[name]) for name in CANDIDATE_FORMATS},
        "interpretation": (
            "bounded deterministic functional/performance probe; p95 is descriptive only"
        ),
    }


def classification_independence(
    paths: dict[str, Path], samples: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    selected = [sample["building_key"] for sample in samples[: min(16, len(samples))]]
    overlay_a = {
        key: ("Other" if index % 2 == 0 else "Condominium")
        for index, key in enumerate(selected)
    }
    overlay_b = {
        key: ("Apartments" if index % 2 == 0 else "Unclassified")
        for index, key in enumerate(selected)
    }
    format_results = {}
    for name in CANDIDATE_FORMATS:
        before = artifact_sha256(paths[name])
        reader = open_reader(name, paths[name])
        try:
            resolved_a = []
            resolved_b = []
            for sample in samples[: min(16, len(samples))]:
                point = (float(sample["point"][0]), float(sample["point"][1]))
                keys, _ = reader.hit_test(point)
                if sample["building_key"] not in keys:
                    raise RuntimeError(f"Classification overlay lookup failed for {name}")
                key = sample["building_key"]
                class_a = overlay_a.get(key, "Unclassified")
                class_b = overlay_b.get(key, "Unclassified")
                resolved_a.append({"building_key": key, "classification": class_a, "color": CLASS_COLORS[class_a]})
                resolved_b.append({"building_key": key, "classification": class_b, "color": CLASS_COLORS[class_b]})
            if resolved_a == resolved_b:
                raise RuntimeError("Classification overlay mappings did not change resolved colors")
        finally:
            reader.close()
        after = artifact_sha256(paths[name])
        if before != after:
            raise RuntimeError(f"Base {name} artifact changed during classification overlay lookup")
        format_results[name] = {
            "base_artifact_sha256_before": before,
            "base_artifact_sha256_after": after,
            "unchanged": True,
            "overlay_a_sha256": sha256_bytes(canonical_bytes(resolved_a)),
            "overlay_b_sha256": sha256_bytes(canonical_bytes(resolved_b)),
            "resolved_outputs_differ": resolved_a != resolved_b,
        }
    return {
        "sample_building_count": len(selected),
        "classification_values_embedded_in_base": False,
        "format_results": format_results,
    }


def candidate_evidence(paths: dict[str, Path]) -> dict[str, Any]:
    output = {}
    for name, path in paths.items():
        size, file_count = artifact_size_and_files(path)
        if name == "sqlite":
            connection = connect_read_only(path)
            try:
                quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            finally:
                connection.close()
            if quick != "ok":
                raise RuntimeError(f"SQLite candidate quick_check failed: {quick}")
        reader = open_reader(name, path)
        try:
            total_records = sum(chunk.record_count for chunk in reader.chunks)
            if total_records != reader.record_count:
                raise RuntimeError(f"{name} candidate record-count integrity failure")
            for chunk in reader.chunks:
                reader.read_payload(chunk)
        finally:
            reader.close()
        output[name] = {
            "artifact_path": str(path),
            "artifact_sha256": artifact_sha256(path),
            "package_bytes": size,
            "artifact_file_count": file_count,
            "replacement_unit_count": file_count,
            "single_file": file_count == 1,
        }
    return output


def run_measurement(database: Path, workspace: Path) -> dict[str, Any]:
    database = database.resolve()
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if database == workspace or workspace in database.parents:
        raise RuntimeError("Benchmark workspace must not contain the authoritative database")
    validation = validate_authoritative_database(database)
    releases = accepted_release_identity(database)
    database_sha = sha256_file(database)
    storage = storage_environment(workspace)

    candidate_root = workspace / "candidates"
    candidate_root.mkdir(exist_ok=True)
    staging = workspace / "canonical-staging.sqlite"
    staging_info = prepare_canonical_staging(database, staging)
    probes = derive_viewports(staging, staging_info["county_bounds"])
    hit_samples = sample_hit_points(staging)

    chunk_results = {}
    for chunk_size in CHUNK_SIZES:
        paths = build_candidates(staging, candidate_root, chunk_size)
        evidence = candidate_evidence(paths)
        startup = benchmark_startup(paths)
        viewports = benchmark_viewports(staging, paths, probes)
        hits = benchmark_hit_tests(staging, paths, hit_samples)
        for name in CANDIDATE_FORMATS:
            evidence[name]["warm_startup_index_open_ms"] = startup[name]
            evidence[name]["viewport_probes"] = viewports[name]
            evidence[name]["hit_test_summary"] = hits["summary"][name]
        chunk_results[str(chunk_size)] = {
            "candidate_evidence": evidence,
            "hit_test": hits,
            "viewport_equivalence": "exact across canonical staging and all candidates",
            "hit_test_equivalence": "exact across canonical staging and all candidates",
        }

    classification = classification_independence(
        candidate_paths(candidate_root, 512), hit_samples
    )
    report = {
        "report_schema": REPORT_SCHEMA,
        "protocol_version": PROTOCOL_VERSION,
        "measurement_stage": "batch-025-pre-acceptance",
        "selection_status": "not-selected",
        "accepted_ssot": SSOT_COMMIT,
        "source": {
            "authoritative_database_path": str(database),
            "authoritative_database_sha256": database_sha,
            "accepted_releases": releases,
            "established_validation": validation,
            "canonical_staging": {
                key: value for key, value in staging_info.items() if key != "path"
            },
        },
        "storage_environment": storage,
        "protocol": protocol_summary(),
        "compatibility_matrix": compatibility_matrix(),
        "viewport_probes": probes,
        "chunk_size_results": chunk_results,
        "classification_independence": classification,
        "decision_rule": (
            "This measurement does not select a format. The final Batch 025 decision must audit "
            "real-dataset orchestrator evidence, cross-platform/replacement tradeoffs, and "
            "chunk-size sensitivity without a weighted composite score. Physical USB and "
            "workstation deployment validation are explicitly deferred until the application "
            "is complete."
        ),
        "scope_exclusions": [
            "renderer",
            "browser application",
            "county overview LOD",
            "road LOD",
            "water LOD",
            "building LOD",
            "classification snapshot format",
            "final render-package manifest",
            "visible grid/cell behavior",
            "physical USB deployment validation",
            "workstation deployment validation",
        ],
    }
    report_path = workspace / "benchmark-report.json"
    report_path.write_bytes(canonical_bytes(report) + b"\n")
    report_sha = sha256_file(report_path)
    checksum_path = workspace / "benchmark-report.json.sha256"
    checksum_path.write_text(f"{report_sha}  benchmark-report.json\n", encoding="utf-8")
    result = {
        "report_file": str(report_path),
        "report_sha256": report_sha,
        "checksum_file": str(checksum_path),
        "measurement_context": storage["measurement_context"],
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("protocol", help="print the fixed Batch 025 benchmark protocol")
    measure = subparsers.add_parser("measure", help="run controlled development benchmark")
    measure.add_argument("database", type=Path)
    measure.add_argument("workspace", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "protocol":
            print(json.dumps(protocol_summary(), indent=2, sort_keys=True))
            return 0
        result = run_measurement(args.database, args.workspace)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
