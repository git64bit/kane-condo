#!/usr/bin/env python3
"""Create, validate, and inspect Kane Condo project building identities."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

PROJECT_TABLE = "project_building"
MAPPING_TABLE = "project_building_source_mapping"
IDENTITY_ALGORITHM = "sha256-release-feature-v1"
BUILDING_KEY_PATTERN = re.compile(r"^kcb-[0-9a-f]{64}$")
PROJECT_COLUMNS = (
    "project_building_id",
    "building_key",
    "lifecycle_status",
    "created_from_source_building_id",
    "identity_algorithm",
    "created_at",
    "retired_at",
)
MAPPING_COLUMNS = (
    "mapping_id",
    "project_building_id",
    "source_building_id",
    "relationship_type",
    "decision_method",
    "mapping_status",
    "created_at",
    "reviewed_at",
)
def load_sibling(name: str):
    module_path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_kane_condo_{name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
kane_db = load_sibling("kane_db")
kane_buildings = load_sibling("kane_buildings")
def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
def project_building_key(release_key: str, source_feature_id: str) -> str:
    release = release_key.strip()
    feature = source_feature_id.strip()
    if not release or not feature:
        raise RuntimeError("Project building identity inputs must be non-empty")
    payload = canonical_json(
        {
            "algorithm": IDENTITY_ALGORITHM,
            "release_key": release,
            "source_feature_id": feature,
        }
    ).encode("utf-8")
    return "kcb-" + hashlib.sha256(payload).hexdigest()
def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = table.replace('"', '""')
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{quoted}")'))
def validate_schema(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    tables = kane_db.table_names(connection)
    for table, columns in (
        (PROJECT_TABLE, PROJECT_COLUMNS),
        (MAPPING_TABLE, MAPPING_COLUMNS),
    ):
        if table not in tables:
            errors.append(f"Missing project-building table: {table}")
            continue
        actual = table_columns(connection, table)
        if actual != columns:
            errors.append(
                f"Unexpected {table} columns: expected {columns!r}, found {actual!r}"
            )
    expected = {
        PROJECT_TABLE: "Kane Condo project buildings",
        MAPPING_TABLE: "Kane Condo building mappings",
    }
    registrations = {
        str(row[0]): (str(row[1]), str(row[2]), row[3])
        for row in connection.execute(
            "SELECT table_name, data_type, identifier, srs_id FROM gpkg_contents "
            "WHERE table_name IN (?, ?)",
            (PROJECT_TABLE, MAPPING_TABLE),
        )
    }
    for table, identifier in expected.items():
        row = registrations.get(table)
        if row != ("attributes", identifier, None):
            errors.append(f"Unexpected {table} gpkg_contents registration: {row!r}")
    return errors
def validate_project_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT pb.*, sb.source_feature_id, sr.release_key, d.data_kind "
        "FROM project_building pb "
        "JOIN source_building sb "
        "ON sb.source_building_id = pb.created_from_source_building_id "
        "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "ORDER BY pb.project_building_id"
    ).fetchall()
    for row in rows:
        identity = row["project_building_id"]
        if row["data_kind"] != "buildings":
            errors.append(f"Project building {identity} originated from a non-building dataset")
        if row["identity_algorithm"] != IDENTITY_ALGORITHM:
            errors.append(f"Project building {identity} has an unsupported identity algorithm")
        expected_key = project_building_key(
            row["release_key"], row["source_feature_id"]
        )
        if row["building_key"] != expected_key:
            errors.append(f"Project building {identity} has an invalid deterministic key")
        if BUILDING_KEY_PATTERN.fullmatch(str(row["building_key"])) is None:
            errors.append(f"Project building {identity} building_key is invalid")
        if not kane_db.valid_datetime(row["created_at"]):
            errors.append(f"Project building {identity} created_at is invalid")
        retired_at = row["retired_at"]
        if retired_at is not None and not kane_db.valid_datetime(retired_at):
            errors.append(f"Project building {identity} retired_at is invalid")
    return errors
def validate_mapping_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT m.*, pb.created_from_source_building_id, d.data_kind "
        "FROM project_building_source_mapping m "
        "JOIN project_building pb ON pb.project_building_id = m.project_building_id "
        "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
        "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "ORDER BY m.mapping_id"
    ).fetchall()
    for row in rows:
        mapping_id = row["mapping_id"]
        if row["data_kind"] != "buildings":
            errors.append(f"Project-building mapping {mapping_id} targets a non-building dataset")
        if not kane_db.valid_datetime(row["created_at"]):
            errors.append(f"Project-building mapping {mapping_id} created_at is invalid")
        reviewed_at = row["reviewed_at"]
        if reviewed_at is not None and not kane_db.valid_datetime(reviewed_at):
            errors.append(f"Project-building mapping {mapping_id} reviewed_at is invalid")
        if row["relationship_type"] == "initial":
            if row["source_building_id"] != row["created_from_source_building_id"]:
                errors.append(
                    f"Project-building mapping {mapping_id} initial source does not match origin"
                )
            if row["decision_method"] != "deterministic-seed":
                errors.append(
                    f"Project-building mapping {mapping_id} initial decision method is invalid"
                )
            if row["mapping_status"] != "confirmed":
                errors.append(
                    f"Project-building mapping {mapping_id} initial mapping is not confirmed"
                )
    return errors
def validate_initial_mappings(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    rows = connection.execute(
        "SELECT pb.project_building_id, pb.created_from_source_building_id, "
        "COUNT(m.mapping_id), MIN(m.source_building_id), MAX(m.source_building_id) "
        "FROM project_building pb "
        "LEFT JOIN project_building_source_mapping m "
        "ON m.project_building_id = pb.project_building_id "
        "AND m.relationship_type = 'initial' AND m.mapping_status = 'confirmed' "
        "GROUP BY pb.project_building_id ORDER BY pb.project_building_id"
    ).fetchall()
    for project_id, origin_id, count, minimum, maximum in rows:
        if count != 1 or minimum != origin_id or maximum != origin_id:
            errors.append(
                f"Project building {project_id} does not have exactly one confirmed initial mapping"
            )
    return errors
def validate_accepted_release_coverage(
    connection: sqlite3.Connection, *, require_complete: bool
) -> list[str]:
    if not require_complete:
        return []
    errors: list[str] = []
    rows = connection.execute(
        "SELECT sr.release_key, COUNT(DISTINCT sb.source_building_id) AS source_count, "
        "COUNT(DISTINCT CASE WHEN m.mapping_status = 'confirmed' "
        "THEN sb.source_building_id END) AS mapped_count "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "LEFT JOIN source_building sb ON sb.source_release_id = sr.source_release_id "
        "LEFT JOIN project_building_source_mapping m "
        "ON m.source_building_id = sb.source_building_id "
        "WHERE d.data_kind = 'buildings' AND sr.lifecycle_status = 'accepted' "
        "GROUP BY sr.source_release_id ORDER BY sr.source_release_id"
    ).fetchall()
    for release_key, source_count, mapped_count in rows:
        if source_count and mapped_count != source_count:
            errors.append(
                f"Accepted building release {release_key} maps {mapped_count} of "
                f"{source_count} official footprints to project identities"
            )
    return errors
def validate_contents(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table in (PROJECT_TABLE, MAPPING_TABLE):
        row = connection.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name = ?", (table,)
        ).fetchone()
        if row is None or not kane_db.valid_datetime(row[0]):
            errors.append(f"{table} gpkg_contents last_change is invalid")
    return errors
def validate_data(
    connection: sqlite3.Connection, *, require_complete: bool = True
) -> list[str]:
    return (
        validate_project_rows(connection)
        + validate_mapping_rows(connection)
        + validate_initial_mappings(connection)
        + validate_accepted_release_coverage(
            connection, require_complete=require_complete
        )
        + validate_contents(connection)
    )


def validate_foundation(path: Path) -> list[str]:
    errors = list(kane_buildings.validate_database(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        errors = validate_schema(connection)
        if not errors:
            errors.extend(validate_data(connection, require_complete=False))
        return errors
    except sqlite3.Error as exc:
        return [f"Project-building foundation validation failed: {exc}"]
    finally:
        connection.close()


def validate_database(path: Path) -> list[str]:
    errors = list(kane_buildings.validate_database(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        errors = validate_schema(connection)
        if not errors:
            errors.extend(validate_data(connection, require_complete=True))
        return errors
    except sqlite3.Error as exc:
        return [f"Project-building validation failed: {exc}"]
    finally:
        connection.close()


def accepted_release_context(
    connection: sqlite3.Connection, release_key: str
) -> sqlite3.Row:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
        "sr.feature_count, d.data_kind, COUNT(sb.source_building_id) AS stored_count "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "LEFT JOIN source_building sb ON sb.source_release_id = sr.source_release_id "
        "WHERE sr.release_key = ? GROUP BY sr.source_release_id",
        (release_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Unknown source release: {release_key}")
    if row["data_kind"] != "buildings":
        raise RuntimeError(f"Source release {release_key} is not a building dataset")
    if row["lifecycle_status"] != "accepted":
        raise RuntimeError(f"Project identity seed requires an accepted building release")
    if row["feature_count"] <= 0 or row["stored_count"] != row["feature_count"]:
        raise RuntimeError(
            f"Accepted building release {release_key} is not completely stored"
        )
    return row


def seed_project_buildings(database: Path, release_key: str) -> dict[str, object]:
    database = database.resolve()
    errors = validate_foundation(database)
    if errors:
        raise RuntimeError(
            "Database failed validation before project-identity seed:\n- "
            + "\n- ".join(errors)
        )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        release = accepted_release_context(connection, release_key)
        existing_projects = connection.execute(
            "SELECT COUNT(*) FROM project_building"
        ).fetchone()[0]
        existing_mappings = connection.execute(
            "SELECT COUNT(*) FROM project_building_source_mapping"
        ).fetchone()[0]
        if existing_projects or existing_mappings:
            raise RuntimeError("Project building identities are already initialized")
        source_rows = connection.execute(
            "SELECT source_building_id, source_feature_id FROM source_building "
            "WHERE source_release_id = ? ORDER BY source_ordinal",
            (release["source_release_id"],),
        ).fetchall()
        now = kane_db.utc_now()
        for source_row in source_rows:
            building_key = project_building_key(
                release["release_key"], source_row["source_feature_id"]
            )
            cursor = connection.execute(
                "INSERT INTO project_building ("
                "building_key, lifecycle_status, created_from_source_building_id, "
                "identity_algorithm, created_at, retired_at"
                ") VALUES (?, 'active', ?, ?, ?, NULL)",
                (
                    building_key,
                    source_row["source_building_id"],
                    IDENTITY_ALGORITHM,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO project_building_source_mapping ("
                "project_building_id, source_building_id, relationship_type, "
                "decision_method, mapping_status, created_at, reviewed_at"
                ") VALUES (?, ?, 'initial', 'deterministic-seed', 'confirmed', ?, NULL)",
                (cursor.lastrowid, source_row["source_building_id"], now),
            )
        changed_at = kane_db.utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name IN (?, ?)",
            (changed_at, PROJECT_TABLE, MAPPING_TABLE),
        )
        transaction_errors = validate_schema(connection) + validate_data(
            connection, require_complete=True
        )
        if transaction_errors:
            raise RuntimeError(
                "Project-identity seed failed validation:\n- "
                + "\n- ".join(transaction_errors)
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return _identity_info(connection, database, release_key)
    finally:
        connection.close()


def _identity_info(
    connection: sqlite3.Connection, database: Path, release_key: str | None
) -> dict[str, object]:
    if release_key is None:
        release = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status "
            "FROM source_release sr JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "WHERE d.data_kind = 'buildings' AND sr.lifecycle_status = 'accepted'"
        ).fetchone()
    else:
        release = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status "
            "FROM source_release sr JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "WHERE d.data_kind = 'buildings' AND sr.release_key = ?", (release_key,)
        ).fetchone()
        if release is None:
            raise RuntimeError(f"Unknown building release: {release_key}")
    lifecycle = dict(connection.execute(
        "SELECT lifecycle_status, COUNT(*) FROM project_building "
        "GROUP BY lifecycle_status ORDER BY lifecycle_status"
    ))
    relationships = dict(connection.execute(
        "SELECT relationship_type, COUNT(*) FROM project_building_source_mapping "
        "GROUP BY relationship_type ORDER BY relationship_type"
    ))
    statuses = dict(connection.execute(
        "SELECT mapping_status, COUNT(*) FROM project_building_source_mapping "
        "GROUP BY mapping_status ORDER BY mapping_status"
    ))
    release_info: dict[str, object] | None = None
    if release is not None:
        counts = connection.execute(
            "SELECT COUNT(DISTINCT sb.source_building_id), "
            "COUNT(DISTINCT CASE WHEN m.mapping_status = 'confirmed' "
            "THEN sb.source_building_id END) "
            "FROM source_building sb LEFT JOIN project_building_source_mapping m "
            "ON m.source_building_id = sb.source_building_id "
            "WHERE sb.source_release_id = ?", (release["source_release_id"],)
        ).fetchone()
        release_info = {
            "release_key": release["release_key"],
            "lifecycle_status": release["lifecycle_status"],
            "source_building_count": counts[0],
            "confirmed_mapped_source_count": counts[1],
        }
    return {
        "valid": True,
        "path": str(database),
        "identity_algorithm": IDENTITY_ALGORITHM,
        "project_buildings": {
            "count": connection.execute("SELECT COUNT(*) FROM project_building").fetchone()[0],
            "lifecycle_counts": lifecycle,
        },
        "mappings": {
            "count": connection.execute(
                "SELECT COUNT(*) FROM project_building_source_mapping"
            ).fetchone()[0],
            "relationship_counts": relationships,
            "status_counts": statuses,
        },
        "release": release_info,
    }


def project_identity_info(
    database: Path, release_key: str | None = None
) -> dict[str, object]:
    database = database.resolve()
    errors = validate_database(database)
    if errors:
        return {"valid": False, "path": str(database), "errors": errors}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return _identity_info(connection, database, release_key)
    finally:
        connection.close()

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("seed", help="create deterministic project identities")
    seed.add_argument("database", type=Path)
    seed.add_argument("release_key")
    validate = subparsers.add_parser("validate", help="validate project identities")
    validate.add_argument("database", type=Path)
    info = subparsers.add_parser("info", help="report project identity state")
    info.add_argument("database", type=Path)
    info.add_argument("release_key", nargs="?")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "seed":
            result = seed_project_buildings(args.database, args.release_key)
        elif args.command == "validate":
            errors = validate_database(args.database)
            result = {
                "valid": not errors,
                "path": str(args.database.resolve()),
                "errors": errors,
            }
        else:
            result = project_identity_info(args.database, args.release_key)
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
