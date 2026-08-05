#!/usr/bin/env python3
"""Import, validate, and inspect immutable official Kane County buildings."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

BUILDING_TABLE = "source_building"
BUILDING_COLUMNS = (
    "source_building_id",
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
ALLOWED_GEOMETRY_TYPES = ("Polygon", "MultiPolygon")


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
kane_boundary = load_sibling("kane_boundary")
kane_map_layers = load_sibling("kane_map_layers")
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
    if BUILDING_TABLE not in kane_db.table_names(connection):
        return [f"Missing official-building table: {BUILDING_TABLE}"]
    actual_columns = table_columns(connection, BUILDING_TABLE)
    if actual_columns != BUILDING_COLUMNS:
        errors.append(
            f"Unexpected {BUILDING_TABLE} columns: expected {BUILDING_COLUMNS!r}, "
            f"found {actual_columns!r}"
        )
    registration = connection.execute(
        "SELECT data_type, identifier, srs_id FROM gpkg_contents WHERE table_name = ?",
        (BUILDING_TABLE,),
    ).fetchone()
    registration_tuple = tuple(registration) if registration is not None else None
    expected_registration = ("features", "Kane County official buildings", 4326)
    if registration_tuple != expected_registration:
        errors.append(
            f"Unexpected {BUILDING_TABLE} gpkg_contents registration: "
            f"{registration_tuple!r}"
        )
    geometry_registration = connection.execute(
        "SELECT column_name, geometry_type_name, srs_id, z, m "
        "FROM gpkg_geometry_columns WHERE table_name = ?",
        (BUILDING_TABLE,),
    ).fetchone()
    geometry_tuple = tuple(geometry_registration) if geometry_registration is not None else None
    if geometry_tuple != ("geometry", "GEOMETRY", 4326, 0, 0):
        errors.append(
            f"Unexpected {BUILDING_TABLE} geometry registration: {geometry_tuple!r}"
        )
    return errors


def _canonical_attributes(value: object, identity: object, errors: list[str]) -> dict[str, Any] | None:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        errors.append(f"Official-building row {identity} has invalid attributes_json")
        return None
    if not isinstance(decoded, dict):
        errors.append(
            f"Official-building row {identity} attributes_json must contain an object"
        )
        return None
    try:
        canonical = canonical_json(decoded)
    except (TypeError, ValueError) as exc:
        errors.append(
            f"Official-building row {identity} attributes_json is not canonicalizable: {exc}"
        )
        return None
    if canonical != value:
        errors.append(f"Official-building row {identity} attributes_json is not canonical")
    return decoded


def _metadata_id_property(metadata_json: object, source_metadata_json: object) -> str | None:
    for value in (metadata_json, source_metadata_json):
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(decoded, dict):
            candidate = decoded.get("id_property")
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def validate_feature_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT b.*, sr.release_key, sr.feature_count, sr.harvest_run_id, "
        "sr.metadata_json, d.dataset_key, d.data_kind, "
        "h.status AS harvest_status, h.object_count, h.source_metadata_json, "
        "sf.harvest_run_id AS file_harvest_run_id, sf.file_role "
        "FROM source_building b "
        "JOIN source_release sr ON sr.source_release_id = b.source_release_id "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "JOIN source_file sf ON sf.source_file_id = b.source_file_id "
        "ORDER BY b.source_building_id"
    ).fetchall()
    for row in rows:
        building_id = row["source_building_id"]
        if row["data_kind"] != "buildings":
            errors.append(
                f"Official-building row {building_id} belongs to non-building dataset"
            )
        if row["harvest_status"] != "succeeded":
            errors.append(
                f"Official-building release {row['release_key']} does not have a succeeded harvest"
            )
        if (
            row["harvest_run_id"] != row["file_harvest_run_id"]
            or row["file_role"] != "source"
        ):
            errors.append(
                f"Official-building row {building_id} source-file lineage is invalid"
            )
        if row["source_ordinal"] < 1:
            errors.append(
                f"Official-building row {building_id} source_ordinal is invalid"
            )
        source_feature_id = row["source_feature_id"]
        if not isinstance(source_feature_id, str) or not source_feature_id.strip():
            errors.append(
                f"Official-building row {building_id} source_feature_id is invalid"
            )
        if not kane_db.valid_datetime(row["created_at"]):
            errors.append(f"Official-building row {building_id} created_at is invalid")
        try:
            decoded_geometry = kane_geometry.decode_geopackage_polygon(row["geometry"])
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append(
                f"Official-building row {building_id} geometry is invalid: {exc}"
            )
            decoded_geometry = None
        if decoded_geometry is not None:
            if decoded_geometry.geometry_type != row["geometry_type"]:
                errors.append(
                    f"Official-building row {building_id} geometry_type is inconsistent"
                )
            if decoded_geometry.geometry_type not in ALLOWED_GEOMETRY_TYPES:
                errors.append(
                    f"Official-building row {building_id} geometry type is invalid"
                )
            if sha256_bytes(decoded_geometry.wkb) != row["geometry_sha256"]:
                errors.append(
                    f"Official-building row {building_id} geometry SHA-256 is invalid"
                )
            stored_bounds = (
                row["min_x"],
                row["min_y"],
                row["max_x"],
                row["max_y"],
            )
            if decoded_geometry.envelope != stored_bounds:
                errors.append(
                    f"Official-building row {building_id} stored bounds are inconsistent"
                )
        attributes = _canonical_attributes(
            row["attributes_json"], building_id, errors
        )
        if attributes is not None:
            canonical = canonical_json(attributes)
            expected_attributes_hash = sha256_bytes(canonical.encode("utf-8"))
            if expected_attributes_hash != row["attributes_sha256"]:
                errors.append(
                    f"Official-building row {building_id} attributes SHA-256 is invalid"
                )
            id_property = _metadata_id_property(
                row["metadata_json"], row["source_metadata_json"]
            )
            if id_property is None:
                errors.append(
                    f"Official-building release {row['release_key']} has no id_property"
                )
            else:
                attribute_identity = attributes.get(id_property)
                if attribute_identity is None or str(attribute_identity).strip() != source_feature_id:
                    errors.append(
                        f"Official-building row {building_id} source identity does not "
                        f"match attributes property {id_property!r}"
                    )
            expected_content_hash = sha256_bytes(
                canonical_json(
                    {
                        "source_feature_id": source_feature_id,
                        "geometry_sha256": row["geometry_sha256"],
                        "attributes_sha256": row["attributes_sha256"],
                    }
                ).encode("utf-8")
            )
            if expected_content_hash != row["content_sha256"]:
                errors.append(
                    f"Official-building row {building_id} content SHA-256 is invalid"
                )
    return errors


def validate_release_groups(
    connection: sqlite3.Connection, *, require_complete: bool
) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    releases = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
        "sr.feature_count, h.object_count, h.status AS harvest_status, "
        "COUNT(b.source_building_id) AS stored_count, "
        "COUNT(DISTINCT b.source_ordinal) AS distinct_ordinals, "
        "MIN(b.source_ordinal) AS min_ordinal, MAX(b.source_ordinal) AS max_ordinal, "
        "COUNT(DISTINCT b.source_file_id) AS source_file_count "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "LEFT JOIN source_building b ON b.source_release_id = sr.source_release_id "
        "WHERE d.data_kind = 'buildings' "
        "GROUP BY sr.source_release_id ORDER BY sr.source_release_id"
    ).fetchall()
    for row in releases:
        release_key = row["release_key"]
        feature_count = row["feature_count"]
        stored_count = row["stored_count"]
        object_count = row["object_count"]
        if row["harvest_status"] != "succeeded" and stored_count:
            errors.append(
                f"Stored building release {release_key} does not have a succeeded harvest"
            )
        if object_count is not None and object_count < feature_count:
            errors.append(
                f"Building release {release_key} harvest object_count is smaller than "
                "feature_count"
            )
        if stored_count:
            if stored_count != feature_count:
                errors.append(
                    f"Building release {release_key} stores {stored_count} features; "
                    f"expected {feature_count}"
                )
            if row["distinct_ordinals"] != stored_count:
                errors.append(
                    f"Building release {release_key} source ordinals are not unique"
                )
            if row["min_ordinal"] != 1 or row["max_ordinal"] != stored_count:
                errors.append(
                    f"Building release {release_key} source ordinals are not contiguous"
                )
            if row["source_file_count"] != 1:
                errors.append(
                    f"Building release {release_key} does not reference exactly one source file"
                )
        elif require_complete and row["lifecycle_status"] in ("accepted", "superseded"):
            errors.append(
                f"Accepted building release {release_key} has no stored features"
            )
    return errors


def validate_contents(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    bounds = connection.execute(
        "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_building"
    ).fetchone()
    contents = connection.execute(
        "SELECT min_x, min_y, max_x, max_y, last_change FROM gpkg_contents "
        "WHERE table_name = 'source_building'"
    ).fetchone()
    if contents is not None:
        expected_bounds = (
            tuple(bounds) if bounds[0] is not None else (None, None, None, None)
        )
        if tuple(contents[:4]) != expected_bounds:
            errors.append(
                "Official-building gpkg_contents bounds do not match stored features"
            )
        if not kane_db.valid_datetime(contents[4]):
            errors.append(
                "Official-building gpkg_contents last_change is invalid"
            )
    return errors


def validate_data(
    connection: sqlite3.Connection, *, require_complete: bool = True
) -> list[str]:
    return (
        validate_feature_rows(connection)
        + validate_release_groups(connection, require_complete=require_complete)
        + validate_contents(connection)
    )


def validate_foundation(path: Path) -> list[str]:
    errors = list(kane_db.validate_database(path))
    if errors:
        return errors
    errors = list(kane_provenance.validate_database(path))
    if errors:
        return errors
    errors = list(kane_boundary.validate_database(path))
    if errors:
        return errors
    errors = list(kane_map_layers.validate_foundation(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        errors = validate_schema(connection)
        if not errors:
            errors.extend(validate_data(connection, require_complete=False))
        return errors
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
            errors.extend(validate_data(connection, require_complete=True))
        return errors
    except sqlite3.Error as exc:
        return [f"Official-building validation failed: {exc}"]
    finally:
        connection.close()


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
    if row["data_kind"] != "buildings":
        raise RuntimeError(f"Source release {release_key} is not a building dataset")
    if row["harvest_status"] != "succeeded":
        raise RuntimeError(
            f"Source release {release_key} does not have a succeeded harvest"
        )
    if row["feature_count"] <= 0:
        raise RuntimeError(
            f"Source release {release_key} feature_count must be positive"
        )
    if row["object_count"] is not None and row["object_count"] < row["feature_count"]:
        raise RuntimeError(
            f"Source release {release_key} harvest object_count is smaller than "
            "feature_count"
        )
    if _id_property(row) is None:
        raise RuntimeError(
            f"Source release {release_key} must declare metadata.id_property or "
            "harvest.source_metadata.id_property"
        )
    return row


def _id_property(release: sqlite3.Row) -> str | None:
    return _metadata_id_property(
        release["metadata_json"], release["source_metadata_json"]
    )


def load_feature_collection(
    path: Path, expected_count: int
) -> tuple[bytes, list[Mapping[str, Any]]]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read building GeoJSON {path}: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("type") != "FeatureCollection":
        raise RuntimeError("Building source must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise RuntimeError("Building FeatureCollection has no features array")
    if len(features) != expected_count:
        raise RuntimeError(
            f"Building source contains {len(features)} features; expected {expected_count}"
        )
    if not features:
        raise RuntimeError("Building source contains no features")
    normalized_features: list[Mapping[str, Any]] = []
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise RuntimeError(f"Building item {ordinal} is not a GeoJSON Feature")
        normalized_features.append(feature)
    return raw, normalized_features


def normalize_features(
    features: Sequence[Mapping[str, Any]], id_property: str
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for ordinal, feature in enumerate(features, start=1):
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            raise RuntimeError(
                f"Building item {ordinal} properties must be a JSON object"
            )
        source_value = properties.get(id_property)
        if source_value is None or not str(source_value).strip():
            raise RuntimeError(
                f"Building item {ordinal} is missing source identity property "
                f"{id_property!r}"
            )
        source_feature_id = str(source_value).strip()
        if source_feature_id in seen:
            raise RuntimeError(
                f"Duplicate building source feature id: {source_feature_id}"
            )
        seen.add(source_feature_id)
        geometry_type, coordinates = kane_geometry.normalize_polygon_geometry(
            feature.get("geometry")
        )
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
        normalized.append(
            {
                "source_feature_id": source_feature_id,
                "source_ordinal": ordinal,
                "geometry": geometry_blob,
                "geometry_type": geometry_type,
                "geometry_sha256": geometry_hash,
                "attributes_json": attributes_json,
                "attributes_sha256": attributes_hash,
                "content_sha256": content_hash,
                "bounds": bounds,
            }
        )
    return normalized


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
        raise RuntimeError(
            "Building GeoJSON does not match preserved source-file evidence"
        )
    return rows[0]


def import_buildings(
    database: Path, release_key: str, geojson: Path
) -> dict[str, object]:
    database = database.resolve()
    errors = validate_foundation(database)
    if errors:
        raise RuntimeError(
            "Database failed validation before official-building import:\n- "
            + "\n- ".join(errors)
        )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        release = release_context(connection, release_key)
        if connection.execute(
            "SELECT 1 FROM source_building WHERE source_release_id = ?",
            (release["source_release_id"],),
        ).fetchone():
            raise RuntimeError(
                f"Official building release is already stored: {release_key}"
            )
        raw, features = load_feature_collection(
            geojson.resolve(), release["feature_count"]
        )
        source_file = matching_source_file(
            connection, release["harvest_run_id"], raw
        )
        id_property = _id_property(release)
        if id_property is None:
            raise RuntimeError(
                f"Source release {release_key} has no id_property"
            )
        normalized = normalize_features(features, id_property)
        now = kane_db.utc_now()
        for feature in normalized:
            bounds = feature["bounds"]
            connection.execute(
                "INSERT INTO source_building ("
                "source_release_id, source_file_id, source_feature_id, source_ordinal, "
                "geometry, geometry_type, geometry_sha256, attributes_json, "
                "attributes_sha256, content_sha256, min_x, min_y, max_x, max_y, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    release["source_release_id"],
                    source_file["source_file_id"],
                    feature["source_feature_id"],
                    feature["source_ordinal"],
                    feature["geometry"],
                    feature["geometry_type"],
                    feature["geometry_sha256"],
                    feature["attributes_json"],
                    feature["attributes_sha256"],
                    feature["content_sha256"],
                    bounds[0],
                    bounds[1],
                    bounds[2],
                    bounds[3],
                    now,
                ),
            )
        aggregate = connection.execute(
            "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) "
            "FROM source_building"
        ).fetchone()
        changed_at = kane_db.utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ?, "
            "last_change = ? WHERE table_name = 'source_building'",
            (*aggregate, changed_at),
        )
        transaction_errors = validate_schema(connection) + validate_data(
            connection, require_complete=True
        )
        if transaction_errors:
            raise RuntimeError(
                "Official-building import failed validation:\n- "
                + "\n- ".join(transaction_errors)
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    errors = validate_database(database)
    if errors:
        raise RuntimeError(
            "Database failed validation after official-building import:\n- "
            + "\n- ".join(errors)
        )
    return building_info(database, release_key)


def building_info(
    database: Path, release_key: str | None = None
) -> dict[str, object]:
    errors = validate_database(database)
    if errors:
        raise RuntimeError(
            "Database failed official-building validation:\n- "
            + "\n- ".join(errors)
        )
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if release_key is None:
            where = "sr.lifecycle_status = 'accepted'"
            parameters: tuple[object, ...] = ()
        else:
            where = "sr.release_key = ?"
            parameters = (release_key,)
        row = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
            "sr.content_sha256 AS release_sha256, sr.feature_count, "
            "d.dataset_key, sf.relative_path, sf.byte_length, "
            "sf.sha256 AS source_file_sha256, COUNT(b.source_building_id) AS stored_count, "
            "MIN(b.min_x) AS min_x, MIN(b.min_y) AS min_y, "
            "MAX(b.max_x) AS max_x, MAX(b.max_y) AS max_y, "
            "MIN(b.created_at) AS created_at "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN source_building b ON b.source_release_id = sr.source_release_id "
            "JOIN source_file sf ON sf.source_file_id = b.source_file_id "
            f"WHERE {where} AND d.data_kind = 'buildings' "
            "GROUP BY sr.source_release_id, sf.source_file_id "
            "ORDER BY sr.source_release_id DESC LIMIT 1",
            parameters,
        ).fetchone()
        if row is None:
            label = release_key or "accepted building release"
            raise RuntimeError(f"No stored official buildings found for {label}")
        geometry_types = [
            item[0]
            for item in connection.execute(
                "SELECT DISTINCT geometry_type FROM source_building "
                "WHERE source_release_id = ? ORDER BY geometry_type",
                (row["source_release_id"],),
            )
        ]
        return {
            "release": {
                "release_key": row["release_key"],
                "lifecycle_status": row["lifecycle_status"],
                "content_sha256": row["release_sha256"],
                "feature_count": row["feature_count"],
                "dataset_key": row["dataset_key"],
                "data_kind": "buildings",
            },
            "source_file": {
                "relative_path": row["relative_path"],
                "byte_length": row["byte_length"],
                "sha256": row["source_file_sha256"],
            },
            "features": {
                "stored_count": row["stored_count"],
                "geometry_types": geometry_types,
                "bounds": [row["min_x"], row["min_y"], row["max_x"], row["max_y"]],
                "created_at": row["created_at"],
            },
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser(
        "validate", help="validate official building storage"
    )
    validate.add_argument("database", type=Path)
    import_parser = subparsers.add_parser(
        "import", help="import one official building release"
    )
    import_parser.add_argument("database", type=Path)
    import_parser.add_argument("release_key")
    import_parser.add_argument("geojson", type=Path)
    info = subparsers.add_parser(
        "info", help="report the accepted or named official building release"
    )
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
                "official_buildings": import_buildings(
                    args.database, args.release_key, args.geojson
                ),
            }
        else:
            result = {
                "valid": True,
                "path": str(args.database.resolve()),
                "official_buildings": building_info(
                    args.database, args.release_key
                ),
            }
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
