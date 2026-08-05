#!/usr/bin/env python3
"""Create and validate the Kane Condo GeoPackage foundation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

GPKG_APPLICATION_ID = 0x47504B47
GPKG_USER_VERSION = 10400
GPKG_VERSION = "1.4.0"
MIGRATION_PATTERN = re.compile(r"^(?P<number>[0-9]{4})_[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DATETIME_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$")

REQUIRED_TABLES = {
    "county",
    "source_agency",
    "dataset",
    "harvest_run",
    "source_file",
    "source_release",
    "source_county_boundary",
    "source_map_feature",
    "source_building",
    "schema_migration",
    "gpkg_spatial_ref_sys",
    "gpkg_contents",
    "gpkg_geometry_columns",
    "gpkg_extensions",
}

CORE_COLUMNS = {
    "schema_migration": (
        ("migration_id", "INTEGER", 0, 1),
        ("filename", "TEXT", 1, 0),
        ("sha256", "TEXT", 1, 0),
        ("applied_at", "DATETIME", 1, 0),
    ),
    "gpkg_spatial_ref_sys": (
        ("srs_name", "TEXT", 1, 0),
        ("srs_id", "INTEGER", 1, 1),
        ("organization", "TEXT", 1, 0),
        ("organization_coordsys_id", "INTEGER", 1, 0),
        ("definition", "TEXT", 1, 0),
        ("description", "TEXT", 0, 0),
    ),
    "gpkg_contents": (
        ("table_name", "TEXT", 1, 1),
        ("data_type", "TEXT", 1, 0),
        ("identifier", "TEXT", 0, 0),
        ("description", "TEXT", 0, 0),
        ("last_change", "DATETIME", 1, 0),
        ("min_x", "DOUBLE", 0, 0),
        ("min_y", "DOUBLE", 0, 0),
        ("max_x", "DOUBLE", 0, 0),
        ("max_y", "DOUBLE", 0, 0),
        ("srs_id", "INTEGER", 0, 0),
    ),
    "gpkg_geometry_columns": (
        ("table_name", "TEXT", 1, 1),
        ("column_name", "TEXT", 1, 2),
        ("geometry_type_name", "TEXT", 1, 0),
        ("srs_id", "INTEGER", 1, 0),
        ("z", "TINYINT", 1, 0),
        ("m", "TINYINT", 1, 0),
    ),
    "gpkg_extensions": (
        ("table_name", "TEXT", 0, 0),
        ("column_name", "TEXT", 0, 0),
        ("extension_name", "TEXT", 1, 0),
        ("definition", "TEXT", 1, 0),
        ("scope", "TEXT", 1, 0),
    ),
    "source_county_boundary": (
        ("source_boundary_id", "INTEGER", 0, 1),
        ("source_release_id", "INTEGER", 1, 0),
        ("source_file_id", "INTEGER", 1, 0),
        ("source_feature_id", "TEXT", 1, 0),
        ("source_ordinal", "INTEGER", 1, 0),
        ("geometry", "BLOB", 1, 0),
        ("geometry_type", "TEXT", 1, 0),
        ("geometry_sha256", "TEXT", 1, 0),
        ("attributes_json", "TEXT", 1, 0),
        ("attributes_sha256", "TEXT", 1, 0),
        ("content_sha256", "TEXT", 1, 0),
        ("min_x", "DOUBLE", 1, 0),
        ("min_y", "DOUBLE", 1, 0),
        ("max_x", "DOUBLE", 1, 0),
        ("max_y", "DOUBLE", 1, 0),
        ("created_at", "DATETIME", 1, 0),
    ),
    "source_building": (
        ("source_building_id", "INTEGER", 0, 1),
        ("source_release_id", "INTEGER", 1, 0),
        ("source_file_id", "INTEGER", 1, 0),
        ("source_feature_id", "TEXT", 1, 0),
        ("source_ordinal", "INTEGER", 1, 0),
        ("geometry", "BLOB", 1, 0),
        ("geometry_type", "TEXT", 1, 0),
        ("geometry_sha256", "TEXT", 1, 0),
        ("attributes_json", "TEXT", 1, 0),
        ("attributes_sha256", "TEXT", 1, 0),
        ("content_sha256", "TEXT", 1, 0),
        ("min_x", "DOUBLE", 1, 0),
        ("min_y", "DOUBLE", 1, 0),
        ("max_x", "DOUBLE", 1, 0),
        ("max_y", "DOUBLE", 1, 0),
        ("created_at", "DATETIME", 1, 0),
    ),
    "source_map_feature": (
        ("source_map_feature_id", "INTEGER", 0, 1),
        ("source_release_id", "INTEGER", 1, 0),
        ("source_file_id", "INTEGER", 1, 0),
        ("source_feature_id", "TEXT", 1, 0),
        ("source_ordinal", "INTEGER", 1, 0),
        ("geometry", "BLOB", 1, 0),
        ("geometry_type", "TEXT", 1, 0),
        ("geometry_sha256", "TEXT", 1, 0),
        ("attributes_json", "TEXT", 1, 0),
        ("attributes_sha256", "TEXT", 1, 0),
        ("content_sha256", "TEXT", 1, 0),
        ("min_x", "DOUBLE", 1, 0),
        ("min_y", "DOUBLE", 1, 0),
        ("max_x", "DOUBLE", 1, 0),
        ("max_y", "DOUBLE", 1, 0),
        ("created_at", "DATETIME", 1, 0),
    ),
}


@dataclass(frozen=True)
class Migration:
    migration_id: int
    path: Path
    sha256: str

    @property
    def filename(self) -> str:
        return self.path.name


def utc_now() -> str:
    """Return a GeoPackage DATETIME value in UTC with millisecond precision."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrations_directory() -> Path:
    return Path(__file__).resolve().parent.parent / "migrations"


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    root = migrations_directory() if directory is None else directory
    paths = sorted(root.glob("*.sql"))
    if not paths:
        raise RuntimeError(f"No SQL migrations found in {root}")

    migrations: list[Migration] = []
    seen: set[int] = set()
    for path in paths:
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise RuntimeError(
                f"Invalid migration filename {path.name!r}; "
                "expected NNNN_lowercase_description.sql"
            )
        migration_id = int(match.group("number"))
        if migration_id in seen:
            raise RuntimeError(f"Duplicate migration number: {migration_id:04d}")
        seen.add(migration_id)
        migrations.append(Migration(migration_id, path, sha256_file(path)))

    ids = [migration.migration_id for migration in migrations]
    if ids != sorted(ids):
        raise RuntimeError("Migration files are not in numeric order")
    return migrations


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def apply_migration(connection: sqlite3.Connection, migration: Migration) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    applied_at = utc_now()
    record = (
        "INSERT INTO schema_migration "
        "(migration_id, filename, sha256, applied_at) VALUES ("
        f"{migration.migration_id}, {sql_literal(migration.filename)}, "
        f"{sql_literal(migration.sha256)}, {sql_literal(applied_at)});"
    )
    touch_contents = (
        "UPDATE gpkg_contents "
        f"SET last_change = {sql_literal(applied_at)} "
        "WHERE table_name = 'schema_migration';"
    )
    try:
        connection.executescript(
            "BEGIN IMMEDIATE;\n" + sql + "\n" + record + "\n" + touch_contents + "\nCOMMIT;"
        )
    except sqlite3.Error:
        connection.rollback()
        raise


