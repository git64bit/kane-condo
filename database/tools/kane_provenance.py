#!/usr/bin/env python3
"""Record, validate, and trace Kane Condo administrative provenance."""

from __future__ import annotations

import argparse
import importlib.util
import datetime as dt
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DATETIME_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
ADMIN_TABLES = {
    "county",
    "source_agency",
    "dataset",
    "harvest_run",
    "source_file",
    "source_release",
}
EXPECTED_COLUMNS = {
    "county": (
        "county_id", "county_key", "name", "state_code", "country_code", "fips_code", "created_at"
    ),
    "source_agency": (
        "source_agency_id", "agency_key", "name", "jurisdiction", "homepage_uri", "created_at"
    ),
    "dataset": (
        "dataset_id", "dataset_key", "county_id", "source_agency_id", "name", "description",
        "data_kind", "source_uri", "created_at"
    ),
    "harvest_run": (
        "harvest_run_id", "harvest_key", "dataset_id", "started_at", "completed_at", "status",
        "source_metadata_json", "object_count", "error_message", "created_at"
    ),
    "source_file": (
        "source_file_id", "harvest_run_id", "file_role", "relative_path", "byte_length", "sha256",
        "media_type", "created_at"
    ),
    "source_release": (
        "source_release_id", "release_key", "dataset_id", "harvest_run_id", "lifecycle_status",
        "source_published_at", "content_sha256", "feature_count", "metadata_json", "accepted_at",
        "superseded_by_release_id", "created_at"
    ),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def valid_datetime(value: object, *, optional: bool = False) -> bool:
    if value is None:
        return optional
    if not isinstance(value, str) or DATETIME_PATTERN.fullmatch(value) is None:
        return False
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def require_text(record: Mapping[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label}.{field} must be non-empty text")
    return value


def require_key(record: Mapping[str, Any], field: str, label: str) -> str:
    value = require_text(record, field, label)
    if KEY_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{label}.{field} must be a lowercase hyphenated key")
    return value


def require_hash(record: Mapping[str, Any], field: str, label: str) -> str:
    value = require_text(record, field, label)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{label}.{field} must be a lowercase SHA-256 value")
    return value


def require_datetime(
    record: Mapping[str, Any], field: str, label: str, *, optional: bool = False
) -> str | None:
    value = record.get(field)
    if not valid_datetime(value, optional=optional):
        requirement = "a millisecond UTC DATETIME or null" if optional else "a millisecond UTC DATETIME"
        raise RuntimeError(f"{label}.{field} must be {requirement}")
    return value


def require_nonnegative(record: Mapping[str, Any], field: str, label: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{label}.{field} must be a non-negative integer")
    return value


def optional_nonnegative(record: Mapping[str, Any], field: str, label: str) -> int | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{label}.{field} must be a non-negative integer or null")
    return value


def canonical_json(value: object, label: str) -> str:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be a JSON object")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def load_descriptor(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read descriptor {path}: {exc}") from exc
    return require_mapping(value, "descriptor")


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = table.replace('"', '""')
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{quoted}")'))


def validate_schema(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing = sorted(ADMIN_TABLES - tables)
    if missing:
        return ["Missing administrative provenance tables: " + ", ".join(missing)]
    for table, expected in EXPECTED_COLUMNS.items():
        actual = table_columns(connection, table)
        if actual != expected:
            errors.append(f"Unexpected {table} columns: expected {expected!r}, found {actual!r}")
    registrations = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in connection.execute(
            "SELECT table_name, data_type, identifier FROM gpkg_contents "
            "WHERE table_name IN ('county','source_agency','dataset','harvest_run','source_file','source_release')"
        )
    }
    for table in sorted(ADMIN_TABLES):
        row = registrations.get(table)
        if row is None:
            errors.append(f"{table} is not registered in gpkg_contents")
        elif row[0] != "attributes":
            errors.append(f"{table} must be registered as attributes")
    return errors


def _validate_json_column(connection: sqlite3.Connection, table: str, column: str) -> list[str]:
    errors: list[str] = []
    for identity, value in connection.execute(f"SELECT rowid, {column} FROM {table}"):
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            errors.append(f"{table} row {identity} has invalid {column}")
            continue
        if not isinstance(decoded, dict):
            errors.append(f"{table} row {identity} {column} must contain a JSON object")
    return errors


def validate_data(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table, key_column in (
        ("county", "county_key"),
        ("source_agency", "agency_key"),
        ("dataset", "dataset_key"),
        ("harvest_run", "harvest_key"),
        ("source_release", "release_key"),
    ):
        for identity, value in connection.execute(f"SELECT rowid, {key_column} FROM {table}"):
            if not isinstance(value, str) or KEY_PATTERN.fullmatch(value) is None:
                errors.append(f"{table} row {identity} has invalid {key_column}")
    for table, columns in (
        ("county", ("created_at",)),
        ("source_agency", ("created_at",)),
        ("dataset", ("created_at",)),
        ("harvest_run", ("started_at", "completed_at", "created_at")),
        ("source_file", ("created_at",)),
        ("source_release", ("source_published_at", "accepted_at", "created_at")),
    ):
        for identity, *values in connection.execute(
            f"SELECT rowid, {', '.join(columns)} FROM {table}"
        ):
            for column, value in zip(columns, values):
                if not valid_datetime(value, optional=column in {"completed_at", "source_published_at", "accepted_at"}):
                    errors.append(f"{table} row {identity} has invalid {column}")
    for table, column in (("source_file", "sha256"), ("source_release", "content_sha256")):
        for identity, value in connection.execute(f"SELECT rowid, {column} FROM {table}"):
            if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
                errors.append(f"{table} row {identity} has invalid {column}")
    errors.extend(_validate_json_column(connection, "harvest_run", "source_metadata_json"))
    errors.extend(_validate_json_column(connection, "source_release", "metadata_json"))
    orphaned = connection.execute(
        "SELECT sr.release_key FROM source_release sr "
        "LEFT JOIN source_file sf ON sf.harvest_run_id = sr.harvest_run_id "
        "GROUP BY sr.source_release_id HAVING COUNT(sf.source_file_id) = 0"
    ).fetchall()
    errors.extend(f"Source release {row[0]} has no preserved source files" for row in orphaned)
    return errors



def validate_core_database(path: Path) -> list[str]:
    module_path = Path(__file__).resolve().with_name("kane_db.py")
    spec = importlib.util.spec_from_file_location("_kane_condo_core_db", module_path)
    if spec is None or spec.loader is None:
        return [f"Unable to load core database validator: {module_path}"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return list(module.validate_database(path))
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        return [f"Core GeoPackage validation failed: {exc}"]


def validate_database(path: Path) -> list[str]:
    path = path.resolve()
    core_errors = validate_core_database(path)
    if core_errors:
        return core_errors
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [f"Unable to open GeoPackage read-only: {exc}"]
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        errors: list[str] = []
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            errors.append(f"SQLite integrity_check failed: {integrity!r}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            errors.append(f"SQLite foreign_key_check failed: {foreign_keys!r}")
        errors.extend(validate_schema(connection))
        if not errors:
            errors.extend(validate_data(connection))
        return errors
    except sqlite3.Error as exc:
        return [f"Administrative provenance validation failed: {exc}"]
    finally:
        connection.close()


def ensure_entity(
    connection: sqlite3.Connection,
    table: str,
    key_column: str,
    values: Mapping[str, object],
) -> int:
    key = values[key_column]
    existing = connection.execute(
        f"SELECT * FROM {table} WHERE {key_column} = ?", (key,)
    ).fetchone()
    columns = tuple(values)
    if existing is None:
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
    names = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
    actual = dict(zip(names, existing))
    conflicts = [
        column
        for column, value in values.items()
        if column != "created_at" and actual.get(column) != value
    ]
    if conflicts:
        raise RuntimeError(
            f"Existing {table} {key!r} conflicts in fields: {', '.join(conflicts)}"
        )
    return int(actual[names[0]])


def normalize_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    now = utc_now()
    county = require_mapping(descriptor.get("county"), "county")
    agency = require_mapping(descriptor.get("agency"), "agency")
    dataset = require_mapping(descriptor.get("dataset"), "dataset")
    harvest = require_mapping(descriptor.get("harvest"), "harvest")
    release = require_mapping(descriptor.get("release"), "release")
    files = descriptor.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("files must be a non-empty JSON array")
    status = require_text(harvest, "status", "harvest")
    if status != "succeeded":
        raise RuntimeError("A source release may only be recorded from a succeeded harvest")
    lifecycle = require_text(release, "lifecycle_status", "release")
    if lifecycle not in {"candidate", "accepted", "rejected"}:
        raise RuntimeError("release.lifecycle_status must be candidate, accepted, or rejected")
    accepted_at = require_datetime(release, "accepted_at", "release", optional=True)
    if lifecycle == "accepted" and accepted_at is None:
        raise RuntimeError("An accepted release requires release.accepted_at")
    if lifecycle != "accepted" and accepted_at is not None:
        raise RuntimeError("Only an accepted release may declare release.accepted_at")
    normalized_files = []
    for index, raw in enumerate(files):
        item = require_mapping(raw, f"files[{index}]")
        role = require_text(item, "file_role", f"files[{index}]")
        if role not in {"source", "manifest", "metadata", "inventory", "exclusions", "other"}:
            raise RuntimeError(f"files[{index}].file_role is invalid")
        normalized_files.append(
            {
                "file_role": role,
                "relative_path": require_text(item, "relative_path", f"files[{index}]"),
                "byte_length": require_nonnegative(item, "byte_length", f"files[{index}]"),
                "sha256": require_hash(item, "sha256", f"files[{index}]"),
                "media_type": str(item.get("media_type") or "application/octet-stream"),
                "created_at": now,
            }
        )
    return {
        "county": {
            "county_key": require_key(county, "county_key", "county"),
            "name": require_text(county, "name", "county"),
            "state_code": require_text(county, "state_code", "county").upper(),
            "country_code": str(county.get("country_code") or "US").upper(),
            "fips_code": require_text(county, "fips_code", "county"),
            "created_at": now,
        },
        "agency": {
            "agency_key": require_key(agency, "agency_key", "agency"),
            "name": require_text(agency, "name", "agency"),
            "jurisdiction": require_text(agency, "jurisdiction", "agency"),
            "homepage_uri": agency.get("homepage_uri"),
            "created_at": now,
        },
        "dataset": {
            "dataset_key": require_key(dataset, "dataset_key", "dataset"),
            "name": require_text(dataset, "name", "dataset"),
            "description": str(dataset.get("description") or ""),
            "data_kind": require_text(dataset, "data_kind", "dataset"),
            "source_uri": require_text(dataset, "source_uri", "dataset"),
            "created_at": now,
        },
        "harvest": {
            "harvest_key": require_key(harvest, "harvest_key", "harvest"),
            "started_at": require_datetime(harvest, "started_at", "harvest"),
            "completed_at": require_datetime(harvest, "completed_at", "harvest"),
            "status": status,
            "source_metadata_json": canonical_json(harvest.get("source_metadata", {}), "harvest.source_metadata"),
            "object_count": optional_nonnegative(harvest, "object_count", "harvest"),
            "error_message": None,
            "created_at": now,
        },
        "files": normalized_files,
        "release": {
            "release_key": require_key(release, "release_key", "release"),
            "lifecycle_status": lifecycle,
            "source_published_at": require_datetime(
                release, "source_published_at", "release", optional=True
            ),
            "content_sha256": require_hash(release, "content_sha256", "release"),
            "feature_count": require_nonnegative(release, "feature_count", "release"),
            "metadata_json": canonical_json(release.get("metadata", {}), "release.metadata"),
            "accepted_at": accepted_at,
            "superseded_by_release_id": None,
            "created_at": now,
        },
    }


def record_descriptor(database: Path, descriptor_path: Path) -> dict[str, object]:
    database = database.resolve()
    descriptor = normalize_descriptor(load_descriptor(descriptor_path))
    if validate_database(database):
        raise RuntimeError("Database failed administrative provenance validation before write")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        county_id = ensure_entity(connection, "county", "county_key", descriptor["county"])
        agency_id = ensure_entity(connection, "source_agency", "agency_key", descriptor["agency"])
        dataset_values = dict(descriptor["dataset"], county_id=county_id, source_agency_id=agency_id)
        dataset_id = ensure_entity(connection, "dataset", "dataset_key", dataset_values)
        harvest_values = dict(descriptor["harvest"], dataset_id=dataset_id)
        harvest_id = ensure_entity(connection, "harvest_run", "harvest_key", harvest_values)
        if connection.execute(
            "SELECT 1 FROM source_release WHERE release_key = ?",
            (descriptor["release"]["release_key"],),
        ).fetchone():
            raise RuntimeError(f"Source release already exists: {descriptor['release']['release_key']}")
        if connection.execute(
            "SELECT COUNT(*) FROM source_file WHERE harvest_run_id = ?", (harvest_id,)
        ).fetchone()[0]:
            raise RuntimeError(f"Harvest already has source files: {descriptor['harvest']['harvest_key']}")
        for source_file in descriptor["files"]:
            values = dict(source_file, harvest_run_id=harvest_id)
            columns = tuple(values)
            connection.execute(
                f"INSERT INTO source_file ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
        release_values = dict(
            descriptor["release"], dataset_id=dataset_id, harvest_run_id=harvest_id
        )
        columns = tuple(release_values)
        connection.execute(
            f"INSERT INTO source_release ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            tuple(release_values[column] for column in columns),
        )
        release_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        changed_at = utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name IN "
            "('county','source_agency','dataset','harvest_run','source_file','source_release')",
            (changed_at,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    errors = validate_database(database)
    if errors:
        raise RuntimeError("Database failed validation after write:\n- " + "\n- ".join(errors))
    return trace_release(database, descriptor["release"]["release_key"])


def trace_release(database: Path, release_key: str) -> dict[str, object]:
    if KEY_PATTERN.fullmatch(release_key) is None:
        raise RuntimeError("release_key must be a lowercase hyphenated key")
    errors = validate_database(database)
    if errors:
        raise RuntimeError("Database failed administrative provenance validation:\n- " + "\n- ".join(errors))
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT sr.*, d.dataset_key, d.name AS dataset_name, d.data_kind, d.source_uri, "
            "c.county_key, c.name AS county_name, c.state_code, c.fips_code, "
            "a.agency_key, a.name AS agency_name, a.jurisdiction, a.homepage_uri, "
            "h.harvest_key, h.started_at, h.completed_at, h.status AS harvest_status, "
            "h.source_metadata_json, h.object_count "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN county c ON c.county_id = d.county_id "
            "JOIN source_agency a ON a.source_agency_id = d.source_agency_id "
            "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
            "WHERE sr.release_key = ?",
            (release_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Unknown source release: {release_key}")
        files = [dict(item) for item in connection.execute(
            "SELECT file_role, relative_path, byte_length, sha256, media_type, created_at "
            "FROM source_file WHERE harvest_run_id = ? ORDER BY file_role, relative_path",
            (row["harvest_run_id"],),
        )]
        return {
            "release": {
                "release_key": row["release_key"],
                "lifecycle_status": row["lifecycle_status"],
                "source_published_at": row["source_published_at"],
                "content_sha256": row["content_sha256"],
                "feature_count": row["feature_count"],
                "metadata": json.loads(row["metadata_json"]),
                "accepted_at": row["accepted_at"],
                "created_at": row["created_at"],
            },
            "dataset": {
                "dataset_key": row["dataset_key"],
                "name": row["dataset_name"],
                "data_kind": row["data_kind"],
                "source_uri": row["source_uri"],
            },
            "county": {
                "county_key": row["county_key"],
                "name": row["county_name"],
                "state_code": row["state_code"],
                "fips_code": row["fips_code"],
            },
            "agency": {
                "agency_key": row["agency_key"],
                "name": row["agency_name"],
                "jurisdiction": row["jurisdiction"],
                "homepage_uri": row["homepage_uri"],
            },
            "harvest": {
                "harvest_key": row["harvest_key"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "status": row["harvest_status"],
                "source_metadata": json.loads(row["source_metadata_json"]),
                "object_count": row["object_count"],
                "files": files,
            },
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate administrative provenance")
    validate.add_argument("database", type=Path)
    record = subparsers.add_parser("record", help="record one source release descriptor")
    record.add_argument("database", type=Path)
    record.add_argument("descriptor", type=Path)
    trace = subparsers.add_parser("trace", help="trace one source release as JSON")
    trace.add_argument("database", type=Path)
    trace.add_argument("release_key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            errors = validate_database(args.database)
            result: dict[str, object] = {
                "valid": not errors,
                "path": str(args.database.resolve()),
                "errors": errors,
            }
        elif args.command == "record":
            result = {"valid": True, "lineage": record_descriptor(args.database, args.descriptor)}
        else:
            result = {"valid": True, "lineage": trace_release(args.database, args.release_key)}
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
