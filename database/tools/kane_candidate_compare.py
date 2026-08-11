#!/usr/bin/env python3
"""Deterministically compare validated source candidates with accepted releases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
COMPARISON_SCHEMA = 1
CHANGED_CATEGORIES = (
    "added",
    "removed",
    "geometry_changed",
    "attributes_changed",
    "both_changed",
)
ALL_CATEGORIES = (
    "added",
    "removed",
    "unchanged",
    "geometry_changed",
    "attributes_changed",
    "both_changed",
)


class ComparisonError(RuntimeError):
    """Raised when candidate comparison cannot be performed safely."""


def load_sibling(name: str):
    module_path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_kane_condo_{name}_compare", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kane_geometry = load_sibling("kane_geometry")
kane_source_status = load_sibling("kane_source_status")
kane_buildings = load_sibling("kane_buildings")
kane_map_layers = load_sibling("kane_map_layers")
kane_boundary = load_sibling("kane_boundary")
kane_building_candidate = load_sibling("kane_building_candidate")
kane_road_candidate = load_sibling("kane_road_candidate")
kane_water_candidate = load_sibling("kane_water_candidate")
kane_boundary_candidate = load_sibling("kane_boundary_candidate")


def canonical_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _reject_constant(token: str) -> None:
    raise ValueError(f"invalid JSON constant {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ComparisonError(f"Unable to read {path}: {exc}") from exc
    if not raw:
        raise ComparisonError(f"JSON file is empty: {path}")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ComparisonError(f"JSON file has a UTF-8 BOM: {path}")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ComparisonError(f"Invalid UTF-8 JSON in {path}: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonError(f"{label} must be a JSON object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ComparisonError(f"{label} must be a JSON array")
    return value


def _object_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ComparisonError(f"{label} is not an integer object ID")
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ComparisonError(f"{label} is not an integer object ID") from exc
    if normalized < 0 or str(normalized) != str(value).strip():
        raise ComparisonError(f"{label} is not a canonical nonnegative integer object ID")
    return normalized


def _identity(value: Any, label: str) -> str:
    if value is None or isinstance(value, bool):
        raise ComparisonError(f"{label} is missing")
    text = str(value).strip()
    if not text:
        raise ComparisonError(f"{label} is missing")
    return text


def _open_read_only(database: Path) -> sqlite3.Connection:
    database = database.resolve()
    if not database.is_file():
        raise ComparisonError(f"Database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _validate_database(database: Path, candidate_kind: str) -> None:
    if candidate_kind == "official-buildings":
        errors = kane_buildings.validate_database(database)
    elif candidate_kind in {"official-roads", "official-water-context"}:
        errors = kane_map_layers.validate_database(database)
    elif candidate_kind == "county-boundary":
        errors = kane_boundary.validate_database(database)
    else:
        raise ComparisonError(f"Unsupported candidate kind: {candidate_kind!r}")
    if errors:
        raise ComparisonError("Database validation failed before comparison:\n- " + "\n- ".join(errors))


def _candidate_kind(candidate_dir: Path) -> str:
    candidate_dir = candidate_dir.absolute()
    if candidate_dir.is_symlink() or not candidate_dir.is_dir():
        raise ComparisonError(f"Candidate directory is missing or is a symlink: {candidate_dir}")
    manifest = _mapping(load_json(candidate_dir / "manifest.json"), "Candidate manifest")
    kind = manifest.get("candidate_kind")
    if kind not in {
        "official-buildings",
        "official-roads",
        "official-water-context",
        "county-boundary",
    }:
        raise ComparisonError(f"Unsupported candidate kind: {kind!r}")
    return str(kind)


def _validated_candidate(candidate_dir: Path, candidate_kind: str) -> dict[str, Any]:
    try:
        if candidate_kind == "official-buildings":
            return kane_building_candidate.validate_candidate(candidate_dir)
        if candidate_kind == "official-roads":
            return kane_road_candidate.validate_candidate(candidate_dir)
        if candidate_kind == "official-water-context":
            return kane_water_candidate.validate_candidate(candidate_dir)
        if candidate_kind == "county-boundary":
            return kane_boundary_candidate.validate_candidate(candidate_dir)
    except RuntimeError as exc:
        raise ComparisonError(str(exc)) from exc
    raise ComparisonError(f"Unsupported candidate kind: {candidate_kind!r}")


def _release_row(
    connection: sqlite3.Connection,
    dataset_key: str,
    lifecycle_status: str,
    *,
    release_key: str | None = None,
) -> sqlite3.Row:
    sql = (
        "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
        "sr.content_sha256, sr.feature_count, sr.metadata_json, "
        "h.object_count, h.source_metadata_json "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "WHERE d.dataset_key = ? AND sr.lifecycle_status = ?"
    )
    params: list[Any] = [dataset_key, lifecycle_status]
    if release_key is not None:
        sql += " AND sr.release_key = ?"
        params.append(release_key)
    rows = connection.execute(sql, params).fetchall()
    expected = f"{lifecycle_status} release"
    if release_key is not None:
        expected += f" {release_key}"
    if len(rows) != 1:
        raise ComparisonError(
            f"Expected exactly one {expected} for {dataset_key}; found {len(rows)}"
        )
    return rows[0]


def _json_object(text: Any, label: str) -> dict[str, Any]:
    try:
        value = json.loads(str(text))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"{label} must contain a JSON object")
    return value


def _stored_feature_rows(
    connection: sqlite3.Connection,
    dataset_key: str,
    release_id: int,
) -> list[sqlite3.Row]:
    if dataset_key == "buildings":
        table = "source_building"
    elif dataset_key == "county-boundary":
        table = "source_county_boundary"
    elif dataset_key in {"roads", "water-creeks", "water-fox-river"}:
        table = "source_map_feature"
    else:
        raise ComparisonError(f"Unsupported dataset key: {dataset_key}")
    return connection.execute(
        f"SELECT source_feature_id, source_ordinal, geometry_sha256, "
        f"attributes_json, attributes_sha256 FROM {table} "
        "WHERE source_release_id = ? ORDER BY source_ordinal",
        (release_id,),
    ).fetchall()


def _comparison_attributes_hash(
    attributes: Mapping[str, Any],
    identity_field: str,
    *,
    expected_identity: str,
    label: str,
) -> str:
    if identity_field not in attributes:
        raise ComparisonError(f"{label} is missing stable identity field {identity_field}")
    normalized_identity = _identity(
        attributes.get(identity_field),
        f"{label} {identity_field}",
    )
    if normalized_identity != expected_identity:
        raise ComparisonError(
            f"{label} stable identity field does not match feature identity"
        )
    normalized = dict(attributes)
    normalized[identity_field] = normalized_identity
    return sha256_bytes(kane_buildings.canonical_json(normalized).encode("utf-8"))


def _accepted_records(
    connection: sqlite3.Connection,
    dataset_key: str,
    release: sqlite3.Row,
    object_id_field: str,
    identity_field: str,
) -> tuple[dict[str, tuple[str, str]], dict[str, Any]]:
    rows = _stored_feature_rows(connection, dataset_key, int(release["source_release_id"]))
    if len(rows) != int(release["feature_count"]):
        raise ComparisonError(
            f"Accepted {dataset_key} feature storage count does not match release metadata"
        )
    records: dict[str, tuple[str, str]] = {}
    object_ids: list[int] = []
    for row in rows:
        identity = _identity(row["source_feature_id"], f"Accepted {dataset_key} identity")
        if identity in records:
            raise ComparisonError(f"Accepted {dataset_key} contains duplicate identity {identity}")
        attributes = _json_object(row["attributes_json"], f"Accepted {dataset_key} attributes")
        object_ids.append(_object_id(attributes.get(object_id_field), f"Accepted {dataset_key} {object_id_field}"))
        canonical_attributes = kane_buildings.canonical_json(attributes)
        computed_attributes = sha256_bytes(canonical_attributes.encode("utf-8"))
        if computed_attributes != row["attributes_sha256"]:
            raise ComparisonError(f"Accepted {dataset_key} attributes hash mismatch for {identity}")
        comparison_attributes = _comparison_attributes_hash(
            attributes,
            identity_field,
            expected_identity=identity,
            label=f"Accepted {dataset_key} attributes for {identity}",
        )
        records[identity] = (str(row["geometry_sha256"]), comparison_attributes)
    if len(set(object_ids)) != len(object_ids):
        raise ComparisonError(f"Accepted {dataset_key} contains duplicate object IDs")
    object_ids.sort()
    object_count = len(object_ids) if release["object_count"] is None else int(release["object_count"])
    if object_count < len(object_ids):
        raise ComparisonError(f"Accepted {dataset_key} object count is smaller than stored feature count")
    source_metadata = _json_object(
        release["source_metadata_json"],
        f"Accepted {dataset_key} harvest source metadata",
    )
    stored_inventory_hash = source_metadata.get("object_ids_sha256")
    if object_count == len(object_ids):
        computed_hash = kane_source_status.object_id_sha256(object_ids)
        if stored_inventory_hash is not None and stored_inventory_hash != computed_hash:
            raise ComparisonError(f"Accepted {dataset_key} object inventory hash is inconsistent with stored features")
        inventory = {
            "count": object_count,
            "object_ids_sha256": computed_hash,
            "object_ids": object_ids,
            "exact": True,
            "limitation": None,
        }
    else:
        if not isinstance(stored_inventory_hash, str) or len(stored_inventory_hash) != 64:
            raise ComparisonError(
                f"Accepted {dataset_key} object inventory is incomplete and has no preserved inventory hash"
            )
        inventory = {
            "count": object_count,
            "object_ids_sha256": stored_inventory_hash,
            "object_ids": None,
            "exact": False,
            "limitation": "accepted object-ID list is not reconstructable from database provenance",
        }
    return records, inventory


def _candidate_feature_records(
    feature_path: Path,
    dataset_key: str,
    identity_field: str,
) -> dict[str, tuple[str, str]]:
    collection = _mapping(load_json(feature_path), f"{dataset_key} candidate FeatureCollection")
    features = _list(collection.get("features"), f"{dataset_key} candidate features")
    records: dict[str, tuple[str, str]] = {}
    for ordinal, raw_feature in enumerate(features, start=1):
        feature = _mapping(raw_feature, f"{dataset_key} candidate feature {ordinal}")
        identity = _identity(feature.get("id"), f"{dataset_key} candidate feature identity")
        if identity in records:
            raise ComparisonError(f"Candidate {dataset_key} contains duplicate identity {identity}")
        properties = dict(_mapping(feature.get("properties"), f"Candidate {dataset_key} properties"))
        attributes_hash = _comparison_attributes_hash(
            properties,
            identity_field,
            expected_identity=identity,
            label=f"Candidate {dataset_key} properties for {identity}",
        )
        try:
            geometry_type, coordinates = kane_geometry.normalize_map_geometry(feature.get("geometry"))
            wkb = kane_geometry.map_geometry_wkb(geometry_type, coordinates)
        except RuntimeError as exc:
            raise ComparisonError(f"Candidate {dataset_key} geometry is invalid for {identity}: {exc}") from exc
        geometry_hash = sha256_bytes(wkb)
        records[identity] = (geometry_hash, attributes_hash)
    return records


def _inventory_file(path: Path) -> list[int]:
    values = _list(load_json(path), f"Object inventory {path.name}")
    normalized = [_object_id(value, f"Object inventory {path.name}") for value in values]
    if normalized != sorted(normalized) or len(set(normalized)) != len(normalized):
        raise ComparisonError(f"Object inventory is not strictly sorted and unique: {path.name}")
    return normalized


def _identity_bucket(identities: Sequence[str], *, include_identities: bool) -> dict[str, Any]:
    ordered = sorted(identities)
    result: dict[str, Any] = {
        "count": len(ordered),
        "identity_sha256": sha256_value(ordered),
    }
    if include_identities:
        result["identities"] = ordered
    return result


def _object_bucket(object_ids: Sequence[int]) -> dict[str, Any]:
    ordered = sorted(int(value) for value in object_ids)
    return {
        "count": len(ordered),
        "object_ids_sha256": kane_source_status.object_id_sha256(ordered),
        "object_ids": ordered,
    }


def _feature_changes(
    accepted: Mapping[str, tuple[str, str]],
    candidate: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    accepted_ids = set(accepted)
    candidate_ids = set(candidate)
    categories: dict[str, list[str]] = {key: [] for key in ALL_CATEGORIES}
    categories["added"] = sorted(candidate_ids - accepted_ids)
    categories["removed"] = sorted(accepted_ids - candidate_ids)
    for identity in sorted(accepted_ids & candidate_ids):
        accepted_geometry, accepted_attributes = accepted[identity]
        candidate_geometry, candidate_attributes = candidate[identity]
        geometry_changed = accepted_geometry != candidate_geometry
        attributes_changed = accepted_attributes != candidate_attributes
        if geometry_changed and attributes_changed:
            category = "both_changed"
        elif geometry_changed:
            category = "geometry_changed"
        elif attributes_changed:
            category = "attributes_changed"
        else:
            category = "unchanged"
        categories[category].append(identity)
    result = {
        key: _identity_bucket(
            categories[key],
            include_identities=(key != "unchanged"),
        )
        for key in ALL_CATEGORIES
    }
    if sum(result[key]["count"] for key in ALL_CATEGORIES) != len(accepted_ids | candidate_ids):
        raise ComparisonError("Feature comparison categories are not exhaustive")
    return result


def _inventory_comparison(accepted: Mapping[str, Any], candidate: Sequence[int]) -> dict[str, Any]:
    candidate = list(candidate)
    result: dict[str, Any] = {
        "accepted_count": int(accepted["count"]),
        "accepted_object_ids_sha256": str(accepted["object_ids_sha256"]),
        "candidate_count": len(candidate),
        "candidate_object_ids_sha256": kane_source_status.object_id_sha256(candidate),
        "exact_identity_diff_available": bool(accepted["exact"]),
        "limitation": accepted["limitation"],
    }
    accepted_ids = accepted.get("object_ids")
    if accepted_ids is None:
        result["added"] = None
        result["removed"] = None
    else:
        accepted_set = set(int(value) for value in accepted_ids)
        candidate_set = set(candidate)
        result["added"] = _object_bucket(sorted(candidate_set - accepted_set))
        result["removed"] = _object_bucket(sorted(accepted_set - candidate_set))
    return result


def _registered_candidate(
    connection: sqlite3.Connection,
    dataset_key: str,
    release_key: str,
    *,
    content_sha256: str,
    feature_count: int,
    object_count: int,
) -> sqlite3.Row:
    release = _release_row(
        connection,
        dataset_key,
        "candidate",
        release_key=release_key,
    )
    if release["content_sha256"] != content_sha256:
        raise ComparisonError(f"Registered {dataset_key} candidate content hash does not match staged evidence")
    if int(release["feature_count"]) != int(feature_count):
        raise ComparisonError(f"Registered {dataset_key} candidate feature count does not match staged evidence")
    if release["object_count"] is None or int(release["object_count"]) != int(object_count):
        raise ComparisonError(f"Registered {dataset_key} candidate object count does not match staged evidence")
    return release


def _dataset_comparison(
    connection: sqlite3.Connection,
    *,
    dataset_key: str,
    candidate_release_key: str,
    candidate_content_sha256: str,
    candidate_feature_count: int,
    candidate_object_ids: Sequence[int],
    candidate_feature_path: Path,
    object_id_field: str,
    identity_field: str,
    candidate_excluded_ids: Sequence[int] = (),
) -> dict[str, Any]:
    accepted_release = _release_row(connection, dataset_key, "accepted")
    _registered_candidate(
        connection,
        dataset_key,
        candidate_release_key,
        content_sha256=candidate_content_sha256,
        feature_count=candidate_feature_count,
        object_count=len(candidate_object_ids),
    )
    accepted_records, accepted_inventory = _accepted_records(
        connection,
        dataset_key,
        accepted_release,
        object_id_field,
        identity_field,
    )
    candidate_records = _candidate_feature_records(
        candidate_feature_path,
        dataset_key,
        identity_field,
    )
    if len(candidate_records) != candidate_feature_count:
        raise ComparisonError(f"Candidate {dataset_key} feature count does not match staged evidence")
    excluded = sorted(int(value) for value in candidate_excluded_ids)
    if len(set(excluded)) != len(excluded):
        raise ComparisonError(f"Candidate {dataset_key} contains duplicate excluded object IDs")
    if not set(excluded).issubset(set(candidate_object_ids)):
        raise ComparisonError(f"Candidate {dataset_key} exclusions are not contained in source inventory")
    if len(candidate_records) + len(excluded) != len(candidate_object_ids):
        raise ComparisonError(f"Candidate {dataset_key} retained and excluded counts do not cover source inventory")
    return {
        "dataset_key": dataset_key,
        "accepted_release_key": str(accepted_release["release_key"]),
        "candidate_release_key": candidate_release_key,
        "object_id_field": object_id_field,
        "identity_field": identity_field,
        "accepted_feature_count": len(accepted_records),
        "candidate_feature_count": len(candidate_records),
        "candidate_exclusions": _object_bucket(excluded),
        "source_inventory": _inventory_comparison(accepted_inventory, list(candidate_object_ids)),
        "feature_changes": _feature_changes(accepted_records, candidate_records),
    }


def _building_compare(connection: sqlite3.Connection, candidate_dir: Path, validated: Mapping[str, Any]) -> list[dict[str, Any]]:
    inventory = _inventory_file(candidate_dir / "object-ids.json")
    return [
        _dataset_comparison(
            connection,
            dataset_key="buildings",
            candidate_release_key=str(validated["release_key"]),
            candidate_content_sha256=str(validated["content_sha256"]),
            candidate_feature_count=int(validated["feature_count"]),
            candidate_object_ids=inventory,
            candidate_feature_path=candidate_dir / "buildings.geojson",
            object_id_field="OBJECTID",
            identity_field="FPId",
        )
    ]


def _road_compare(connection: sqlite3.Connection, candidate_dir: Path, validated: Mapping[str, Any]) -> list[dict[str, Any]]:
    inventory = _inventory_file(candidate_dir / "object-ids.json")
    excluded = _inventory_file(candidate_dir / "excluded-object-ids.json")
    return [
        _dataset_comparison(
            connection,
            dataset_key="roads",
            candidate_release_key=str(validated["release_key"]),
            candidate_content_sha256=str(validated["content_sha256"]),
            candidate_feature_count=int(validated["feature_count"]),
            candidate_object_ids=inventory,
            candidate_feature_path=candidate_dir / "roads.geojson",
            object_id_field="OBJECTID",
            identity_field="OBJECTID",
            candidate_excluded_ids=excluded,
        )
    ]


def _water_compare(connection: sqlite3.Connection, candidate_dir: Path, validated: Mapping[str, Any]) -> list[dict[str, Any]]:
    components = _mapping(validated["components"], "Water candidate components")
    result: list[dict[str, Any]] = []
    specs = (
        ("water-creeks", "creeks"),
        ("water-fox-river", "fox-river"),
    )
    for dataset_key, slug in specs:
        component = _mapping(components[dataset_key], f"Water candidate {dataset_key}")
        inventory = _inventory_file(candidate_dir / f"{slug}-object-ids.json")
        result.append(
            _dataset_comparison(
                connection,
                dataset_key=dataset_key,
                candidate_release_key=str(component["release_key"]),
                candidate_content_sha256=str(component["content_sha256"]),
                candidate_feature_count=int(component["feature_count"]),
                candidate_object_ids=inventory,
                candidate_feature_path=candidate_dir / f"{slug}.geojson",
                object_id_field="OBJECTID",
                identity_field="OBJECTID",
            )
        )
    return sorted(result, key=lambda value: value["dataset_key"])


def _boundary_compare(connection: sqlite3.Connection, candidate_dir: Path, validated: Mapping[str, Any]) -> list[dict[str, Any]]:
    inventory = _inventory_file(candidate_dir / "object-ids.json")
    return [
        _dataset_comparison(
            connection,
            dataset_key="county-boundary",
            candidate_release_key=str(validated["release_key"]),
            candidate_content_sha256=str(validated["content_sha256"]),
            candidate_feature_count=int(validated["feature_count"]),
            candidate_object_ids=inventory,
            candidate_feature_path=candidate_dir / "boundary.geojson",
            object_id_field="OBJECTID",
            identity_field="OBJECTID",
        )
    ]


def compare_candidate(database: Path, candidate_dir: Path) -> dict[str, Any]:
    database = database.resolve()
    candidate_dir = candidate_dir.absolute()
    candidate_kind = _candidate_kind(candidate_dir)
    _validate_database(database, candidate_kind)
    validated = _validated_candidate(candidate_dir, candidate_kind)
    candidate_dir = candidate_dir.resolve()
    connection = _open_read_only(database)
    try:
        if candidate_kind == "official-buildings":
            datasets = _building_compare(connection, candidate_dir, validated)
            candidate_identity = str(validated["release_key"])
        elif candidate_kind == "official-roads":
            datasets = _road_compare(connection, candidate_dir, validated)
            candidate_identity = str(validated["release_key"])
        elif candidate_kind == "official-water-context":
            datasets = _water_compare(connection, candidate_dir, validated)
            candidate_identity = str(validated["group_key"])
        elif candidate_kind == "county-boundary":
            datasets = _boundary_compare(connection, candidate_dir, validated)
            candidate_identity = str(validated["release_key"])
        else:
            raise ComparisonError(f"Unsupported candidate kind: {candidate_kind!r}")
    finally:
        connection.close()
    body = {
        "comparison_schema": COMPARISON_SCHEMA,
        "candidate_kind": candidate_kind,
        "candidate_identity": candidate_identity,
        "datasets": sorted(datasets, key=lambda value: value["dataset_key"]),
        "valid": True,
    }
    return {
        **body,
        "comparison_sha256": sha256_value(body),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministically compare a validated candidate with its accepted release."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare one registered staged candidate with the accepted database",
    )
    compare_parser.add_argument("database", type=Path)
    compare_parser.add_argument("candidate_directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            result = compare_candidate(args.database, args.candidate_directory)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except (ComparisonError, RuntimeError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