def initialize_database(output: Path) -> None:
    """Create a new GeoPackage and apply every repository migration."""
    output = output.resolve()
    if output.suffix.lower() != ".gpkg":
        raise RuntimeError(f"GeoPackage output must use the .gpkg extension: {output}")
    if output.exists():
        raise RuntimeError(f"Output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    migrations = discover_migrations()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(output)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA encoding = 'UTF-8'")
        connection.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        for migration in migrations:
            apply_migration(connection, migration)
    except Exception:
        if connection is not None:
            connection.close()
            connection = None
        remove_sqlite_files(output)
        raise
    finally:
        if connection is not None:
            connection.close()

    errors = validate_database(output)
    if errors:
        remove_sqlite_files(output)
        raise RuntimeError("Created GeoPackage failed validation:\n- " + "\n- ".join(errors))


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return {str(row[0]) for row in rows}


def table_columns(connection: sqlite3.Connection, table_name: str) -> tuple[tuple[object, ...], ...]:
    quoted = table_name.replace('"', '""')
    rows = connection.execute(f'PRAGMA table_info("{quoted}")').fetchall()
    return tuple((row[1], str(row[2]).upper(), row[3], row[5]) for row in rows)


def valid_datetime(value: object) -> bool:
    if not isinstance(value, str) or DATETIME_PATTERN.fullmatch(value) is None:
        return False
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def validate_migration_state(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    try:
        expected = discover_migrations()
        rows = connection.execute(
            "SELECT migration_id, filename, sha256, applied_at "
            "FROM schema_migration ORDER BY migration_id"
        ).fetchall()
    except (RuntimeError, sqlite3.Error) as exc:
        return [f"Migration-state validation failed: {exc}"]

    expected_triplets = [
        (migration.migration_id, migration.filename, migration.sha256) for migration in expected
    ]
    actual_triplets = [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
    if actual_triplets != expected_triplets:
        errors.append(
            "Applied migration identity does not match repository migrations: "
            f"expected {expected_triplets!r}, found {actual_triplets!r}"
        )

    for row in rows:
        if not SHA256_PATTERN.fullmatch(str(row[2])):
            errors.append(f"Migration {row[0]} has an invalid SHA-256 value")
        if not valid_datetime(row[3]):
            errors.append(f"Migration {row[0]} has an invalid applied_at DATETIME")
    return errors


def validate_core_schema(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    found_tables = table_names(connection)
    missing = sorted(REQUIRED_TABLES - found_tables)
    if missing:
        errors.append("Missing required tables: " + ", ".join(missing))
        return errors

    for table_name, expected in CORE_COLUMNS.items():
        actual = table_columns(connection, table_name)
        if actual != expected:
            errors.append(
                f"Unexpected {table_name} columns: expected {expected!r}, found {actual!r}"
            )

    try:
        srs_rows = connection.execute(
            "SELECT srs_id, organization, organization_coordsys_id, definition "
            "FROM gpkg_spatial_ref_sys WHERE srs_id IN (-1, 0, 4326) ORDER BY srs_id"
        ).fetchall()
        expected_srs = [
            (-1, "NONE", -1, "undefined"),
            (0, "NONE", 0, "undefined"),
        ]
        if [tuple(row) for row in srs_rows[:2]] != expected_srs:
            errors.append("Required undefined spatial reference rows are invalid")
        if len(srs_rows) != 3:
            errors.append("GeoPackage must contain SRS rows -1, 0, and 4326")
        elif not (
            srs_rows[2][0] == 4326
            and str(srs_rows[2][1]).lower() == "epsg"
            and srs_rows[2][2] == 4326
            and isinstance(srs_rows[2][3], str)
            and srs_rows[2][3] != "undefined"
        ):
            errors.append("WGS 84 spatial reference row is invalid")

        content = connection.execute(
            "SELECT data_type, identifier, min_x, min_y, max_x, max_y, srs_id, last_change "
            "FROM gpkg_contents WHERE table_name = 'schema_migration'"
        ).fetchone()
        if content is None:
            errors.append("schema_migration is not registered in gpkg_contents")
        else:
            if content[0] != "attributes":
                errors.append("schema_migration must be registered as attributes")
            if content[1] != "Kane Condo schema migrations":
                errors.append("schema_migration has an unexpected identifier")
            if any(value is not None for value in content[2:7]):
                errors.append("schema_migration must not declare spatial bounds or an SRS")
            if not valid_datetime(content[7]):
                errors.append("schema_migration gpkg_contents last_change is invalid")

        boundary_content = connection.execute(
            "SELECT data_type, identifier, srs_id, last_change FROM gpkg_contents "
            "WHERE table_name = 'source_county_boundary'"
        ).fetchone()
        if boundary_content is None:
            errors.append("source_county_boundary is not registered in gpkg_contents")
        elif boundary_content[:3] != ("features", "Kane County boundary", 4326):
            errors.append("source_county_boundary has an invalid gpkg_contents registration")
        elif not valid_datetime(boundary_content[3]):
            errors.append("source_county_boundary gpkg_contents last_change is invalid")

        boundary_geometry = connection.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns WHERE table_name = 'source_county_boundary'"
        ).fetchone()
        if boundary_geometry != ("geometry", "GEOMETRY", 4326, 0, 0):
            errors.append("source_county_boundary has an invalid geometry registration")

        map_content = connection.execute(
            "SELECT data_type, identifier, srs_id, last_change FROM gpkg_contents "
            "WHERE table_name = 'source_map_feature'"
        ).fetchone()
        if map_content is None:
            errors.append("source_map_feature is not registered in gpkg_contents")
        elif map_content[:3] != ("features", "Kane County roads and water", 4326):
            errors.append("source_map_feature has an invalid gpkg_contents registration")
        elif not valid_datetime(map_content[3]):
            errors.append("source_map_feature gpkg_contents last_change is invalid")

        map_geometry = connection.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns WHERE table_name = 'source_map_feature'"
        ).fetchone()
        if map_geometry != ("geometry", "GEOMETRY", 4326, 0, 0):
            errors.append("source_map_feature has an invalid geometry registration")

        building_content = connection.execute(
            "SELECT data_type, identifier, srs_id, last_change FROM gpkg_contents "
            "WHERE table_name = 'source_building'"
        ).fetchone()
        if building_content is None:
            errors.append("source_building is not registered in gpkg_contents")
        elif building_content[:3] != (
            "features", "Kane County official buildings", 4326
        ):
            errors.append("source_building has an invalid gpkg_contents registration")
        elif not valid_datetime(building_content[3]):
            errors.append("source_building gpkg_contents last_change is invalid")

        building_geometry = connection.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m "
            "FROM gpkg_geometry_columns WHERE table_name = 'source_building'"
        ).fetchone()
        if building_geometry != ("geometry", "GEOMETRY", 4326, 0, 0):
            errors.append("source_building has an invalid geometry registration")

    except sqlite3.Error as exc:
        errors.append(f"GeoPackage core data validation failed: {exc}")
    return errors


