#!/usr/bin/env python3
"""Import, validate, and inspect immutable Kane Condo roads and water features."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

MAP_TABLE = "source_map_feature"
MAP_COLUMNS = (
    "source_map_feature_id",
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
ALLOWED_GEOMETRY_TYPES = {
    "roads": ("LineString", "MultiLineString"),
    "water": ("LineString", "MultiLineString", "Polygon", "MultiPolygon"),
}


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
    if MAP_TABLE not in kane_db.table_names(connection):
        return [f"Missing roads-and-water table: {MAP_TABLE}"]
    actual_columns = table_columns(connection, MAP_TABLE)
    if actual_columns != MAP_COLUMNS:
        errors.append(
            f"Unexpected {MAP_TABLE} columns: expected {MAP_COLUMNS!r}, "
            f"found {actual_columns!r}"
        )
    registration = connection.execute(
        "SELECT data_type, identifier, srs_id FROM gpkg_contents WHERE table_name = ?",
        (MAP_TABLE,),
    ).fetchone()
    registration_tuple = tuple(registration) if registration is not None else None
    expected_registration = ("features", "Kane County roads and water", 4326)
    if registration_tuple != expected_registration:
        errors.append(
            f"Unexpected {MAP_TABLE} gpkg_contents registration: {registration_tuple!r}"
        )
    geometry_registration = connection.execute(
        "SELECT column_name, geometry_type_name, srs_id, z, m "
        "FROM gpkg_geometry_columns WHERE table_name = ?",
        (MAP_TABLE,),
    ).fetchone()
    geometry_tuple = tuple(geometry_registration) if geometry_registration is not None else None
    if geometry_tuple != ("geometry", "GEOMETRY", 4326, 0, 0):
        errors.append(f"Unexpected {MAP_TABLE} geometry registration: {geometry_tuple!r}")
    return errors


def _canonical_attributes(value: object, identity: object, errors: list[str]) -> str | None:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        errors.append(f"Map-feature row {identity} has invalid attributes_json")
        return None
    if not isinstance(decoded, dict):
        errors.append(f"Map-feature row {identity} attributes_json must contain an object")
        return None
    try:
        canonical = canonical_json(decoded)
    except (TypeError, ValueError) as exc:
        errors.append(f"Map-feature row {identity} attributes_json is not canonicalizable: {exc}")
        return None
    if canonical != value:
        errors.append(f"Map-feature row {identity} attributes_json is not canonical")
    return canonical


def validate_feature_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT f.*, sr.release_key, sr.feature_count, sr.harvest_run_id, "
        "d.dataset_key, d.data_kind, h.status AS harvest_status, h.object_count, "
        "sf.harvest_run_id AS file_harvest_run_id, sf.file_role "
        "FROM source_map_feature f "
        "JOIN source_release sr ON sr.source_release_id = f.source_release_id "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "JOIN source_file sf ON sf.source_file_id = f.source_file_id "
        "ORDER BY f.source_map_feature_id"
    ).fetchall()
    for row in rows:
        feature_id = row["source_map_feature_id"]
        data_kind = row["data_kind"]
        allowed = ALLOWED_GEOMETRY_TYPES.get(data_kind)
        if allowed is None:
            errors.append(
                f"Map-feature row {feature_id} belongs to unsupported data kind {data_kind!r}"
            )
        if row["harvest_status"] != "succeeded":
            errors.append(
                f"Map-feature release {row['release_key']} does not have a succeeded harvest"
            )
        if (
            row["harvest_run_id"] != row["file_harvest_run_id"]
            or row["file_role"] != "source"
        ):
            errors.append(f"Map-feature row {feature_id} source-file lineage is invalid")
        if row["source_ordinal"] < 1:
            errors.append(f"Map-feature row {feature_id} source_ordinal is invalid")
        source_feature_id = row["source_feature_id"]
        if not isinstance(source_feature_id, str) or not source_feature_id.strip():
            errors.append(f"Map-feature row {feature_id} source_feature_id is invalid")
        if not kane_db.valid_datetime(row["created_at"]):
            errors.append(f"Map-feature row {feature_id} created_at is invalid")
        try:
            decoded = kane_geometry.decode_geopackage_geometry(row["geometry"])
        except (RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"Map-feature row {feature_id} geometry is invalid: {exc}")
            decoded = None
        if decoded is not None:
            if decoded.geometry_type != row["geometry_type"]:
                errors.append(f"Map-feature row {feature_id} geometry_type is inconsistent")
            if allowed is not None and decoded.geometry_type not in allowed:
                errors.append(
                    f"Map-feature row {feature_id} geometry {decoded.geometry_type} "
                    f"is invalid for {data_kind}"
                )
            if sha256_bytes(decoded.wkb) != row["geometry_sha256"]:
                errors.append(f"Map-feature row {feature_id} geometry SHA-256 is invalid")
            stored_bounds = (row["min_x"], row["min_y"], row["max_x"], row["max_y"])
            if decoded.envelope != stored_bounds:
                errors.append(f"Map-feature row {feature_id} stored bounds are inconsistent")
        canonical = _canonical_attributes(row["attributes_json"], feature_id, errors)
        if canonical is not None:
            expected_attributes_hash = sha256_bytes(canonical.encode("utf-8"))
            if expected_attributes_hash != row["attributes_sha256"]:
                errors.append(f"Map-feature row {feature_id} attributes SHA-256 is invalid")
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
                errors.append(f"Map-feature row {feature_id} content SHA-256 is invalid")
    return errors


def validate_release_groups(
    connection: sqlite3.Connection, *, require_complete: bool
) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    releases = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, sr.feature_count, "
        "d.dataset_key, d.data_kind, h.object_count, h.status AS harvest_status, "
        "COUNT(f.source_map_feature_id) AS stored_count, "
        "COUNT(DISTINCT f.source_ordinal) AS distinct_ordinals, "
        "MIN(f.source_ordinal) AS min_ordinal, MAX(f.source_ordinal) AS max_ordinal, "
        "COUNT(DISTINCT f.source_file_id) AS source_file_count "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "LEFT JOIN source_map_feature f ON f.source_release_id = sr.source_release_id "
        "WHERE d.data_kind IN ('roads','water') "
        "GROUP BY sr.source_release_id ORDER BY sr.source_release_id"
    ).fetchall()
    for row in releases:
        release_key = row["release_key"]
        feature_count = row["feature_count"]
        stored_count = row["stored_count"]
        object_count = row["object_count"]
        if row["harvest_status"] != "succeeded" and stored_count:
            errors.append(f"Stored map release {release_key} does not have a succeeded harvest")
        if object_count is not None and object_count < feature_count:
            errors.append(
                f"Map release {release_key} harvest object_count is smaller than feature_count"
            )
        if stored_count:
            if stored_count != feature_count:
                errors.append(
                    f"Map release {release_key} stores {stored_count} features; "
                    f"expected {feature_count}"
                )
            if row["distinct_ordinals"] != stored_count:
                errors.append(f"Map release {release_key} source ordinals are not unique")
            if row["min_ordinal"] != 1 or row["max_ordinal"] != stored_count:
                errors.append(f"Map release {release_key} source ordinals are not contiguous")
            if row["source_file_count"] != 1:
                errors.append(f"Map release {release_key} does not reference exactly one source file")
        elif require_complete and row["lifecycle_status"] in ("accepted", "superseded"):
            errors.append(f"Accepted map release {release_key} has no stored features")
    return errors


def validate_contents(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    bounds = connection.execute(
        "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_map_feature"
    ).fetchone()
    contents = connection.execute(
        "SELECT min_x, min_y, max_x, max_y, last_change FROM gpkg_contents "
        "WHERE table_name = 'source_map_feature'"
    ).fetchone()
    if contents is not None:
        expected_bounds = tuple(bounds) if bounds[0] is not None else (None, None, None, None)
        if tuple(contents[:4]) != expected_bounds:
            errors.append("Roads-and-water gpkg_contents bounds do not match stored features")
        if not kane_db.valid_datetime(contents[4]):
            errors.append("Roads-and-water gpkg_contents last_change is invalid")
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
        return [f"Roads-and-water validation failed: {exc}"]
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
    if row["data_kind"] not in ALLOWED_GEOMETRY_TYPES:
        raise RuntimeError(f"Source release {release_key} is not a roads or water dataset")
    if row["harvest_status"] != "succeeded":
        raise RuntimeError(f"Source release {release_key} does not have a succeeded harvest")
    if row["feature_count"] <= 0:
        raise RuntimeError(f"Source release {release_key} feature_count must be positive")
    if row["object_count"] is not None and row["object_count"] < row["feature_count"]:
        raise RuntimeError(
            f"Source release {release_key} harvest object_count is smaller than feature_count"
        )
    metadata = json.loads(row["metadata_json"])
    if not isinstance(metadata, dict):
        raise RuntimeError(f"Source release {release_key} metadata must be a JSON object")
    id_property = metadata.get("id_property")
    if not isinstance(id_property, str) or not id_property.strip():
        source_metadata = json.loads(row["source_metadata_json"])
        id_property = source_metadata.get("id_property") if isinstance(source_metadata, dict) else None
    if not isinstance(id_property, str) or not id_property.strip():
        raise RuntimeError(
            f"Source release {release_key} must declare metadata.id_property or "
            "harvest.source_metadata.id_property"
        )
    return row


def load_feature_collection(path: Path, expected_count: int) -> tuple[bytes, list[Mapping[str, Any]]]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read map-layer GeoJSON {path}: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("type") != "FeatureCollection":
        raise RuntimeError("Map layer must be a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list):
        raise RuntimeError("Map-layer FeatureCollection has no features array")
    if len(features) != expected_count:
        raise RuntimeError(
            f"Map layer contains {len(features)} features; expected {expected_count}"
        )
    if not features:
        raise RuntimeError("Map layer contains no features")
    normalized_features: list[Mapping[str, Any]] = []
    for ordinal, feature in enumerate(features, start=1):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise RuntimeError(f"Map-layer item {ordinal} is not a GeoJSON Feature")
        normalized_features.append(feature)
    return raw, normalized_features


def normalize_features(
    features: Sequence[Mapping[str, Any]], id_property: str, data_kind: str
) -> list[dict[str, object]]:
    allowed_types = ALLOWED_GEOMETRY_TYPES[data_kind]
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for ordinal, feature in enumerate(features, start=1):
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            raise RuntimeError(f"Map-layer item {ordinal} properties must be a JSON object")
        source_value = properties.get(id_property)
        if source_value is None or not str(source_value).strip():
            raise RuntimeError(
                f"Map-layer item {ordinal} is missing source identity property {id_property!r}"
            )
        source_feature_id = str(source_value).strip()
        if source_feature_id in seen:
            raise RuntimeError(f"Duplicate map-layer source feature id: {source_feature_id}")
        seen.add(source_feature_id)
        geometry_type, coordinates = kane_geometry.normalize_map_geometry(feature.get("geometry"))
        if geometry_type not in allowed_types:
            raise RuntimeError(
                f"Map-layer feature {source_feature_id} geometry is {geometry_type}; "
                f"expected {' or '.join(allowed_types)}"
            )
        geometry_blob, wkb, bounds = kane_geometry.encode_geopackage_geometry(
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
        raise RuntimeError("Map-layer GeoJSON does not match preserved source-file evidence")
    return rows[0]


def _id_property(release: sqlite3.Row) -> str:
    metadata = json.loads(release["metadata_json"])
    value = metadata.get("id_property") if isinstance(metadata, dict) else None
    if not isinstance(value, str) or not value.strip():
        source_metadata = json.loads(release["source_metadata_json"])
        value = source_metadata.get("id_property") if isinstance(source_metadata, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Source release {release['release_key']} has no id_property")
    return value.strip()


def import_map_layers(
    database: Path, sources: Sequence[tuple[str, Path]]
) -> dict[str, object]:
    database = database.resolve()
    if not sources:
        raise RuntimeError("At least one release and GeoJSON source are required")
    release_keys = [release_key for release_key, _path in sources]
    if len(set(release_keys)) != len(release_keys):
        raise RuntimeError("Each map-layer release may appear only once in an import")
    errors = validate_foundation(database)
    if errors:
        raise RuntimeError(
            "Database failed validation before roads-and-water import:\n- "
            + "\n- ".join(errors)
        )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        for release_key, geojson in sources:
            release = release_context(connection, release_key)
            if connection.execute(
                "SELECT 1 FROM source_map_feature WHERE source_release_id = ?",
                (release["source_release_id"],),
            ).fetchone():
                raise RuntimeError(f"Map-layer release is already stored: {release_key}")
            raw, features = load_feature_collection(geojson.resolve(), release["feature_count"])
            source_file = matching_source_file(connection, release["harvest_run_id"], raw)
            normalized = normalize_features(
                features, _id_property(release), release["data_kind"]
            )
            now = kane_db.utc_now()
            for feature in normalized:
                bounds = feature["bounds"]
                connection.execute(
                    "INSERT INTO source_map_feature ("
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
            "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM source_map_feature"
        ).fetchone()
        now = kane_db.utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ?, "
            "last_change = ? WHERE table_name = 'source_map_feature'",
            (*aggregate, now),
        )
        transaction_errors = validate_schema(connection) + validate_data(
            connection, require_complete=True
        )
        if transaction_errors:
            raise RuntimeError(
                "Roads-and-water import failed validation:\n- "
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
            "Database failed validation after roads-and-water import:\n- "
            + "\n- ".join(errors)
        )
    return map_layers_info(database, release_keys=release_keys)


def map_layers_info(
    database: Path,
    release_key: str | None = None,
    *,
    release_keys: Sequence[str] | None = None,
) -> dict[str, object]:
    errors = validate_database(database)
    if errors:
        raise RuntimeError(
            "Database failed roads-and-water validation:\n- " + "\n- ".join(errors)
        )
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        parameters: tuple[object, ...]
        if release_key is not None:
            where = "sr.release_key = ?"
            parameters = (release_key,)
        elif release_keys is not None:
            placeholders = ",".join("?" for _ in release_keys)
            where = f"sr.release_key IN ({placeholders})"
            parameters = tuple(release_keys)
        else:
            where = "sr.lifecycle_status = 'accepted'"
            parameters = ()
        rows = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
            "sr.content_sha256 AS release_sha256, sr.feature_count, "
            "d.dataset_key, d.data_kind, sf.relative_path, sf.byte_length, "
            "sf.sha256 AS source_file_sha256, COUNT(f.source_map_feature_id) AS stored_count, "
            "MIN(f.min_x) AS min_x, MIN(f.min_y) AS min_y, "
            "MAX(f.max_x) AS max_x, MAX(f.max_y) AS max_y, "
            "MIN(f.created_at) AS created_at "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN source_map_feature f ON f.source_release_id = sr.source_release_id "
            "JOIN source_file sf ON sf.source_file_id = f.source_file_id "
            f"WHERE {where} AND d.data_kind IN ('roads','water') "
            "GROUP BY sr.source_release_id, sf.source_file_id "
            "ORDER BY d.dataset_key, sr.source_release_id",
            parameters,
        ).fetchall()
        if not rows:
            label = release_key or "requested accepted roads-and-water releases"
            raise RuntimeError(f"No stored map features found for {label}")
        layers: dict[str, object] = {}
        for row in rows:
            geometry_types = [
                item[0]
                for item in connection.execute(
                    "SELECT DISTINCT geometry_type FROM source_map_feature "
                    "WHERE source_release_id = ? ORDER BY geometry_type",
                    (row["source_release_id"],),
                )
            ]
            layers[row["dataset_key"]] = {
                "release": {
                    "release_key": row["release_key"],
                    "lifecycle_status": row["lifecycle_status"],
                    "content_sha256": row["release_sha256"],
                    "feature_count": row["feature_count"],
                    "dataset_key": row["dataset_key"],
                    "data_kind": row["data_kind"],
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
        return {"layers": layers}
    finally:
        connection.close()


def source_pairs(values: Sequence[str]) -> list[tuple[str, Path]]:
    if len(values) % 2:
        raise RuntimeError("Import requires RELEASE_KEY GEOJSON pairs")
    return [(values[index], Path(values[index + 1])) for index in range(0, len(values), 2)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate roads and water storage")
    validate.add_argument("database", type=Path)
    import_parser = subparsers.add_parser(
        "import", help="atomically import one or more RELEASE_KEY GEOJSON pairs"
    )
    import_parser.add_argument("database", type=Path)
    import_parser.add_argument("sources", nargs="+")
    info = subparsers.add_parser("info", help="report accepted or named map releases")
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
                "roads_and_water": import_map_layers(
                    args.database, source_pairs(args.sources)
                ),
            }
        else:
            result = {
                "valid": True,
                "path": str(args.database.resolve()),
                "roads_and_water": map_layers_info(args.database, args.release_key),
            }
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
