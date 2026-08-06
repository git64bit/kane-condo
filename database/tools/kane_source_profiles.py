#!/usr/bin/env python3
"""Load, validate, inspect, and hash Kane Condo source profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

PROFILE_DIR = Path(__file__).resolve().parent.parent / "source-profiles"
REGISTRY_SCHEMA = 1
PROFILE_SCHEMA = 1
DONOR_REPOSITORY = "https://github.com/git64bit/kane-offline-map"
DONOR_COMMIT = "0911eeefeafbb18c58af0618200ba9edead29bdc"
ARC_GIS_HOST = "services1.arcgis.com"
ARC_GIS_ACCOUNT = "oRKmdBXD6EbdmVgJ"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

PROFILE_FILENAMES = (
    "kane-county-boundary.json",
    "kane-county-buildings.json",
    "kane-county-creeks.json",
    "kane-county-fox-river.json",
    "kane-county-roads.json",
)
ALLOWED_DIRECTORY_ENTRIES = frozenset((*PROFILE_FILENAMES, "README.md"))

TOP_REQUIRED = frozenset(
    (
        "registry_profile_schema",
        "profile_key",
        "agency_key",
        "dataset_key",
        "donor",
        "source",
        "query",
        "geometry",
        "pagination",
        "validation",
        "copyright_text",
    )
)
TOP_OPTIONAL = frozenset(("expected_feature_count", "update_group"))
OBJECT_KEYS = {
    "donor": frozenset(("repository", "commit", "path", "file_sha256", "profile_schema")),
    "source": frozenset(("layer_url", "service_name", "layer_id")),
    "query": frozenset(
        ("where", "object_id_field", "identity_field", "out_srs", "page_size", "out_fields")
    ),
    "geometry": frozenset(
        (
            "arcgis_type",
            "geojson_types",
            "missing_geometry_policy",
            "missing_geometry_policy_origin",
        )
    ),
    "pagination": frozenset(
        (
            "mode",
            "inventory_query",
            "ordering",
            "respect_service_max_record_count",
            "offset_pagination",
            "require_exact_requested_ids",
        )
    ),
    "validation": frozenset(("identity", "schema", "geometry", "response")),
}

PAGINATION_CONTRACT = {
    "mode": "exact-object-id-groups",
    "inventory_query": "returnIdsOnly",
    "ordering": "ascending-numeric",
    "respect_service_max_record_count": True,
    "offset_pagination": False,
    "require_exact_requested_ids": True,
}
VALIDATION_CONTRACT = {
    "identity": "required-unique",
    "schema": "requested-fields-present",
    "geometry": "declared-types-only",
    "response": "geojson-feature-collection",
}


def _expected_profile(
    *,
    filename: str,
    profile_key: str,
    dataset_key: str,
    donor_path: str,
    donor_sha256: str,
    service_name: str,
    layer_id: int,
    identity_field: str,
    arcgis_type: str,
    geojson_types: list[str],
    missing_policy: str,
    missing_origin: str,
    out_fields: list[str],
    expected_feature_count: int | None = None,
    update_group: str | None = None,
) -> dict[str, Any]:
    layer_url = (
        f"https://{ARC_GIS_HOST}/{ARC_GIS_ACCOUNT}/ArcGIS/rest/services/"
        f"{service_name}/FeatureServer/{layer_id}"
    )
    profile: dict[str, Any] = {
        "registry_profile_schema": PROFILE_SCHEMA,
        "profile_key": profile_key,
        "agency_key": "kane-county-gis",
        "dataset_key": dataset_key,
        "donor": {
            "repository": DONOR_REPOSITORY,
            "commit": DONOR_COMMIT,
            "path": donor_path,
            "file_sha256": donor_sha256,
            "profile_schema": 1,
        },
        "source": {
            "layer_url": layer_url,
            "service_name": service_name,
            "layer_id": layer_id,
        },
        "query": {
            "where": "1=1",
            "object_id_field": "OBJECTID",
            "identity_field": identity_field,
            "out_srs": 4326,
            "page_size": 2000,
            "out_fields": out_fields,
        },
        "geometry": {
            "arcgis_type": arcgis_type,
            "geojson_types": geojson_types,
            "missing_geometry_policy": missing_policy,
            "missing_geometry_policy_origin": missing_origin,
        },
        "pagination": dict(PAGINATION_CONTRACT),
        "validation": dict(VALIDATION_CONTRACT),
        "copyright_text": "Kane County, GIS",
    }
    if expected_feature_count is not None:
        profile["expected_feature_count"] = expected_feature_count
    if update_group is not None:
        profile["update_group"] = update_group
    return profile


APPROVED_PROFILES: dict[str, dict[str, Any]] = {
    "kane-county-boundary.json": _expected_profile(
        filename="kane-county-boundary.json",
        profile_key="kane-county-boundary",
        dataset_key="county-boundary",
        donor_path="database/sources/kane-county-boundary.json",
        donor_sha256="c67ad4b470f4c9ba88dc42583d4a28c56c6bd5d7adeb0b2eebd9bb28430fac40",
        service_name="County_Boundary",
        layer_id=0,
        identity_field="OBJECTID",
        arcgis_type="esriGeometryPolygon",
        geojson_types=["Polygon", "MultiPolygon"],
        missing_policy="reject",
        missing_origin="donor-default",
        out_fields=["OBJECTID"],
        expected_feature_count=1,
    ),
    "kane-county-buildings.json": _expected_profile(
        filename="kane-county-buildings.json",
        profile_key="kane-county-building-footprints",
        dataset_key="buildings",
        donor_path="database/sources/kane-county-buildings.json",
        donor_sha256="f716a10f286998a0d0169126fbea2d7d7c063cc0007b4bc57bfa08c7be2896cf",
        service_name="KaneCo_IL_BuildingFootprints",
        layer_id=0,
        identity_field="FPId",
        arcgis_type="esriGeometryPolygon",
        geojson_types=["Polygon", "MultiPolygon"],
        missing_policy="reject",
        missing_origin="donor-default",
        out_fields=[
            "OBJECTID",
            "FPId",
            "CommonName",
            "Active",
            "FirstYear",
            "LastYear",
            "FrstFlrElev",
            "FFESource",
            "FloodZone",
            "SourceData",
            "Notes",
            "ESRICarto",
            "AddUser",
            "AddDate",
            "EditUser",
            "EditDate",
            "Shape__Area",
            "Shape__Length",
        ],
    ),
    "kane-county-roads.json": _expected_profile(
        filename="kane-county-roads.json",
        profile_key="kane-county-road-centerlines",
        dataset_key="roads",
        donor_path="database/sources/kane-county-roads.json",
        donor_sha256="f3c44d95a8557a4c281250f1a940574da3495fed2c42991ff7de13fa10bf2dca",
        service_name="KaneCo_IL_Centerlines_ROW",
        layer_id=1,
        identity_field="OBJECTID",
        arcgis_type="esriGeometryPolyline",
        geojson_types=["LineString", "MultiLineString"],
        missing_policy="exclude",
        missing_origin="donor-explicit",
        out_fields=["OBJECTID"],
    ),
    "kane-county-fox-river.json": _expected_profile(
        filename="kane-county-fox-river.json",
        profile_key="kane-county-fox-river",
        dataset_key="water-fox-river",
        donor_path="database/sources/kane-county-fox-river.json",
        donor_sha256="67116d45e041dce953588d1a330821a3b69b644731181e244583074cea694223",
        service_name="KaneCo_IL_FoxRiver",
        layer_id=1,
        identity_field="OBJECTID",
        arcgis_type="esriGeometryPolygon",
        geojson_types=["Polygon", "MultiPolygon"],
        missing_policy="reject",
        missing_origin="donor-default",
        out_fields=["OBJECTID"],
        update_group="water-context",
    ),
    "kane-county-creeks.json": _expected_profile(
        filename="kane-county-creeks.json",
        profile_key="kane-county-creeks",
        dataset_key="water-creeks",
        donor_path="database/sources/kane-county-creeks.json",
        donor_sha256="21c043a3c8c3319fb42c4038be5400bb9c28380730b62792e4f7c4e1cc3d8f1c",
        service_name="KaneCo_IL_Creeks",
        layer_id=1,
        identity_field="OBJECTID",
        arcgis_type="esriGeometryPolyline",
        geojson_types=["LineString", "MultiLineString"],
        missing_policy="reject",
        missing_origin="donor-default",
        out_fields=["OBJECTID"],
        update_group="water-context",
    ),
}


class DuplicateKeyError(ValueError):
    """Raised when JSON contains a duplicate object key."""


def _pairs_to_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _path_text(path: tuple[str | int, ...]) -> str:
    text = "profile"
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else f".{part}"
    return text


def _scan_value(value: Any, path: tuple[str | int, ...], errors: list[str]) -> None:
    label = _path_text(path)
    if value is None:
        errors.append(f"{label}: null is not permitted")
    elif isinstance(value, str):
        if not value:
            errors.append(f"{label}: empty strings are not permitted")
        elif value != value.strip():
            errors.append(f"{label}: leading or trailing whitespace is not permitted")
    elif isinstance(value, list):
        fingerprints: set[str] = set()
        for index, item in enumerate(value):
            fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if fingerprint in fingerprints:
                errors.append(f"{label}: duplicate array entry at index {index}")
            fingerprints.add(fingerprint)
            _scan_value(item, (*path, index), errors)
    elif isinstance(value, dict):
        for key, item in value.items():
            _scan_value(item, (*path, key), errors)


def _check_keys(
    value: Any,
    label: str,
    required: frozenset[str],
    optional: frozenset[str],
    errors: list[str],
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{label}: expected an object")
        return False
    keys = set(value)
    for key in sorted(required - keys):
        errors.append(f"{label}: missing required key {key!r}")
    for key in sorted(keys - required - optional):
        errors.append(f"{label}: unknown key {key!r}")
    return required <= keys and keys <= required | optional


def _compare_exact(actual: Any, expected: Any, label: str, errors: list[str]) -> None:
    if type(actual) is not type(expected):
        errors.append(
            f"{label}: expected {type(expected).__name__}, found {type(actual).__name__}"
        )
        return
    if actual != expected:
        errors.append(f"{label}: value does not match the approved profile manifest")


def _validate_endpoint(profile: dict[str, Any], filename: str, errors: list[str]) -> None:
    source = profile.get("source")
    if not isinstance(source, dict):
        return
    url = source.get("layer_url")
    service = source.get("service_name")
    layer_id = source.get("layer_id")
    if not isinstance(url, str):
        errors.append(f"{filename}: source.layer_url must be a string")
        return
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        errors.append(f"{filename}: invalid source.layer_url: {exc}")
        return
    if parsed.scheme != "https":
        errors.append(f"{filename}: source.layer_url must use HTTPS")
    if parsed.hostname != ARC_GIS_HOST:
        errors.append(f"{filename}: source.layer_url has an unapproved hostname")
    try:
        port = parsed.port
    except ValueError:
        port = -1
    if port is not None:
        errors.append(f"{filename}: source.layer_url must not declare a port")
    if parsed.username is not None or parsed.password is not None:
        errors.append(f"{filename}: source.layer_url must not contain credentials")
    if parsed.query or parsed.fragment:
        errors.append(f"{filename}: source.layer_url must not contain query or fragment data")
    if url.endswith("/"):
        errors.append(f"{filename}: source.layer_url must not end with a slash")
    if not isinstance(service, str):
        errors.append(f"{filename}: source.service_name must be a string")
        return
    if "%" in service or unquote(service) != service:
        errors.append(f"{filename}: source.service_name must not be percent encoded")
    if type(layer_id) is not int or layer_id < 0:
        errors.append(f"{filename}: source.layer_id must be a nonnegative integer")
        return
    expected_path = (
        f"/{ARC_GIS_ACCOUNT}/ArcGIS/rest/services/{service}/FeatureServer/{layer_id}"
    )
    reconstructed = f"https://{ARC_GIS_HOST}{expected_path}"
    if parsed.path != expected_path or reconstructed != url:
        errors.append(f"{filename}: source endpoint and service/layer declaration disagree")


def _parse_profile(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OSError(f"cannot read {path}: {exc}") from exc
    if not raw:
        return None, [f"{path.name}: empty profile file"]
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, [f"{path.name}: UTF-8 BOM is not permitted"]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [f"{path.name}: invalid UTF-8: {exc}"]
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_constant,
        )
    except (DuplicateKeyError, json.JSONDecodeError, ValueError) as exc:
        return None, [f"{path.name}: invalid JSON: {exc}"]
    if not isinstance(value, dict):
        return None, [f"{path.name}: top-level JSON value must be an object"]
    _scan_value(value, (), errors)
    return value, errors


def _validate_profile(profile: dict[str, Any], filename: str) -> list[str]:
    errors: list[str] = []
    complete = _check_keys(profile, filename, TOP_REQUIRED, TOP_OPTIONAL, errors)
    for name, keys in OBJECT_KEYS.items():
        if name in profile:
            _check_keys(profile[name], f"{filename}.{name}", keys, frozenset(), errors)
    _validate_endpoint(profile, filename, errors)

    query = profile.get("query")
    if isinstance(query, dict):
        out_fields = query.get("out_fields")
        if not isinstance(out_fields, list) or not out_fields:
            errors.append(f"{filename}: query.out_fields must be a nonempty array")
        elif any(not isinstance(field, str) for field in out_fields):
            errors.append(f"{filename}: query.out_fields entries must be strings")
        else:
            if "*" in out_fields:
                errors.append(f"{filename}: wildcard field requests are not permitted")
            if any("," in field for field in out_fields):
                errors.append(f"{filename}: comma-combined requested fields are not permitted")
            identity = query.get("identity_field")
            if isinstance(identity, str) and identity not in out_fields:
                errors.append(f"{filename}: identity_field is absent from out_fields")
            if "OBJECTID" not in out_fields:
                errors.append(f"{filename}: OBJECTID is absent from out_fields")
        for key, expected in (("out_srs", 4326), ("page_size", 2000)):
            value = query.get(key)
            if type(value) is not int:
                errors.append(f"{filename}: query.{key} must be an integer, not a Boolean")
            elif value != expected:
                errors.append(f"{filename}: query.{key} must equal {expected}")

    donor = profile.get("donor")
    if isinstance(donor, dict):
        digest = donor.get("file_sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            errors.append(f"{filename}: donor.file_sha256 must be lowercase SHA-256")

    if complete and filename in APPROVED_PROFILES:
        expected = APPROVED_PROFILES[filename]
        for key in sorted(expected):
            _compare_exact(profile.get(key), expected[key], f"{filename}.{key}", errors)
        for key in sorted(set(profile) - set(expected)):
            errors.append(f"{filename}: unapproved optional key {key!r}")
    return errors


def _directory_errors(directory: Path) -> tuple[list[str], list[Path]]:
    if not directory.is_dir():
        return [f"registry directory does not exist: {directory}"], []
    errors: list[str] = []
    profiles: list[Path] = []
    entries = sorted(directory.iterdir(), key=lambda item: item.name)
    names = {entry.name for entry in entries}
    for entry in entries:
        if entry.is_symlink():
            errors.append(f"registry directory contains a symlink: {entry.name}")
            continue
        if entry.is_dir():
            errors.append(f"registry directory contains a subdirectory: {entry.name}")
            continue
        if entry.name not in ALLOWED_DIRECTORY_ENTRIES:
            errors.append(f"registry directory contains an additional file: {entry.name}")
        elif entry.name.endswith(".json"):
            profiles.append(entry)
    for name in sorted(ALLOWED_DIRECTORY_ENTRIES - names):
        errors.append(f"registry directory is missing required file: {name}")
    return errors, profiles


def _cross_profile_errors(profiles: list[tuple[str, dict[str, Any]]]) -> list[str]:
    errors: list[str] = []
    if len(profiles) != 5:
        errors.append(f"registry must contain exactly five profiles; found {len(profiles)}")

    def values(getter: Callable[[dict[str, Any]], Any]) -> list[Any]:
        return [getter(profile) for _, profile in profiles]

    uniqueness = {
        "profile_key": values(lambda p: p.get("profile_key")),
        "dataset_key": values(lambda p: p.get("dataset_key")),
        "donor path": values(
            lambda p: p.get("donor", {}).get("path") if isinstance(p.get("donor"), dict) else None
        ),
    }
    for label, items in uniqueness.items():
        if len(items) != len(set(json.dumps(item, sort_keys=True) for item in items)):
            errors.append(f"registry contains duplicate {label} values")

    tuples: list[tuple[Any, ...]] = []
    for _, profile in profiles:
        source = profile.get("source")
        if isinstance(source, dict):
            tuples.append((ARC_GIS_HOST, ARC_GIS_ACCOUNT, source.get("service_name"), source.get("layer_id")))
    if len(tuples) != len(set(tuples)):
        errors.append("registry contains duplicate stable source-layer identifiers")

    groups = {
        profile.get("profile_key"): profile.get("update_group")
        for _, profile in profiles
        if "update_group" in profile
    }
    expected_groups = {
        "kane-county-creeks": "water-context",
        "kane-county-fox-river": "water-context",
    }
    if groups != expected_groups:
        errors.append("Fox River and creeks must be the only water-context update-group members")

    expected_counts = [profile for _, profile in profiles if "expected_feature_count" in profile]
    if len(expected_counts) != 1 or expected_counts[0].get("profile_key") != "kane-county-boundary":
        errors.append("exactly the county boundary must declare expected_feature_count")
    return errors


def canonical_registry_bytes(registry: dict[str, Any]) -> bytes:
    """Return the exact canonical byte representation used for registry identity."""
    text = json.dumps(
        registry,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def inspect_registry(directory: Path = PROFILE_DIR) -> dict[str, Any]:
    """Validate a source-profile directory and return deterministic inspection data."""
    directory = Path(directory)
    errors, paths = _directory_errors(directory)
    parsed: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(paths, key=lambda item: item.name):
        profile, parse_errors = _parse_profile(path)
        errors.extend(parse_errors)
        if profile is not None:
            errors.extend(_validate_profile(profile, path.name))
            parsed.append((path.name, profile))
    errors.extend(_cross_profile_errors(parsed))
    errors = sorted(set(errors))
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "profile_count": len(paths),
            "registry": None,
            "registry_sha256": None,
        }
    normalized_profiles = []
    for filename, profile in sorted(parsed, key=lambda item: item[1]["profile_key"]):
        normalized = dict(profile)
        normalized["registry_filename"] = filename
        normalized_profiles.append(normalized)
    registry = {"registry_schema": REGISTRY_SCHEMA, "profiles": normalized_profiles}
    digest = hashlib.sha256(canonical_registry_bytes(registry)).hexdigest()
    return {
        "valid": True,
        "errors": [],
        "profile_count": len(normalized_profiles),
        "registry": registry,
        "registry_sha256": digest,
    }


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))


def _command_validate(result: dict[str, Any]) -> int:
    _emit(
        {
            "errors": result["errors"],
            "profile_count": result["profile_count"],
            "registry_sha256": result["registry_sha256"],
            "valid": result["valid"],
        }
    )
    return 0 if result["valid"] else 1


def _command_hash(result: dict[str, Any]) -> int:
    if not result["valid"]:
        return _command_validate(result)
    _emit({"registry_sha256": result["registry_sha256"], "valid": True})
    return 0


def _command_info(result: dict[str, Any]) -> int:
    if not result["valid"]:
        return _command_validate(result)
    _emit(
        {
            "profile_count": result["profile_count"],
            "profiles": result["registry"]["profiles"],
            "registry_schema": result["registry"]["registry_schema"],
            "registry_sha256": result["registry_sha256"],
            "valid": True,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=PROFILE_DIR,
        help="source-profile directory (default: repository registry)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "info", "hash"):
        subparsers.add_parser(command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = inspect_registry(args.directory)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.command == "validate":
        return _command_validate(result)
    if args.command == "info":
        return _command_info(result)
    if args.command == "hash":
        return _command_hash(result)
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