def validate_database(path: Path) -> list[str]:
    """Return validation errors for a Kane Condo GeoPackage foundation."""
    path = path.resolve()
    if not path.is_file():
        return [f"GeoPackage does not exist: {path}"]
    if path.suffix.lower() != ".gpkg":
        return [f"GeoPackage must use the .gpkg extension: {path}"]
    with path.open("rb") as handle:
        header = handle.read(16)
    if header != b"SQLite format 3\x00":
        return ["File header is not SQLite format 3"]

    errors: list[str] = []
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [f"Unable to open GeoPackage read-only: {exc}"]

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if application_id != GPKG_APPLICATION_ID:
            errors.append(
                f"Unexpected application_id: expected {GPKG_APPLICATION_ID}, found {application_id}"
            )
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if user_version != GPKG_USER_VERSION:
            errors.append(
                f"Unexpected user_version: expected {GPKG_USER_VERSION}, found {user_version}"
            )
        encoding = connection.execute("PRAGMA encoding").fetchone()[0]
        if str(encoding).upper() != "UTF-8":
            errors.append(f"Unexpected SQLite encoding: {encoding}")

        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            errors.append(f"SQLite integrity_check failed: {integrity!r}")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            errors.append(f"SQLite foreign_key_check failed: {foreign_keys!r}")

        errors.extend(validate_core_schema(connection))
        if "schema_migration" in table_names(connection):
            errors.extend(validate_migration_state(connection))
    except sqlite3.Error as exc:
        errors.append(f"SQLite validation failed: {exc}")
    finally:
        connection.close()
    return errors


