#!/usr/bin/env python3
"""Import, validate, and inspect immutable Kane Condo county-boundary features."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

BOUNDARY_TABLE = "source_county_boundary"
BOUNDARY_COLUMNS = (
    "source_boundary_id",
    "source_release_id",
    "source_file_id",
    "source_feature_id",
    "source_ordinal",
    "geometry",
    "geometry_type",
    "geometry_sha256",
    "attributes_json",
    "attributes_sha256",
    "content_sha256",
    "min_x",
    "min_y",
    "max_x",
    "max_y",
    "created_at",
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
kane_provenance = load_sibling("kane_provenance")
kane_geometry = load_sibling("kane_geometry")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = table.replace('"', '""')
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{quoted}")'))


def validate_schema(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    if BOUNDARY_TABLE not in kane_db.table_names(connection):
        return [f"Missing county-boundary table: {BOUNDARY_TABLE}"]
    actual_columns = table_columns(connection, BOUNDARY_TABLE)
    if actual_columns != BOUNDARY_COLUMNS:
        errors.append(
            f"Unexpected {BOUNDARY_TABLE} columns: "
            f"expected {BOUNDARY_COLUMNS!r}, found {actual_columns!r}"
        )
    registration = connection.execute(
        "SELECT data_type, identifier, srs_id FROM gpkg_contents WHERE table_name = ?",
        (BOUNDARY_TABLE,),
    ).fetchone()
    registration_tuple = tuple(registration) if registration is not None else None
    if registration_tuple != ("features", "Kane County boundary", 4326):
        errors.append(
            f"Unexpected {BOUNDARY_TABLE} gpkg_contents registration: {registration_tuple!r}"
        )
    geometry_registration = connection.execute(
        "SELECT column_name, geometry_type_name, srs_id, z, m "
        "FROM gpkg_geometry_columns WHERE table_name = ?",
        (BOUNDARY_TABLE,),
    ).fetchone()
    geometry_tuple = tuple(geometry_registration) if geometry_registration is not None else None
    if geometry_tuple != ("geometry", "GEOMETRY", 4326, 0, 0):
        errors.append(
            f"Unexpected {BOUNDARY_TABLE} geometry registration: {geometry_tuple!r}"
        )
    return errors


def _canonical_attributes(value: object, identity: object, errors: list[str]) -> str | None:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        errors.append(f"County-boundary row {identity} has invalid attributes_json")
        return None
    if not isinstance(decoded, dict):
        errors.append(f"County-boundary row {identity} attributes_json must contain an object")
        return None
    try:
        canonical = canonical_json(decoded)
    except (TypeError, ValueError) as exc:
        errors.append(f"County-boundary row {identity} attributes_json is not canonicalizable: {exc}")
        return None
    if canonical != value:
        errors.append(f"County-boundary row {identity} attributes_json is not canonical")
    return canonical


def validate_data(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    query = (
        "SELECT b.source_boundary_id, b.source_release_id, b.source_file_id, "
        "b.source_feature_id, b.source_ordinal, b.geometry, b.geometry_type, "
        "b.geometry_sha256, b.attributes_json, b.attributes_sha256, b.content_sha256, "
        "b.min_x, b.min_y, b.max_x, b.max_y, b.created_at, "
        "sr.release_key, sr.feature_count, sr.lifecycle_status, sr.harvest_run_id, "
        "d.dataset_key, d.data_kind, h.status, h.object_count, "
        "sf.harvest_run_id, sf.file_role, sf.byte_length, sf.sha256 "
        "FROM source_county_boundary b "
        "JOIN source_release sr ON sr.source_release_id = b.source_release_id "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "JOIN source_file sf ON sf.source_file_id = b.source_file_id "
        "ORDER BY b.source_boundary_id"
    )
    for row in connection.execute(query):
        (
            boundary_id,
            _release_id,
            _source_file_id,
            source_feature_id,
            source_ordinal,
            geometry_blob,
            geometry_type,
            geometry_sha256,
            attributes_json,
            attributes_sha256,
            content_sha256,
            min_x,
            min_y,
            max_x,
            max_y,
            created_at,
            release_key,
            feature_count,
            _lifecycle_status,
            release_harvest_id,
            _dataset_key,
            data_kind,
            harvest_status,
            object_count,
            file_harvest_id,
            file_role,
            _byte_length,
            _source_sha256,
        ) = row
        if data_kind != "boundary":
            errors.append(f"County-boundary row {boundary_id} belongs to non-boundary dataset")
        if feature_count != 1:
            errors.append(f"County-boundary release {release_key} feature_count is not 1")
        if object_count not in (None, 1):
            errors.append(f"County-boundary release {release_key} harvest object_count is not 1")
        if harvest_status != "succeeded":
            errors.append(f"County-boundary release {release_key} harvest did not succeed")
        if release_harvest_id != file_harvest_id or file_role != "source":
            errors.append(f"County-boundary row {boundary_id} source-file lineage is invalid")
        if source_ordinal != 1:
            errors.append(f"County-boundary row {boundary_id} source_ordinal is not 1")
        if not isinstance(source_feature_id, str) or not source_feature_id.strip():
            errors.append(f"County-boundary row {boundary_id} source_feature_id is invalid")
        if not kane_db.valid_datetime(created_at):
            errors.append(f"County-boundary row {boundary_id} created_at is invalid")
        try:
            decoded = kane_geometry.decode_geopackage_polygon(geometry_blob)
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"County-boundary row {boundary_id} geometry is invalid: {exc}")
            decoded = None
        if decoded is not None:
            if decoded.geometry_type != geometry_type:
                errors.append(f"County-boundary row {boundary_id} geometry_type is inconsistent")
            if sha256_bytes(decoded.wkb) != geometry_sha256:
                errors.append(f"County-boundary row {boundary_id} geometry SHA-256 is invalid")
            stored_bounds = (min_x, min_y, max_x, max_y)
            if decoded.envelope != stored_bounds:
                errors.append(f"County-boundary row {boundary_id} stored bounds are inconsistent")
        canonical = _canonical_attributes(attributes_json, boundary_id, errors)
        if canonical is not None:
            expected_attributes_hash = sha256_bytes(canonical.encode("utf-8"))
            if expected_attributes_hash != attributes_sha256:
                errors.append(f"County-boundary row {boundary_id} attributes SHA-256 is invalid")
            expected_content_hash = sha256_bytes(
                canonical_json(
                    {
                        "source_feature_id": source_feature_id,
                        "geometry_sha256": geometry_sha256,
                        "attributes_sha256": attributes_sha256,
                    }
                ).encode("utf-8")
            )
            if expected_content_hash != content_sha256:
                errors.append(f"County-boundary row {boundary_id} content SHA-256 is invalid")

    missing_accepted = connection.execute(
        "SELECT sr.release_key FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "LEFT JOIN source_county_boundary b ON b.source_release_id = sr.source_release_id "
        "WHERE d.data_kind = 'boundary' AND sr.lifecycle_status IN ('accepted','superseded') "
        "AND b.source_boundary_id IS NULL ORDER BY sr.release_key"
    ).fetchall()
    errors.extend(
        f"Accepted county-boundary release {row[0]} has no stored feature"
        for row in missing_accepted
    )

    bounds = connection.execute(
        "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_county_boundary"
    ).fetchone()
    contents = connection.execute(
        "SELECT min_x, min_y, max_x, max_y, last_change FROM gpkg_contents "
        "WHERE table_name = 'source_county_boundary'"
    ).fetchone()
    if contents is not None:
        expected_bounds = tuple(bounds) if bounds[0] is not None else (None, None, None, None)
        if tuple(contents[:4]) != expected_bounds:
            errors.append("County-boundary gpkg_contents bounds do not match stored features")
        if not kane_db.valid_datetime(contents[4]):
            errors.append("County-boundary gpkg_contents last_change is invalid")
    return errors


def validate_foundation(path: Path) -> list[str]:
    errors = list(kane_db.validate_database(path))
    if errors:
        return errors
    errors = list(kane_provenance.validate_database(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        return validate_schema(connection)
    finally:
        connection.close()


def validate_database(path: Path) -> list[str]:
    path = path.resolve()
    errors = validate_foundation(path)
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        errors = validate_schema(connection)
        if not errors:
            errors.extend(validate_data(connection))
        return errors
    except sqlite3.Error as exc:
        return [f"County-boundary validation failed: {exc}"]
    finally:
        connection.close()


def load_feature_collection(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read county-boundary GeoJSON {path}: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("type") != "FeatureCollection":
        raise RuntimeError("County boundary must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or len(features) != 1:
        count = len(features) if isinstance(features, list) else 0
        raise RuntimeError(f"County boundary contains {count} features; expected 1")
    feature = features[0]
    if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
        raise RuntimeError("County boundary item is not a GeoJSON Feature")
    return raw, feature


def normalize_feature(feature: Mapping[str, Any], id_property: str) -> dict[str, object]:
    properties = feature.get("properties")
    if not isinstance(properties, Mapping):
        raise RuntimeError("County boundary properties must be a JSON object")
    source_value = properties.get(id_property)
    if source_value is None or not str(source_value).strip():
        raise RuntimeError(f"County boundary is missing source identity property {id_property!r}")
    source_feature_id = str(source_value).strip()
    geometry_type, coordinates = kane_geometry.normalize_polygon_geometry(feature.get("geometry"))
    geometry_blob, wkb, bounds = kane_geometry.encode_geopackage_polygon(
        geometry_type, coordinates
    )
    attributes_json = canonical_json(dict(properties))
    geometry_hash = sha256_bytes(wkb)
    attributes_hash = sha256_bytes(attributes_json.encode("utf-8"))
    content_hash = sha256_bytes(
        canonical_json(
            {
                "source_feature_id": source_feature_id,
                "geometry_sha256": geometry_hash,
                "attributes_sha256": attributes_hash,
            }
        ).encode("utf-8")
    )
    return {
        "source_feature_id": source_feature_id,
        "geometry": geometry_blob,
        "geometry_type": geometry_type,
        "geometry_sha256": geometry_hash,
        "attributes_json": attributes_json,
        "attributes_sha256": attributes_hash,
        "content_sha256": content_hash,
        "bounds": bounds,
    }


def release_context(connection: sqlite3.Connection, release_key: str) -> sqlite3.Row:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT sr.*, d.dataset_key, d.data_kind, h.status AS harvest_status, "
        "h.object_count, h.source_metadata_json "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "WHERE sr.release_key = ?",
        (release_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Unknown source release: {release_key}")
    if row["data_kind"] != "boundary":
        raise RuntimeError(f"Source release {release_key} is not a boundary dataset")
    if row["harvest_status"] != "succeeded":
        raise RuntimeError(f"Source release {release_key} does not have a succeeded harvest")
    if row["feature_count"] != 1:
        raise RuntimeError(f"Source release {release_key} feature_count must be 1")
    if row["object_count"] not in (None, 1):
        raise RuntimeError(f"Source release {release_key} harvest object_count must be 1")
    try:
        metadata = json.loads(row["metadata_json"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Source release {release_key} metadata is invalid JSON") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError(f"Source release {release_key} metadata must be a JSON object")
    id_property = metadata.get("id_property")
    if not isinstance(id_property, str) or not id_property.strip():
        try:
            source_metadata = json.loads(row["source_metadata_json"])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Source release {release_key} harvest metadata is invalid") from exc
        id_property = source_metadata.get("id_property") if isinstance(source_metadata, dict) else None
    if not isinstance(id_property, str) or not id_property.strip():
        raise RuntimeError(
            f"Source release {release_key} must declare metadata.id_property or "
            "harvest.source_metadata.id_property"
        )
    return row


def matching_source_file(
    connection: sqlite3.Connection, harvest_run_id: int, raw: bytes
) -> sqlite3.Row:
    source_hash = sha256_bytes(raw)
    rows = connection.execute(
        "SELECT * FROM source_file WHERE harvest_run_id = ? AND file_role = 'source' "
        "AND byte_length = ? AND sha256 = ? ORDER BY source_file_id",
        (harvest_run_id, len(raw), source_hash),
    ).fetchall()
    if not rows:
        raise RuntimeError("County-boundary GeoJSON does not match preserved source-file evidence")
    return rows[0]


def import_boundary(database: Path, release_key: str, geojson: Path) -> dict[str, object]:
    database = database.resolve()
    geojson = geojson.resolve()
    errors = validate_foundation(database)
    if errors:
        raise RuntimeError("Database failed validation before boundary import:\n- " + "\n- ".join(errors))
    raw, feature = load_feature_collection(geojson)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        release = release_context(connection, release_key)
        if connection.execute(
            "SELECT 1 FROM source_county_boundary WHERE source_release_id = ?",
            (release["source_release_id"],),
        ).fetchone():
            raise RuntimeError(f"County-boundary release is already stored: {release_key}")
        metadata = json.loads(release["metadata_json"])
        id_property = metadata.get("id_property") if isinstance(metadata, dict) else None
        if not isinstance(id_property, str) or not id_property.strip():
            source_metadata = json.loads(release["source_metadata_json"])
            id_property = source_metadata.get("id_property")
        normalized = normalize_feature(feature, id_property.strip())
        source_file = matching_source_file(connection, release["harvest_run_id"], raw)
        now = kane_db.utc_now()
        bounds = normalized["bounds"]
        connection.execute(
            "INSERT INTO source_county_boundary ("
            "source_release_id, source_file_id, source_feature_id, source_ordinal, geometry, "
            "geometry_type, geometry_sha256, attributes_json, attributes_sha256, content_sha256, "
            "min_x, min_y, max_x, max_y, created_at"
            ") VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                release["source_release_id"],
                source_file["source_file_id"],
                normalized["source_feature_id"],
                normalized["geometry"],
                normalized["geometry_type"],
                normalized["geometry_sha256"],
                normalized["attributes_json"],
                normalized["attributes_sha256"],
                normalized["content_sha256"],
                bounds[0],
                bounds[1],
                bounds[2],
                bounds[3],
                now,
            ),
        )
        aggregate = connection.execute(
            "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_county_boundary"
        ).fetchone()
        connection.execute(
            "UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ?, "
            "last_change = ? WHERE table_name = 'source_county_boundary'",
            (*aggregate, now),
        )
        in_transaction_errors = validate_schema(connection) + validate_data(connection)
        if in_transaction_errors:
            raise RuntimeError(
                "County-boundary import failed validation:\n- "
                + "\n- ".join(in_transaction_errors)
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    errors = validate_database(database)
    if errors:
        raise RuntimeError("Database failed validation after boundary import:\n- " + "\n- ".join(errors))
    return boundary_info(database, release_key)


def boundary_info(database: Path, release_key: str | None = None) -> dict[str, object]:
    errors = validate_database(database)
    if errors:
        raise RuntimeError("Database failed county-boundary validation:\n- " + "\n- ".join(errors))
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        where = "sr.release_key = ?" if release_key else "sr.lifecycle_status = 'accepted'"
        parameters = (release_key,) if release_key else ()
        rows = connection.execute(
            "SELECT b.*, sr.release_key, sr.lifecycle_status, sr.content_sha256 AS release_sha256, "
            "sr.feature_count, d.dataset_key, sf.relative_path, sf.byte_length, "
            "sf.sha256 AS source_file_sha256 "
            "FROM source_county_boundary b "
            "JOIN source_release sr ON sr.source_release_id = b.source_release_id "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN source_file sf ON sf.source_file_id = b.source_file_id "
            f"WHERE {where} ORDER BY sr.source_release_id DESC",
            parameters,
        ).fetchall()
        if not rows:
            label = release_key or "accepted county-boundary release"
            raise RuntimeError(f"No stored county boundary found for {label}")
        if release_key is None and len(rows) != 1:
            raise RuntimeError(f"Accepted county-boundary count is {len(rows)}; expected 1")
        row = rows[0]
        return {
            "release": {
                "release_key": row["release_key"],
                "lifecycle_status": row["lifecycle_status"],
                "content_sha256": row["release_sha256"],
                "feature_count": row["feature_count"],
                "dataset_key": row["dataset_key"],
            },
            "source_file": {
                "relative_path": row["relative_path"],
                "byte_length": row["byte_length"],
                "sha256": row["source_file_sha256"],
            },
            "boundary": {
                "source_feature_id": row["source_feature_id"],
                "source_ordinal": row["source_ordinal"],
                "geometry_type": row["geometry_type"],
                "geometry_sha256": row["geometry_sha256"],
                "attributes": json.loads(row["attributes_json"]),
                "attributes_sha256": row["attributes_sha256"],
                "content_sha256": row["content_sha256"],
                "bounds": [row["min_x"], row["min_y"], row["max_x"], row["max_y"]],
                "created_at": row["created_at"],
            },
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate county-boundary storage")
    validate.add_argument("database", type=Path)
    import_parser = subparsers.add_parser(
        "import", help="import one boundary GeoJSON into an existing source release"
    )
    import_parser.add_argument("database", type=Path)
    import_parser.add_argument("release_key")
    import_parser.add_argument("geojson", type=Path)
    info = subparsers.add_parser("info", help="report one stored county boundary as JSON")
    info.add_argument("database", type=Path)
    info.add_argument("release_key", nargs="?")
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
        elif args.command == "import":
            result = {
                "valid": True,
                "path": str(args.database.resolve()),
                "county_boundary": import_boundary(
                    args.database, args.release_key, args.geojson
                ),
            }
        else:
            result = {
                "valid": True,
                "path": str(args.database.resolve()),
                "county_boundary": boundary_info(args.database, args.release_key),
            }
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
