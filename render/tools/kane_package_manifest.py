#!/usr/bin/env python3
"""Build and validate the Batch 032 Kane Condo render-package manifest."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

FORMAT = "kane-condo-render-package-manifest"
VERSION = 1
SRS_ID = 4326
DATASET_KEYS = (
    "county-boundary",
    "roads",
    "water-fox-river",
    "water-creeks",
    "buildings",
)
COMPONENT_SPECS = (
    ("county_overview", "county-overview.json", "kane-condo-county-overview", 1),
    ("roads", "roads-lod.krf", "kane-condo-road-lod", 1),
    ("water", "water-lod.krf", "kane-condo-water-lod", 1),
    ("buildings", "buildings-lod.krf", "kane-condo-building-lod", 1),
    (
        "classification_snapshot",
        "classification-snapshot.json",
        "kane-condo-classification-snapshot",
        1,
    ),
)
ROLE_ORDER = tuple(spec[0] for spec in COMPONENT_SPECS)
EXPECTED_FILENAMES = {spec[0]: spec[1] for spec in COMPONENT_SPECS}
EXPECTED_FORMATS = {spec[0]: (spec[2], spec[3]) for spec in COMPONENT_SPECS}
CREATED_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BUILDING_KEY_PATTERN = re.compile(r"^kcb-[0-9a-f]{64}$")


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_sibling(name: str):
    module_path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_kane_condo_manifest_{name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load render component support: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _require_keys(value: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Render-package manifest {label} is not an object")
    actual = set(value)
    if actual != expected:
        raise RuntimeError(
            f"Render-package manifest {label} fields are invalid: "
            f"expected {sorted(expected)!r}, found {sorted(actual)!r}"
        )
    return value


def normalize_created_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if CREATED_AT_PATTERN.fullmatch(value) is None:
        raise RuntimeError("Manifest creation time must be UTC RFC3339 seconds ending in Z")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RuntimeError("Manifest creation time is not a valid UTC timestamp") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_database_identity(database: Path) -> dict[str, object]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        county_rows = connection.execute(
            "SELECT county_key, name, state_code, fips_code FROM county ORDER BY county_id"
        ).fetchall()
        if len(county_rows) != 1:
            raise RuntimeError(f"Authoritative database county count is {len(county_rows)}; expected 1")
        county = county_rows[0]
        release_rows = connection.execute(
            "SELECT d.dataset_key, sr.release_key, sr.content_sha256, sr.feature_count "
            "FROM source_release sr JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "WHERE sr.lifecycle_status = 'accepted' AND d.dataset_key IN (?, ?, ?, ?, ?) "
            "ORDER BY d.dataset_key",
            DATASET_KEYS,
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read authoritative database identity: {exc}") from exc
    finally:
        connection.close()

    by_dataset: dict[str, list[sqlite3.Row]] = {key: [] for key in DATASET_KEYS}
    for row in release_rows:
        by_dataset[str(row["dataset_key"])].append(row)
    accepted: dict[str, dict[str, object]] = {}
    for dataset_key in DATASET_KEYS:
        rows = by_dataset[dataset_key]
        if len(rows) != 1:
            raise RuntimeError(
                f"Accepted release count for {dataset_key} is {len(rows)}; expected 1"
            )
        row = rows[0]
        accepted[dataset_key] = {
            "feature_count": int(row["feature_count"]),
            "release_content_sha256": str(row["content_sha256"]),
            "release_key": str(row["release_key"]),
        }

    stat = database.stat()
    return {
        "accepted_releases": accepted,
        "byte_length": stat.st_size,
        "county": {
            "county_key": str(county["county_key"]),
            "fips_code": str(county["fips_code"]),
            "name": str(county["name"]),
            "state_code": str(county["state_code"]),
        },
        "sha256": sha256_file(database),
    }


def _validate_component_path(path: Path, role: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"Required render component is missing: {role}: {path}")
    expected = EXPECTED_FILENAMES[role]
    if path.name != expected:
        raise RuntimeError(
            f"Render component filename for {role} is {path.name!r}; expected {expected!r}"
        )
    return path


def _component_descriptor(role: str, path: Path, format_key: str, version: int, data: bytes) -> dict[str, object]:
    return {
        "byte_length": len(data),
        "filename": EXPECTED_FILENAMES[role],
        "format": format_key,
        "role": role,
        "sha256": sha256_bytes(data),
        "version": version,
    }


def inspect_overview(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    role = "county_overview"
    path = _validate_component_path(path, role)
    data = path.read_bytes()
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"County overview is invalid JSON: {exc}") from exc
    overview = load_sibling("kane_county_overview")
    expected_bytes = (overview.canonical_json(document) + "\n").encode("utf-8")
    if expected_bytes != data:
        raise RuntimeError("County overview is not canonical JSON with its required newline")
    top = _require_keys(
        document,
        {"county", "fit", "format", "outline", "source", "srs_id", "version"},
        "county overview",
    )
    if top.get("format") != overview.FORMAT or top.get("version") != overview.VERSION:
        raise RuntimeError("County overview format/version is unsupported")
    if top.get("srs_id") != SRS_ID:
        raise RuntimeError("County overview SRS is unsupported")
    source = _require_keys(
        top.get("source"),
        {
            "dataset_key",
            "geometry_sha256",
            "geometry_type",
            "release_content_sha256",
            "release_key",
            "source_feature_id",
        },
        "county overview source",
    )
    county = _require_keys(
        top.get("county"),
        {"county_key", "fips_code", "name", "state_code"},
        "county overview county",
    )
    fit = _require_keys(
        top.get("fit"), {"bounds", "center", "height", "width"}, "county overview fit"
    )
    outline = _require_keys(
        top.get("outline"),
        {
            "kind",
            "ring_count",
            "rings",
            "simplification_tolerance_degrees",
            "source_interior_ring_count",
            "source_vertex_count",
            "vertex_count",
        },
        "county overview outline",
    )
    if source["dataset_key"] != "county-boundary" or source["geometry_type"] not in ("Polygon", "MultiPolygon"):
        raise RuntimeError("County overview source metadata is invalid")
    if not isinstance(fit["bounds"], list) or len(fit["bounds"]) != 4:
        raise RuntimeError("County overview fit bounds are invalid")
    if outline["kind"] != "exterior-rings" or not isinstance(outline["rings"], list):
        raise RuntimeError("County overview outline metadata is invalid")
    descriptor = _component_descriptor(role, path, overview.FORMAT, overview.VERSION, data)
    metadata = {
        "county": dict(county),
        "datasets": {
            str(source.get("dataset_key")): {
                "feature_count": 1,
                "release_content_sha256": str(source.get("release_content_sha256")),
                "release_key": str(source.get("release_key")),
            }
        },
    }
    return descriptor, metadata


def _validate_flat_container(
    path: Path,
    role: str,
    module_name: str,
    required_levels: tuple[str, ...],
    *,
    collect_building_identity: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    path = _validate_component_path(path, role)
    module = load_sibling(module_name)
    data = path.read_bytes()
    magic = module.MAGIC
    if len(data) < len(magic) + 8 or not data.startswith(magic):
        raise RuntimeError(f"Render component {role} has an invalid magic header")
    index_length = struct.unpack(">Q", data[len(magic) : len(magic) + 8])[0]
    index_start = len(magic) + 8
    index_end = index_start + index_length
    if index_end > len(data):
        raise RuntimeError(f"Render component {role} index is truncated")
    index_bytes = data[index_start:index_end]
    try:
        index = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Render component {role} index is invalid JSON: {exc}") from exc
    if module.canonical_json_bytes(index) != index_bytes:
        raise RuntimeError(f"Render component {role} index is not canonical JSON")
    if index.get("format") != module.FORMAT or index.get("version") != module.VERSION:
        raise RuntimeError(f"Render component {role} format/version is unsupported")
    if index.get("srs_id") != SRS_ID:
        raise RuntimeError(f"Render component {role} SRS is unsupported")

    levels = index.get("levels")
    if not isinstance(levels, list):
        raise RuntimeError(f"Render component {role} level inventory is invalid")
    level_keys = tuple(str(level.get("key")) for level in levels if isinstance(level, Mapping))
    if level_keys != required_levels:
        raise RuntimeError(
            f"Render component {role} levels are invalid: expected {required_levels!r}, found {level_keys!r}"
        )

    payload_area = data[index_end:]
    expected_offset = 0
    building_keys: list[str] = []
    for level in levels:
        if not isinstance(level, Mapping):
            raise RuntimeError(f"Render component {role} level entry is invalid")
        key = str(level["key"])
        chunks = level.get("chunks")
        if not isinstance(chunks, list):
            raise RuntimeError(f"Render component {role} level {key} chunk inventory is invalid")
        level_count = 0
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                raise RuntimeError(f"Render component {role} level {key} chunk entry is invalid")
            offset = int(chunk["offset"])
            length = int(chunk["length"])
            if offset != expected_offset or length < 0:
                raise RuntimeError(f"Render component {role} payload offsets are not contiguous")
            end = offset + length
            if end > len(payload_area):
                raise RuntimeError(f"Render component {role} payload is truncated")
            compressed = payload_area[offset:end]
            if sha256_bytes(compressed) != chunk["payload_sha256"]:
                raise RuntimeError(f"Render component {role} payload SHA-256 is invalid")
            try:
                raw = zlib.decompress(compressed)
            except zlib.error as exc:
                raise RuntimeError(f"Render component {role} payload compression is invalid: {exc}") from exc
            if len(raw) != int(chunk["uncompressed_length"]):
                raise RuntimeError(f"Render component {role} uncompressed payload length is invalid")
            if sha256_bytes(raw) != chunk["records_sha256"]:
                raise RuntimeError(f"Render component {role} record SHA-256 is invalid")
            try:
                records = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Render component {role} records are invalid JSON: {exc}") from exc
            if module.canonical_json_bytes(records) != raw:
                raise RuntimeError(f"Render component {role} records are not canonical JSON")
            if not isinstance(records, list) or len(records) != int(chunk["feature_count"]):
                raise RuntimeError(f"Render component {role} chunk feature count is invalid")
            level_count += len(records)
            if collect_building_identity and key == "editing":
                for record in records:
                    if not isinstance(record, Mapping):
                        raise RuntimeError("Building editing record is not an object")
                    building_key = record.get("building_key")
                    if not isinstance(building_key, str) or BUILDING_KEY_PATTERN.fullmatch(building_key) is None:
                        raise RuntimeError("Building editing record has invalid building_key")
                    building_keys.append(building_key)
            expected_offset = end
        if level_count != int(level["feature_count"]):
            raise RuntimeError(f"Render component {role} level {key} feature count is invalid")
    if expected_offset != len(payload_area):
        raise RuntimeError(f"Render component {role} has trailing payload bytes")

    format_key, version = EXPECTED_FORMATS[role]
    descriptor = _component_descriptor(role, path, format_key, version, data)
    metadata: dict[str, object] = {"index": index}
    if collect_building_identity:
        if len(building_keys) != len(set(building_keys)):
            raise RuntimeError("Building editing level contains duplicate building_key values")
        source = index.get("source")
        if not isinstance(source, Mapping):
            raise RuntimeError("Building LOD source metadata is invalid")
        expected_count = int(source.get("feature_count", -1))
        if len(building_keys) != expected_count:
            raise RuntimeError(
                f"Building editing identity count is {len(building_keys)}; expected {expected_count}"
            )
        sorted_keys = sorted(building_keys)
        metadata["render_building_count"] = len(sorted_keys)
        metadata["render_identity_sha256"] = sha256_bytes(canonical_json_bytes(sorted_keys))
    return descriptor, metadata


def inspect_classification(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    role = "classification_snapshot"
    path = _validate_component_path(path, role)
    data = path.read_bytes()
    snapshot = load_sibling("kane_classification_snapshot")
    document = snapshot.read_snapshot_bytes(data)
    descriptor = _component_descriptor(role, path, snapshot.FORMAT, snapshot.VERSION, data)
    return descriptor, {"document": document}


def inspect_components(
    overview: Path,
    roads: Path,
    water: Path,
    buildings: Path,
    classifications: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    overview_desc, overview_meta = inspect_overview(overview)
    road_desc, road_meta = _validate_flat_container(
        roads, "roads", "kane_road_lod", ("orientation", "context", "detail")
    )
    water_desc, water_meta = _validate_flat_container(
        water, "water", "kane_water_lod", ("overview", "context", "detail")
    )
    building_desc, building_meta = _validate_flat_container(
        buildings,
        "buildings",
        "kane_building_lod",
        ("context", "neighborhood", "editing"),
        collect_building_identity=True,
    )
    classification_desc, classification_meta = inspect_classification(classifications)
    descriptors = [
        overview_desc,
        road_desc,
        water_desc,
        building_desc,
        classification_desc,
    ]
    metadata = {
        "county_overview": overview_meta,
        "roads": road_meta,
        "water": water_meta,
        "buildings": building_meta,
        "classification_snapshot": classification_meta,
    }
    return descriptors, metadata


def _release_projection(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "feature_count": int(value["feature_count"]),
        "release_content_sha256": str(value["release_content_sha256"]),
        "release_key": str(value["release_key"]),
    }


def validate_component_compatibility(
    database_identity: Mapping[str, object], metadata: Mapping[str, object]
) -> dict[str, object]:
    accepted = database_identity["accepted_releases"]
    if not isinstance(accepted, Mapping):
        raise RuntimeError("Authoritative database accepted-release inventory is invalid")
    county = database_identity["county"]

    overview = metadata["county_overview"]
    road_index = metadata["roads"]["index"]
    water_index = metadata["water"]["index"]
    building_index = metadata["buildings"]["index"]
    snapshot = metadata["classification_snapshot"]["document"]
    if not isinstance(overview, Mapping) or not isinstance(road_index, Mapping):
        raise RuntimeError("Render component metadata is invalid")
    if not isinstance(water_index, Mapping) or not isinstance(building_index, Mapping):
        raise RuntimeError("Render component metadata is invalid")
    if not isinstance(snapshot, Mapping):
        raise RuntimeError("Classification snapshot metadata is invalid")

    if overview["county"] != county:
        raise RuntimeError("County overview county identity does not match authoritative database")
    overview_datasets = overview["datasets"]
    if not isinstance(overview_datasets, Mapping):
        raise RuntimeError("County overview release metadata is invalid")
    if _release_projection(overview_datasets["county-boundary"]) != accepted["county-boundary"]:
        raise RuntimeError("County overview release does not match authoritative database")

    road_source = road_index.get("source")
    if not isinstance(road_source, Mapping) or road_source.get("county") != county:
        raise RuntimeError("Road LOD county identity does not match authoritative database")
    if _release_projection(road_source) != accepted["roads"]:
        raise RuntimeError("Road LOD release does not match authoritative database")

    water_source = water_index.get("source")
    if not isinstance(water_source, Mapping) or water_source.get("county") != county:
        raise RuntimeError("Water LOD county identity does not match authoritative database")
    water_datasets = water_source.get("datasets")
    if not isinstance(water_datasets, Mapping):
        raise RuntimeError("Water LOD release metadata is invalid")
    if _release_projection(water_datasets["fox_river"]) != accepted["water-fox-river"]:
        raise RuntimeError("Fox River LOD release does not match authoritative database")
    if _release_projection(water_datasets["creeks"]) != accepted["water-creeks"]:
        raise RuntimeError("Creek LOD release does not match authoritative database")

    building_source = building_index.get("source")
    if not isinstance(building_source, Mapping) or building_source.get("county") != county:
        raise RuntimeError("Building LOD county identity does not match authoritative database")
    if _release_projection(building_source) != accepted["buildings"]:
        raise RuntimeError("Building LOD release does not match authoritative database")

    snapshot_source = snapshot.get("source")
    snapshot_identity = snapshot.get("identity")
    snapshot_explicit = snapshot.get("explicit")
    if not isinstance(snapshot_source, Mapping) or not isinstance(snapshot_identity, Mapping):
        raise RuntimeError("Classification snapshot compatibility metadata is invalid")
    if not isinstance(snapshot_explicit, Mapping):
        raise RuntimeError("Classification snapshot explicit metadata is invalid")
    if _release_projection(snapshot_source) != accepted["buildings"]:
        raise RuntimeError("Classification snapshot building release does not match authoritative database")

    building_count = int(metadata["buildings"]["render_building_count"])
    building_identity = str(metadata["buildings"]["render_identity_sha256"])
    if int(snapshot_identity["render_building_count"]) != building_count:
        raise RuntimeError("Classification snapshot building count does not match building LOD")
    if str(snapshot_identity["render_identity_sha256"]) != building_identity:
        raise RuntimeError("Classification snapshot identity does not match building LOD")

    return {
        "building_component": "buildings",
        "classification_component": "classification_snapshot",
        "explicit_count": int(snapshot_explicit["count"]),
        "records_sha256": str(snapshot_explicit["records_sha256"]),
        "render_building_count": building_count,
        "render_identity_sha256": building_identity,
        "source_release_content_sha256": str(snapshot_source["release_content_sha256"]),
        "source_release_key": str(snapshot_source["release_key"]),
    }


def build_document(
    database: Path,
    overview: Path,
    roads: Path,
    water: Path,
    buildings: Path,
    classifications: Path,
    *,
    created_at: str | None = None,
) -> dict[str, object]:
    created = normalize_created_at(created_at)
    database_identity = load_database_identity(database)
    components, metadata = inspect_components(overview, roads, water, buildings, classifications)
    compatibility = validate_component_compatibility(database_identity, metadata)

    base_components = [component for component in components if component["role"] != "classification_snapshot"]
    base_geometry_sha256 = sha256_bytes(canonical_json_bytes(base_components))
    classification_component = next(
        component for component in components if component["role"] == "classification_snapshot"
    )
    content_identity_input = {
        "components": components,
        "database": database_identity,
        "classification_compatibility": compatibility,
    }
    package_content_sha256 = sha256_bytes(canonical_json_bytes(content_identity_input))

    return {
        "classification_compatibility": compatibility,
        "components": components,
        "created_at": created,
        "database": database_identity,
        "format": FORMAT,
        "identities": {
            "base_geometry_sha256": base_geometry_sha256,
            "classification_snapshot_sha256": classification_component["sha256"],
            "package_content_sha256": package_content_sha256,
        },
        "version": VERSION,
    }


def validate_manifest_document(document: object) -> dict[str, object]:
    top = _require_keys(
        document,
        {
            "classification_compatibility",
            "components",
            "created_at",
            "database",
            "format",
            "identities",
            "version",
        },
        "document",
    )
    if top["format"] != FORMAT or top["version"] != VERSION:
        raise RuntimeError("Render-package manifest format/version is unsupported")
    normalize_created_at(str(top["created_at"]))
    components = top["components"]
    if not isinstance(components, list) or len(components) != len(COMPONENT_SPECS):
        raise RuntimeError("Render-package manifest component inventory is invalid")
    roles = tuple(str(component.get("role")) for component in components if isinstance(component, Mapping))
    if roles != ROLE_ORDER:
        raise RuntimeError("Render-package manifest component roles are invalid")
    for component, spec in zip(components, COMPONENT_SPECS):
        if not isinstance(component, Mapping):
            raise RuntimeError("Render-package manifest component entry is invalid")
        role, filename, format_key, version = spec
        if component.get("filename") != filename or component.get("format") != format_key:
            raise RuntimeError(f"Render-package manifest component {role} identity is invalid")
        if int(component.get("version", -1)) != version:
            raise RuntimeError(f"Render-package manifest component {role} version is invalid")
        if int(component.get("byte_length", -1)) < 0:
            raise RuntimeError(f"Render-package manifest component {role} byte length is invalid")
        sha = component.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            raise RuntimeError(f"Render-package manifest component {role} SHA-256 is invalid")
    identities = top["identities"]
    if not isinstance(identities, Mapping) or set(identities) != {
        "base_geometry_sha256",
        "classification_snapshot_sha256",
        "package_content_sha256",
    }:
        raise RuntimeError("Render-package manifest identity block is invalid")
    for value in identities.values():
        if not isinstance(value, str) or len(value) != 64:
            raise RuntimeError("Render-package manifest content identity SHA-256 is invalid")
    return dict(top)


def read_manifest_bytes(data: bytes) -> dict[str, object]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Render-package manifest is invalid JSON: {exc}") from exc
    if canonical_json_bytes(document) != data:
        raise RuntimeError("Render-package manifest is not canonical JSON")
    return validate_manifest_document(document)


def write_manifest(
    database: Path,
    output: Path,
    overview: Path,
    roads: Path,
    water: Path,
    buildings: Path,
    classifications: Path,
    *,
    created_at: str | None = None,
) -> dict[str, object]:
    output = output.resolve()
    paths = [
        database.resolve(),
        overview.resolve(),
        roads.resolve(),
        water.resolve(),
        buildings.resolve(),
        classifications.resolve(),
    ]
    if output in paths:
        raise RuntimeError("Render-package manifest output must not replace an input component")
    document = build_document(
        database,
        overview,
        roads,
        water,
        buildings,
        classifications,
        created_at=created_at,
    )
    payload = canonical_json_bytes(document)
    read_manifest_bytes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "base_geometry_sha256": document["identities"]["base_geometry_sha256"],
        "byte_length": len(payload),
        "component_count": len(document["components"]),
        "created_at": document["created_at"],
        "output_file": str(output),
        "package_content_sha256": document["identities"]["package_content_sha256"],
        "sha256": sha256_bytes(payload),
    }


def validate_manifest_against_inputs(
    database: Path,
    manifest: Path,
    overview: Path,
    roads: Path,
    water: Path,
    buildings: Path,
    classifications: Path,
) -> dict[str, object]:
    manifest = manifest.resolve()
    if not manifest.is_file():
        raise RuntimeError(f"Render-package manifest does not exist: {manifest}")
    data = manifest.read_bytes()
    document = read_manifest_bytes(data)
    expected = build_document(
        database,
        overview,
        roads,
        water,
        buildings,
        classifications,
        created_at=str(document["created_at"]),
    )
    if document != expected:
        actual_components = {
            str(item["role"]): item for item in document["components"] if isinstance(item, Mapping)
        }
        expected_components = {
            str(item["role"]): item for item in expected["components"] if isinstance(item, Mapping)
        }
        for role in ROLE_ORDER:
            if actual_components.get(role) != expected_components.get(role):
                raise RuntimeError(f"Render-package component integrity mismatch: {role}")
        if document.get("database") != expected.get("database"):
            raise RuntimeError("Render-package authoritative database identity mismatch")
        if document.get("classification_compatibility") != expected.get("classification_compatibility"):
            raise RuntimeError("Render-package classification compatibility mismatch")
        if document.get("identities") != expected.get("identities"):
            raise RuntimeError("Render-package content identity mismatch")
        raise RuntimeError("Render-package manifest content does not match current inputs")
    return {
        "base_geometry_sha256": document["identities"]["base_geometry_sha256"],
        "byte_length": len(data),
        "component_count": len(document["components"]),
        "created_at": document["created_at"],
        "package_content_sha256": document["identities"]["package_content_sha256"],
        "sha256": sha256_bytes(data),
        "status": "valid",
    }


def add_component_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("database", type=Path)
    parser.add_argument("county_overview", type=Path)
    parser.add_argument("roads", type=Path)
    parser.add_argument("water", type=Path)
    parser.add_argument("buildings", type=Path)
    parser.add_argument("classifications", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="validate components and write the render-package manifest")
    add_component_arguments(build)
    build.add_argument("output", type=Path)
    build.add_argument("--created-at", help="override UTC creation time for deterministic test/rebuild workflows")

    validate = subparsers.add_parser("validate", help="validate a manifest against its database and components")
    add_component_arguments(validate)
    validate.add_argument("manifest", type=Path)

    inspect = subparsers.add_parser("inspect", help="validate and summarize a manifest file only")
    inspect.add_argument("manifest", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = write_manifest(
                args.database,
                args.output,
                args.county_overview,
                args.roads,
                args.water,
                args.buildings,
                args.classifications,
                created_at=args.created_at,
            )
        elif args.command == "validate":
            result = validate_manifest_against_inputs(
                args.database,
                args.manifest,
                args.county_overview,
                args.roads,
                args.water,
                args.buildings,
                args.classifications,
            )
        else:
            data = args.manifest.resolve().read_bytes()
            document = read_manifest_bytes(data)
            result = {
                "base_geometry_sha256": document["identities"]["base_geometry_sha256"],
                "byte_length": len(data),
                "component_count": len(document["components"]),
                "created_at": document["created_at"],
                "package_content_sha256": document["identities"]["package_content_sha256"],
                "sha256": sha256_bytes(data),
            }
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