def database_info(path: Path) -> dict[str, object]:
    path = path.resolve()
    errors = validate_database(path)
    if errors:
        return {"valid": False, "path": str(path), "errors": errors}

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        migrations = [
            {
                "migration_id": row[0],
                "filename": row[1],
                "sha256": row[2],
                "applied_at": row[3],
            }
            for row in connection.execute(
                "SELECT migration_id, filename, sha256, applied_at "
                "FROM schema_migration ORDER BY migration_id"
            )
        ]
        return {
            "valid": True,
            "path": str(path),
            "byte_length": path.stat().st_size,
            "sha256": sha256_file(path),
            "geopackage_version": GPKG_VERSION,
            "application_id": connection.execute("PRAGMA application_id").fetchone()[0],
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "migrations": migrations,
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a new migrated GeoPackage")
    init_parser.add_argument("output", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate a GeoPackage")
    validate_parser.add_argument("database", type=Path)

    info_parser = subparsers.add_parser("info", help="print GeoPackage identity as JSON")
    info_parser.add_argument("database", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            initialize_database(args.output)
            result = database_info(args.output)
        elif args.command == "validate":
            errors = validate_database(args.database)
            result = {
                "valid": not errors,
                "path": str(args.database.resolve()),
                "errors": errors,
            }
        else:
            result = database_info(args.database)
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
