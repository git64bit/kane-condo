#!/usr/bin/env python3
"""Harvest, validate, and register a complete official-road candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
PROFILE_DIR = TOOLS_DIR.parent / "source-profiles"
PROFILE_KEY = "kane-county-road-centerlines"
CANDIDATE_SCHEMA = 1
REQUIRED_CANDIDATE_FILES = {
    "roads.geojson",
    "layer-metadata.json",
    "manifest.json",
    "object-ids.json",
    "excluded-object-ids.json",
}
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_PAGE_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT = 120.0
DEFAULT_ATTEMPTS = 3
USER_AGENT = "Kane-Condo-Road-Candidate/1"
Requester = Callable[..., Any]


class HarvestUnavailableError(RuntimeError):
    """Raised when an approved source request cannot complete reliably."""


class HarvestContractError(RuntimeError):
    """Raised when live or staged data violates the approved contract."""


def load_sibling(name: str):
    module_path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_kane_condo_{name}_candidate", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kane_source_profiles = load_sibling("kane_source_profiles")
kane_source_status = load_sibling("kane_source_status")
kane_geometry = load_sibling("kane_geometry")
kane_provenance = load_sibling("kane_provenance")
kane_map_layers = load_sibling("kane_map_layers")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _reject_constant(token: str) -> None:
    raise ValueError(f"invalid JSON constant {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_canonical_json(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Unable to read {path}: {exc}") from exc
    if not raw:
        raise RuntimeError(f"JSON file is empty: {path}")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"JSON file has a UTF-8 BOM: {path}")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Invalid UTF-8 JSON in {path}: {exc}") from exc
    try:
        expected = canonical_bytes(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"JSON is not canonicalizable in {path}: {exc}") from exc
    if raw != expected:
        raise RuntimeError(f"JSON file is not in canonical serialization: {path}")
    return value, raw


def load_road_profile() -> tuple[dict[str, Any], str]:
    result = kane_source_profiles.inspect_registry(PROFILE_DIR)
    if result.get("valid") is not True:
        errors = result.get("errors") or ["unknown registry validation failure"]
        raise RuntimeError("Source-profile registry is invalid: " + "; ".join(errors))
    registry = result["registry"]
    matches = [
        dict(profile)
        for profile in registry["profiles"]
        if profile["profile_key"] == PROFILE_KEY
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Registry must contain exactly one {PROFILE_KEY!r} profile")
    return matches[0], str(result["registry_sha256"])


def _response_url_matches(actual: str, expected: str) -> bool:
    actual_parts = urllib.parse.urlsplit(actual)
    expected_parts = urllib.parse.urlsplit(expected)
    return (
        actual_parts.scheme == expected_parts.scheme
        and actual_parts.netloc == expected_parts.netloc
        and actual_parts.path == expected_parts.path
        and actual_parts.query == expected_parts.query
        and not actual_parts.fragment
    )


def _decode_response(response: Any, expected_url: str, byte_limit: int) -> Any:
    final_url = response.geturl()
    if not _response_url_matches(final_url, expected_url):
        raise HarvestContractError(f"Endpoint redirected unexpectedly to {final_url}")
    content_type = response.headers.get_content_type()
    if content_type not in {
        "application/json",
        "application/geo+json",
        "text/json",
        "text/plain",
    }:
        raise HarvestContractError(f"Unexpected response content type: {content_type}")
    raw = response.read(byte_limit + 1)
    if len(raw) > byte_limit:
        raise HarvestContractError(f"Response exceeds {byte_limit} bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HarvestContractError(f"Response is not valid UTF-8 JSON: {exc}") from exc
    if isinstance(value, Mapping) and "error" in value:
        raise HarvestContractError("ArcGIS returned an error object")
    return value


def http_request_json(
    url: str,
    params: Mapping[str, str],
    *,
    timeout_seconds: float,
    byte_limit: int,
    post: bool,
    attempts: int = DEFAULT_ATTEMPTS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    if timeout_seconds <= 0:
        raise RuntimeError("timeout_seconds must be positive")
    if attempts < 1:
        raise RuntimeError("attempts must be positive")
    encoded = urllib.parse.urlencode(dict(params)).encode("ascii")
    request_url = url
    data: bytes | None = None
    method = "GET"
    if post:
        data = encoded
        method = "POST"
    else:
        request_url += ("&" if "?" in url else "?") + encoded.decode("ascii")
    request = urllib.request.Request(
        request_url,
        data=data,
        headers={
            "Accept": "application/json, application/geo+json",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
        method=method,
    )
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout_seconds) as response:
                return _decode_response(response, request_url if not post else url, byte_limit)
        except HarvestContractError:
            raise
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code not in {408, 429}:
                raise HarvestUnavailableError(
                    f"ArcGIS HTTP error {exc.code}: {exc.reason}"
                ) from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(float(attempt))
    raise HarvestUnavailableError(str(last_error or "source request failed"))


def _request(
    requester: Requester,
    url: str,
    params: Mapping[str, str],
    *,
    timeout_seconds: float,
    byte_limit: int,
    post: bool,
) -> Any:
    return requester(
        url,
        params,
        timeout_seconds=timeout_seconds,
        byte_limit=byte_limit,
        post=post,
    )


def validate_harvest_metadata(
    profile: Mapping[str, Any], metadata: Any
) -> dict[str, Any]:
    summary = kane_source_status.validate_layer_metadata(profile, metadata)
    assert isinstance(metadata, Mapping)
    if metadata.get("type") != "Feature Layer":
        raise HarvestContractError("ArcGIS resource is not a Feature Layer")
    formats = metadata.get("supportedQueryFormats")
    if isinstance(formats, str):
        supported = {item.strip().lower() for item in formats.split(",") if item.strip()}
    elif isinstance(formats, list):
        supported = {str(item).strip().lower() for item in formats if str(item).strip()}
    else:
        supported = set()
    if "geojson" not in supported:
        raise HarvestContractError("Layer does not advertise GeoJSON query support")
    max_records = summary.get("max_record_count")
    if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1:
        raise HarvestContractError("Layer maxRecordCount is missing or invalid")
    return summary


def normalize_inventory(profile: Mapping[str, Any], payload: Any) -> list[int]:
    if not isinstance(payload, Mapping):
        raise HarvestContractError("Object-ID response must be a JSON object")
    field = payload.get("objectIdFieldName")
    expected = profile["query"]["object_id_field"]
    if field != expected:
        raise HarvestContractError(
            f"Object-ID response field changed from {expected!r} to {field!r}"
        )
    try:
        object_ids = kane_source_status.normalize_object_ids(payload.get("objectIds"), "objectIds")
    except Exception as exc:
        raise HarvestContractError(str(exc)) from exc
    if not object_ids:
        raise HarvestContractError("Object-ID inventory is empty")
    return object_ids


def _stable_text(value: Any, field: str) -> str:
    if value is None or isinstance(value, bool):
        raise HarvestContractError(f"Feature is missing stable {field}")
    text = str(value).strip()
    if not text:
        raise HarvestContractError(f"Feature is missing stable {field}")
    return text


def _object_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarvestContractError(f"Feature has invalid {field}: {value!r}")
    return value


def normalize_feature_page(
    profile: Mapping[str, Any],
    payload: Any,
    expected_ids: Sequence[int],
    seen_stable_ids: set[str],
) -> tuple[list[dict[str, Any]], list[list[Any]], list[int]]:
    if not isinstance(payload, Mapping):
        raise HarvestContractError("Feature response must be a JSON object")
    if payload.get("type") != "FeatureCollection" or not isinstance(
        payload.get("features"), list
    ):
        raise HarvestContractError("Feature query did not return a GeoJSON FeatureCollection")
    if payload.get("exceededTransferLimit") is True:
        raise HarvestContractError("Feature query exceeded the transfer limit")
    query = profile["query"]
    object_field = query["object_id_field"]
    identity_field = query["identity_field"]
    requested_fields = list(query["out_fields"])
    allowed_geometry = tuple(profile["geometry"]["geojson_types"])
    missing_policy = profile["geometry"]["missing_geometry_policy"]
    if missing_policy != "exclude":
        raise HarvestContractError("Road profile must explicitly exclude missing geometry")
    by_object: dict[int, tuple[dict[str, Any] | None, str]] = {}
    for index, feature in enumerate(payload["features"]):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise HarvestContractError(f"Feature response item {index} is not a Feature")
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            raise HarvestContractError(f"Feature response item {index} has invalid properties")
        missing = [field for field in requested_fields if field not in properties]
        if missing:
            raise HarvestContractError(
                f"Feature response item {index} is missing requested fields: {', '.join(missing)}"
            )
        current_object_id = _object_id(properties.get(object_field), object_field)
        if current_object_id in by_object:
            raise HarvestContractError(
                f"Feature page contains duplicate object ID {current_object_id}"
            )
        stable_id = _stable_text(properties.get(identity_field), identity_field)
        if stable_id in seen_stable_ids:
            raise HarvestContractError(f"Harvest contains duplicate stable ID {stable_id}")
        normalized_feature: dict[str, Any] | None
        geometry = feature.get("geometry")
        if geometry is None:
            normalized_feature = None
        else:
            try:
                geometry_type, coordinates = kane_geometry.normalize_linear_geometry(geometry)
            except RuntimeError as exc:
                raise HarvestContractError(
                    f"Feature {stable_id} has invalid geometry: {exc}"
                ) from exc
            if geometry_type not in allowed_geometry:
                raise HarvestContractError(
                    f"Feature {stable_id} has unsupported geometry type {geometry_type!r}"
                )
            normalized_properties = {field: properties[field] for field in requested_fields}
            normalized_properties[object_field] = current_object_id
            normalized_properties[identity_field] = current_object_id
            normalized_feature = {
                "type": "Feature",
                "id": stable_id,
                "properties": normalized_properties,
                "geometry": {
                    "type": geometry_type,
                    "coordinates": json.loads(canonical_bytes(coordinates)),
                },
            }
            try:
                canonical_bytes(normalized_feature)
            except (TypeError, ValueError) as exc:
                raise HarvestContractError(
                    f"Feature {stable_id} contains unsupported JSON values: {exc}"
                ) from exc
        by_object[current_object_id] = (normalized_feature, stable_id)
        seen_stable_ids.add(stable_id)
    expected_set = set(expected_ids)
    actual_set = set(by_object)
    if expected_set != actual_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        raise HarvestContractError(
            f"Feature page object-ID mismatch; missing={missing}, extra={extra}"
        )
    features: list[dict[str, Any]] = []
    identity_pairs: list[list[Any]] = []
    excluded_ids: list[int] = []
    for object_id in expected_ids:
        feature, stable_id = by_object[object_id]
        identity_pairs.append([object_id, stable_id])
        if feature is None:
            excluded_ids.append(object_id)
        else:
            features.append(feature)
    return features, identity_pairs, excluded_ids

def _source_published_at(metadata_summary: Mapping[str, Any]) -> str | None:
    value = metadata_summary.get("comparison_edit_ms")
    if value is None:
        return None
    moment = dt.datetime.fromtimestamp(int(value) / 1000.0, tz=dt.timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _date_token(source_published_at: str | None) -> str:
    if source_published_at is None:
        return "undated"
    return source_published_at[:10].replace("-", "")


def _candidate_keys(source_published_at: str | None, content_sha256: str) -> tuple[str, str]:
    token = _date_token(source_published_at)
    suffix = content_sha256[:12]
    return (
        f"kane-roads-candidate-{token}-{suffix}",
        f"kane-roads-harvest-{token}-{suffix}",
    )


def _write_file(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "byte_length": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _candidate_result(candidate_dir: Path, manifest: Mapping[str, Any], *, existing: bool) -> dict[str, Any]:
    return {
        "valid": True,
        "existing": existing,
        "candidate_directory": str(candidate_dir.resolve()),
        "release_key": manifest["registration"]["release_key"],
        "harvest_key": manifest["registration"]["harvest_key"],
        "feature_count": manifest["output"]["feature_count"],
        "object_count": manifest["inventory"]["object_count"],
        "stable_id_count": manifest["output"]["stable_id_count"],
        "excluded_count": manifest["exclusions"]["excluded_count"],
        "content_sha256": manifest["output"]["sha256"],
        "manifest_sha256": sha256_file(candidate_dir / "manifest.json"),
        "source_published_at": manifest["source"]["published_at"],
    }

def harvest_candidate(
    staging_root: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    requester: Requester = http_request_json,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise RuntimeError("timeout_seconds must be positive")
    profile, registry_sha256 = load_road_profile()
    if profile["geometry"]["missing_geometry_policy"] != "exclude":
        raise RuntimeError("Approved road profile must exclude missing geometry")
    started_at = started_at or utc_now()
    layer_url = profile["source"]["layer_url"]
    metadata = _request(
        requester,
        layer_url,
        {"f": "pjson"},
        timeout_seconds=timeout_seconds,
        byte_limit=MAX_METADATA_BYTES,
        post=False,
    )
    metadata_summary = validate_harvest_metadata(profile, metadata)
    query_url = layer_url + "/query"
    inventory_payload = _request(
        requester,
        query_url,
        {"where": profile["query"]["where"], "returnIdsOnly": "true", "f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=MAX_INVENTORY_BYTES,
        post=True,
    )
    object_ids = normalize_inventory(profile, inventory_payload)
    page_size = min(profile["query"]["page_size"], metadata_summary["max_record_count"])
    features: list[dict[str, Any]] = []
    identity_pairs: list[list[Any]] = []
    excluded_ids: list[int] = []
    seen_stable_ids: set[str] = set()
    page_count = 0
    for start in range(0, len(object_ids), page_size):
        page_ids = object_ids[start : start + page_size]
        page_count += 1
        page = _request(
            requester,
            query_url,
            {
                "objectIds": ",".join(str(value) for value in page_ids),
                "outFields": ",".join(profile["query"]["out_fields"]),
                "returnGeometry": "true",
                "returnZ": "false",
                "returnM": "false",
                "outSR": str(profile["query"]["out_srs"]),
                "f": "geojson",
            },
            timeout_seconds=timeout_seconds,
            byte_limit=MAX_PAGE_BYTES,
            post=True,
        )
        normalized_features, normalized_pairs, page_exclusions = normalize_feature_page(
            profile, page, page_ids, seen_stable_ids
        )
        features.extend(normalized_features)
        identity_pairs.extend(normalized_pairs)
        excluded_ids.extend(page_exclusions)
    if len(features) + len(excluded_ids) != len(object_ids):
        raise HarvestContractError("Road harvest completeness validation failed")
    if len(seen_stable_ids) != len(object_ids):
        raise HarvestContractError("Road stable-identity completeness validation failed")
    if sorted(excluded_ids) != excluded_ids or len(set(excluded_ids)) != len(excluded_ids):
        raise HarvestContractError("Road exclusion inventory is not deterministic")
    final_metadata = _request(
        requester,
        layer_url,
        {"f": "pjson"},
        timeout_seconds=timeout_seconds,
        byte_limit=MAX_METADATA_BYTES,
        post=False,
    )
    final_metadata_summary = validate_harvest_metadata(profile, final_metadata)
    if final_metadata_summary != metadata_summary:
        raise HarvestContractError("Layer metadata changed during the road harvest")
    final_inventory_payload = _request(
        requester,
        query_url,
        {"where": profile["query"]["where"], "returnIdsOnly": "true", "f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=MAX_INVENTORY_BYTES,
        post=True,
    )
    final_object_ids = normalize_inventory(profile, final_inventory_payload)
    if final_object_ids != object_ids:
        raise HarvestContractError("Object-ID inventory changed during the road harvest")
    completed_at = completed_at or utc_now()
    if completed_at < started_at:
        raise RuntimeError("Candidate manifest harvest completed_at precedes started_at")
    source_published_at = _source_published_at(metadata_summary)
    collection = {
        "type": "FeatureCollection",
        "name": PROFILE_KEY,
        "source": {
            "profile_key": PROFILE_KEY,
            "dataset_key": profile["dataset_key"],
            "layer_url": layer_url,
            "identity_field": profile["query"]["identity_field"],
            "object_id_field": profile["query"]["object_id_field"],
            "out_srs": profile["query"]["out_srs"],
            "published_at": source_published_at,
            "missing_geometry_policy": profile["geometry"]["missing_geometry_policy"],
            "copyright_text": profile["copyright_text"],
        },
        "features": features,
    }
    output_data = canonical_bytes(collection)
    metadata_data = canonical_bytes(metadata)
    inventory_data = canonical_bytes(object_ids)
    exclusions_data = canonical_bytes(excluded_ids)
    content_sha256 = sha256_bytes(output_data)
    release_key, harvest_key = _candidate_keys(source_published_at, content_sha256)
    staging_root = staging_root.resolve()
    roads_root = staging_root / "roads"
    roads_root.mkdir(parents=True, exist_ok=True)
    if roads_root.is_symlink():
        raise RuntimeError(f"Road staging directory must not be a symlink: {roads_root}")
    final_dir = roads_root / release_key
    if final_dir.exists():
        validated = validate_candidate(final_dir)
        if validated["content_sha256"] != content_sha256:
            raise RuntimeError(f"Existing candidate conflicts with harvested content: {final_dir}")
        return _candidate_result(final_dir, validated["manifest"], existing=True)
    temporary: Path | None = Path(
        tempfile.mkdtemp(prefix=".road-candidate-", dir=roads_root)
    )
    try:
        _write_file(temporary / "roads.geojson", output_data)
        _write_file(temporary / "layer-metadata.json", metadata_data)
        _write_file(temporary / "object-ids.json", inventory_data)
        _write_file(temporary / "excluded-object-ids.json", exclusions_data)
        files = {
            "source": _file_record(temporary / "roads.geojson"),
            "metadata": _file_record(temporary / "layer-metadata.json"),
            "inventory": _file_record(temporary / "object-ids.json"),
            "exclusions": _file_record(temporary / "excluded-object-ids.json"),
        }
        manifest = {
            "candidate_manifest_schema": CANDIDATE_SCHEMA,
            "candidate_kind": "official-roads",
            "profile": {
                "profile_key": PROFILE_KEY,
                "registry_filename": profile["registry_filename"],
                "registry_sha256": registry_sha256,
                "donor_commit": profile["donor"]["commit"],
            },
            "source": {
                "layer_url": layer_url,
                "service_name": profile["source"]["service_name"],
                "layer_id": profile["source"]["layer_id"],
                "published_at": source_published_at,
                "metadata_summary": metadata_summary,
            },
            "harvest": {
                "started_at": started_at,
                "completed_at": completed_at,
                "page_size": page_size,
                "page_count": page_count,
                "end_metadata_verified": True,
                "end_inventory_verified": True,
            },
            "inventory": {
                **files["inventory"],
                "object_count": len(object_ids),
                "object_ids_sha256": kane_source_status.object_id_sha256(object_ids),
            },
            "exclusions": {
                **files["exclusions"],
                "excluded_count": len(excluded_ids),
                "excluded_object_ids_sha256": kane_source_status.object_id_sha256(excluded_ids),
                "policy": "exclude",
            },
            "output": {
                **files["source"],
                "feature_count": len(features),
                "stable_id_count": len(seen_stable_ids),
                "identity_map_sha256": sha256_bytes(canonical_bytes(identity_pairs)),
            },
            "metadata_file": files["metadata"],
            "registration": {
                "release_key": release_key,
                "harvest_key": harvest_key,
                "lifecycle_status": "candidate",
            },
        }
        _write_file(temporary / "manifest.json", canonical_bytes(manifest))
        validate_candidate(temporary, require_final_layout=False)
        os.replace(temporary, final_dir)
        temporary = None
        return _candidate_result(final_dir, manifest, existing=False)
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)

def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _validate_candidate_files(candidate_dir: Path) -> None:
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise RuntimeError(f"Candidate directory is missing or is a symlink: {candidate_dir}")
    names: set[str] = set()
    for path in candidate_dir.iterdir():
        if path.is_symlink():
            raise RuntimeError(f"Candidate contains a symlink: {path.name}")
        if not path.is_file():
            raise RuntimeError(f"Candidate contains a non-file entry: {path.name}")
        names.add(path.name)
    if names != REQUIRED_CANDIDATE_FILES:
        missing = sorted(REQUIRED_CANDIDATE_FILES - names)
        extra = sorted(names - REQUIRED_CANDIDATE_FILES)
        raise RuntimeError(f"Candidate file set mismatch; missing={missing}, extra={extra}")


def validate_candidate(
    candidate_dir: Path, *, require_final_layout: bool = True
) -> dict[str, Any]:
    candidate_dir = candidate_dir.absolute()
    if candidate_dir.is_symlink():
        raise RuntimeError(f"Candidate directory must not be a symlink: {candidate_dir}")
    candidate_dir = candidate_dir.resolve()
    _validate_candidate_files(candidate_dir)
    profile, registry_sha256 = load_road_profile()
    if profile["geometry"]["missing_geometry_policy"] != "exclude":
        raise RuntimeError("Approved road profile must exclude missing geometry")
    metadata, metadata_raw = load_canonical_json(candidate_dir / "layer-metadata.json")
    metadata_summary = validate_harvest_metadata(profile, metadata)
    inventory, inventory_raw = load_canonical_json(candidate_dir / "object-ids.json")
    try:
        object_ids = kane_source_status.normalize_object_ids(inventory, "object IDs")
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if not object_ids or object_ids != inventory:
        raise RuntimeError("Candidate object-ID inventory must be nonempty and ascending")
    exclusions, exclusions_raw = load_canonical_json(candidate_dir / "excluded-object-ids.json")
    try:
        excluded_ids = kane_source_status.normalize_object_ids(exclusions, "excluded object IDs")
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    if excluded_ids != exclusions:
        raise RuntimeError("Candidate exclusion inventory must be ascending")
    object_set = set(object_ids)
    if any(value not in object_set for value in excluded_ids):
        raise RuntimeError("Candidate exclusion inventory contains unknown object IDs")
    excluded_set = set(excluded_ids)
    retained_ids = [value for value in object_ids if value not in excluded_set]
    collection, source_raw = load_canonical_json(candidate_dir / "roads.geojson")
    collection = _require_mapping(collection, "Road candidate")
    if set(collection) != {"type", "name", "source", "features"}:
        raise RuntimeError("Road candidate has an unexpected key set")
    if collection.get("type") != "FeatureCollection" or collection.get("name") != PROFILE_KEY:
        raise RuntimeError("Road candidate has an invalid FeatureCollection identity")
    source = _require_mapping(collection.get("source"), "Road candidate source")
    expected_source = {
        "profile_key": PROFILE_KEY,
        "dataset_key": profile["dataset_key"],
        "layer_url": profile["source"]["layer_url"],
        "identity_field": profile["query"]["identity_field"],
        "object_id_field": profile["query"]["object_id_field"],
        "out_srs": profile["query"]["out_srs"],
        "published_at": _source_published_at(metadata_summary),
        "missing_geometry_policy": "exclude",
        "copyright_text": profile["copyright_text"],
    }
    if dict(source) != expected_source:
        raise RuntimeError("Road candidate source summary does not match metadata and profile")
    features = collection.get("features")
    if not isinstance(features, list) or len(features) != len(retained_ids):
        raise RuntimeError("Road candidate feature count does not match retained inventory")
    seen_stable: set[str] = set()
    identity_pairs: list[list[Any]] = []
    for index, (feature, expected_object_id) in enumerate(zip(features, retained_ids)):
        normalized_features, pairs, normalized_exclusions = normalize_feature_page(
            profile,
            {"type": "FeatureCollection", "features": [feature]},
            [expected_object_id],
            seen_stable,
        )
        if normalized_exclusions or normalized_features[0] != feature:
            raise RuntimeError(f"Road candidate feature {index} is not normalized")
        identity_pairs.extend(pairs)
    for excluded_id in excluded_ids:
        stable_id = str(excluded_id)
        if stable_id in seen_stable:
            raise RuntimeError(f"Road candidate duplicate stable identity {stable_id}")
        seen_stable.add(stable_id)
        identity_pairs.append([excluded_id, stable_id])
    identity_pairs.sort(key=lambda item: item[0])
    manifest, manifest_raw = load_canonical_json(candidate_dir / "manifest.json")
    manifest = _require_mapping(manifest, "Candidate manifest")
    required_manifest_keys = {
        "candidate_manifest_schema",
        "candidate_kind",
        "profile",
        "source",
        "harvest",
        "inventory",
        "exclusions",
        "output",
        "metadata_file",
        "registration",
    }
    if set(manifest) != required_manifest_keys:
        raise RuntimeError("Candidate manifest has an unexpected key set")
    if manifest.get("candidate_manifest_schema") != CANDIDATE_SCHEMA:
        raise RuntimeError(f"candidate_manifest_schema must be {CANDIDATE_SCHEMA}")
    if manifest.get("candidate_kind") != "official-roads":
        raise RuntimeError("candidate_kind must be official-roads")
    expected_profile = {
        "profile_key": PROFILE_KEY,
        "registry_filename": profile["registry_filename"],
        "registry_sha256": registry_sha256,
        "donor_commit": profile["donor"]["commit"],
    }
    if dict(_require_mapping(manifest.get("profile"), "manifest.profile")) != expected_profile:
        raise RuntimeError("Candidate manifest profile identity is invalid")
    source_manifest = _require_mapping(manifest.get("source"), "manifest.source")
    expected_source_manifest = {
        "layer_url": profile["source"]["layer_url"],
        "service_name": profile["source"]["service_name"],
        "layer_id": profile["source"]["layer_id"],
        "published_at": expected_source["published_at"],
        "metadata_summary": metadata_summary,
    }
    if dict(source_manifest) != expected_source_manifest:
        raise RuntimeError("Candidate manifest source identity is invalid")
    expected_metadata_file = {
        "path": "layer-metadata.json",
        "byte_length": len(metadata_raw),
        "sha256": sha256_bytes(metadata_raw),
    }
    if dict(_require_mapping(manifest.get("metadata_file"), "manifest.metadata_file")) != expected_metadata_file:
        raise RuntimeError("Candidate manifest metadata file identity is invalid")
    expected_inventory = {
        "path": "object-ids.json",
        "byte_length": len(inventory_raw),
        "sha256": sha256_bytes(inventory_raw),
        "object_count": len(object_ids),
        "object_ids_sha256": kane_source_status.object_id_sha256(object_ids),
    }
    if dict(_require_mapping(manifest.get("inventory"), "manifest.inventory")) != expected_inventory:
        raise RuntimeError("Candidate manifest inventory identity is invalid")
    expected_exclusions = {
        "path": "excluded-object-ids.json",
        "byte_length": len(exclusions_raw),
        "sha256": sha256_bytes(exclusions_raw),
        "excluded_count": len(excluded_ids),
        "excluded_object_ids_sha256": kane_source_status.object_id_sha256(excluded_ids),
        "policy": "exclude",
    }
    if dict(_require_mapping(manifest.get("exclusions"), "manifest.exclusions")) != expected_exclusions:
        raise RuntimeError("Candidate manifest exclusion identity is invalid")
    expected_output = {
        "path": "roads.geojson",
        "byte_length": len(source_raw),
        "sha256": sha256_bytes(source_raw),
        "feature_count": len(features),
        "stable_id_count": len(seen_stable),
        "identity_map_sha256": sha256_bytes(canonical_bytes(identity_pairs)),
    }
    if dict(_require_mapping(manifest.get("output"), "manifest.output")) != expected_output:
        raise RuntimeError("Candidate manifest output identity is invalid")
    if len(features) + len(excluded_ids) != len(object_ids):
        raise RuntimeError("Candidate retained and excluded counts do not cover object inventory")
    harvest = _require_mapping(manifest.get("harvest"), "manifest.harvest")
    if set(harvest) != {
        "started_at",
        "completed_at",
        "page_size",
        "page_count",
        "end_metadata_verified",
        "end_inventory_verified",
    }:
        raise RuntimeError("Candidate manifest harvest key set is invalid")
    if harvest["end_metadata_verified"] is not True:
        raise RuntimeError("Candidate manifest must confirm end metadata verification")
    if harvest["end_inventory_verified"] is not True:
        raise RuntimeError("Candidate manifest must confirm end inventory verification")
    for field in ("started_at", "completed_at"):
        if not kane_provenance.valid_datetime(harvest.get(field)):
            raise RuntimeError(f"Candidate manifest harvest.{field} is invalid")
    if harvest["completed_at"] < harvest["started_at"]:
        raise RuntimeError("Candidate manifest harvest completed_at precedes started_at")
    expected_page_size = min(profile["query"]["page_size"], metadata_summary["max_record_count"])
    expected_page_count = (len(object_ids) + expected_page_size - 1) // expected_page_size
    if harvest.get("page_size") != expected_page_size or harvest.get("page_count") != expected_page_count:
        raise RuntimeError("Candidate manifest pagination summary is invalid")
    release_key, harvest_key = _candidate_keys(
        expected_source["published_at"], expected_output["sha256"]
    )
    expected_registration = {
        "release_key": release_key,
        "harvest_key": harvest_key,
        "lifecycle_status": "candidate",
    }
    if dict(_require_mapping(manifest.get("registration"), "manifest.registration")) != expected_registration:
        raise RuntimeError("Candidate manifest registration identity is invalid")
    if require_final_layout and (
        candidate_dir.name != release_key or candidate_dir.parent.name != "roads"
    ):
        raise RuntimeError("Candidate directory must be roads/RELEASE_KEY")
    return {
        "valid": True,
        "candidate_directory": str(candidate_dir),
        "release_key": release_key,
        "harvest_key": harvest_key,
        "feature_count": len(features),
        "object_count": len(object_ids),
        "stable_id_count": len(seen_stable),
        "excluded_count": len(excluded_ids),
        "content_sha256": expected_output["sha256"],
        "manifest_sha256": sha256_bytes(manifest_raw),
        "source_published_at": expected_source["published_at"],
        "manifest": dict(manifest),
    }

def _database_context(database: Path, profile: Mapping[str, Any]) -> dict[str, Any]:
    errors = kane_map_layers.validate_database(database)
    if errors:
        raise RuntimeError("Database validation failed before road candidate registration:\n- " + "\n- ".join(errors))
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count, "
            "d.dataset_key, d.name AS dataset_name, d.description, d.data_kind, d.source_uri, "
            "c.county_key, c.name AS county_name, c.state_code, c.country_code, c.fips_code, "
            "a.agency_key, a.name AS agency_name, a.jurisdiction, a.homepage_uri "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "JOIN county c ON c.county_id = d.county_id "
            "JOIN source_agency a ON a.source_agency_id = d.source_agency_id "
            "WHERE d.dataset_key = 'roads' AND sr.lifecycle_status = 'accepted'"
        ).fetchall()
        if len(rows) != 1:
            raise RuntimeError(f"Roads must have exactly one accepted release, found {len(rows)}")
        row = rows[0]
        if row["agency_key"] != profile["agency_key"]:
            raise RuntimeError("Accepted road agency does not match the approved profile")
        if row["data_kind"] != "roads":
            raise RuntimeError("Accepted road dataset has an invalid data kind")
        if row["source_uri"] != profile["source"]["layer_url"]:
            raise RuntimeError("Accepted road source URI does not match the approved endpoint")
        return dict(row)
    finally:
        connection.close()

def _existing_candidate(database: Path, release_key: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT sr.release_key, sr.lifecycle_status, sr.content_sha256, sr.feature_count, "
            "h.harvest_key, h.object_count "
            "FROM source_release sr JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
            "WHERE sr.release_key = ?",
            (release_key,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def _descriptor(
    candidate_dir: Path,
    validated: Mapping[str, Any],
    context: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = validated["manifest"]
    files = []
    roles = {
        "roads.geojson": ("source", "application/geo+json"),
        "excluded-object-ids.json": ("exclusions", "application/json"),
        "layer-metadata.json": ("metadata", "application/json"),
        "object-ids.json": ("inventory", "application/json"),
        "manifest.json": ("manifest", "application/json"),
    }
    for name in sorted(roles):
        role, media_type = roles[name]
        path = candidate_dir / name
        files.append(
            {
                "file_role": role,
                "relative_path": f"roads/{validated['release_key']}/{name}",
                "byte_length": path.stat().st_size,
                "sha256": sha256_file(path),
                "media_type": media_type,
            }
        )
    return {
        "county": {
            "county_key": context["county_key"],
            "name": context["county_name"],
            "state_code": context["state_code"],
            "country_code": context["country_code"],
            "fips_code": context["fips_code"],
        },
        "agency": {
            "agency_key": context["agency_key"],
            "name": context["agency_name"],
            "jurisdiction": context["jurisdiction"],
            "homepage_uri": context["homepage_uri"],
        },
        "dataset": {
            "dataset_key": context["dataset_key"],
            "name": context["dataset_name"],
            "description": context["description"],
            "data_kind": context["data_kind"],
            "source_uri": context["source_uri"],
        },
        "harvest": {
            "harvest_key": validated["harvest_key"],
            "started_at": manifest["harvest"]["started_at"],
            "completed_at": manifest["harvest"]["completed_at"],
            "status": "succeeded",
            "source_metadata": {
                "profile_key": PROFILE_KEY,
                "registry_sha256": manifest["profile"]["registry_sha256"],
                "id_property": profile["query"]["identity_field"],
                "object_id_field": profile["query"]["object_id_field"],
                "object_ids_sha256": manifest["inventory"]["object_ids_sha256"],
                "identity_map_sha256": manifest["output"]["identity_map_sha256"],
                "excluded_count": manifest["exclusions"]["excluded_count"],
                "excluded_object_ids_sha256": manifest["exclusions"]["excluded_object_ids_sha256"],
                "manifest_sha256": validated["manifest_sha256"],
            },
            "object_count": validated["object_count"],
        },
        "files": files,
        "release": {
            "release_key": validated["release_key"],
            "lifecycle_status": "candidate",
            "source_published_at": validated["source_published_at"],
            "content_sha256": validated["content_sha256"],
            "feature_count": validated["feature_count"],
            "metadata": {
                "profile_key": PROFILE_KEY,
                "registry_sha256": manifest["profile"]["registry_sha256"],
                "id_property": profile["query"]["identity_field"],
                "object_id_field": profile["query"]["object_id_field"],
                "candidate_manifest_sha256": validated["manifest_sha256"],
                "excluded_count": manifest["exclusions"]["excluded_count"],
                "excluded_object_ids_sha256": manifest["exclusions"]["excluded_object_ids_sha256"],
            },
            "accepted_at": None,
        },
    }


PROTECTED_TABLES = (
    "source_map_feature",
    "project_building",
    "project_building_source_mapping",
    "building_classification_current",
    "building_classification_event",
)


def _protected_counts(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    try:
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in PROTECTED_TABLES
        }
    finally:
        connection.close()


def _assert_registered_candidate(
    trace: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> None:
    expected_release = {
        "release_key": descriptor["release"]["release_key"],
        "lifecycle_status": descriptor["release"]["lifecycle_status"],
        "source_published_at": descriptor["release"]["source_published_at"],
        "content_sha256": descriptor["release"]["content_sha256"],
        "feature_count": descriptor["release"]["feature_count"],
        "metadata": descriptor["release"]["metadata"],
        "accepted_at": descriptor["release"]["accepted_at"],
    }
    actual_release = {key: trace["release"][key] for key in expected_release}
    expected_harvest = {
        "harvest_key": descriptor["harvest"]["harvest_key"],
        "started_at": descriptor["harvest"]["started_at"],
        "completed_at": descriptor["harvest"]["completed_at"],
        "status": descriptor["harvest"]["status"],
        "source_metadata": descriptor["harvest"]["source_metadata"],
        "object_count": descriptor["harvest"]["object_count"],
    }
    actual_harvest = {key: trace["harvest"][key] for key in expected_harvest}
    expected_files = sorted(
        (
            {
                "file_role": item["file_role"],
                "relative_path": item["relative_path"],
                "byte_length": item["byte_length"],
                "sha256": item["sha256"],
                "media_type": item["media_type"],
            }
            for item in descriptor["files"]
        ),
        key=lambda item: (item["file_role"], item["relative_path"]),
    )
    actual_files = sorted(
        (
            {
                "file_role": item["file_role"],
                "relative_path": item["relative_path"],
                "byte_length": item["byte_length"],
                "sha256": item["sha256"],
                "media_type": item["media_type"],
            }
            for item in trace["harvest"]["files"]
        ),
        key=lambda item: (item["file_role"], item["relative_path"]),
    )
    if trace["dataset"]["dataset_key"] != descriptor["dataset"]["dataset_key"]:
        raise RuntimeError("Existing candidate is registered to the wrong dataset")
    if actual_release != expected_release:
        raise RuntimeError("Existing candidate release provenance conflicts with staged evidence")
    if actual_harvest != expected_harvest:
        raise RuntimeError("Existing candidate harvest provenance conflicts with staged evidence")
    if actual_files != expected_files:
        raise RuntimeError("Existing candidate file provenance conflicts with staged evidence")


def register_candidate(database: Path, candidate_dir: Path) -> dict[str, Any]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Database does not exist: {database}")
    validated = validate_candidate(candidate_dir)
    profile, _registry_sha256 = load_road_profile()
    context = _database_context(database, profile)
    protected_before = _protected_counts(database)
    descriptor = _descriptor(
        Path(validated["candidate_directory"]), validated, context, profile
    )
    existing = _existing_candidate(database, validated["release_key"])
    if existing is not None:
        trace = kane_provenance.trace_release(database, validated["release_key"])
        _assert_registered_candidate(trace, descriptor)
        if _protected_counts(database) != protected_before:
            raise RuntimeError("Protected project or classification state changed unexpectedly")
        return {
            "valid": True,
            "registered": True,
            "existing": True,
            "release_key": validated["release_key"],
            "accepted_release_key": context["release_key"],
            "accepted_release_unchanged": True,
            "protected_state_unchanged": True,
            "candidate_directory": validated["candidate_directory"],
            "trace": trace,
        }
    handle, temporary_name = tempfile.mkstemp(
        prefix=".road-candidate-registration-", suffix=".json", dir=database.parent
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(canonical_bytes(descriptor))
            stream.flush()
            os.fsync(stream.fileno())
        kane_provenance.record_descriptor(database, Path(temporary_name))
    finally:
        Path(temporary_name).unlink(missing_ok=True)
    errors = kane_map_layers.validate_database(database)
    if errors:
        raise RuntimeError("Database validation failed after candidate registration:\n- " + "\n- ".join(errors))
    after = _database_context(database, profile)
    accepted_fields = ("source_release_id", "release_key", "content_sha256", "feature_count")
    if any(after[field] != context[field] for field in accepted_fields):
        raise RuntimeError("Accepted road release changed during candidate registration")
    protected_after = _protected_counts(database)
    if protected_after != protected_before:
        raise RuntimeError("Protected project or classification state changed unexpectedly")
    trace = kane_provenance.trace_release(database, validated["release_key"])
    _assert_registered_candidate(trace, descriptor)
    return {
        "valid": True,
        "registered": True,
        "existing": False,
        "release_key": validated["release_key"],
        "accepted_release_key": context["release_key"],
        "accepted_release_unchanged": True,
        "protected_state_unchanged": True,
        "candidate_directory": validated["candidate_directory"],
        "trace": trace,
    }


def candidate_info(database: Path, release_key: str) -> dict[str, Any]:
    trace = kane_provenance.trace_release(database.resolve(), release_key)
    if trace["release"]["lifecycle_status"] != "candidate":
        raise RuntimeError(f"Source release is not a candidate: {release_key}")
    if trace["dataset"]["dataset_key"] != "roads":
        raise RuntimeError(f"Source release is not a road candidate: {release_key}")
    return {"valid": True, "candidate": trace}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Harvest, validate, and register an official road candidate."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    harvest = subparsers.add_parser("harvest", help="Harvest a complete external candidate")
    harvest.add_argument("staging_root", type=Path)
    harvest.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    validate = subparsers.add_parser("validate", help="Validate one staged candidate")
    validate.add_argument("candidate_directory", type=Path)
    register = subparsers.add_parser(
        "register", help="Register a validated candidate without changing the accepted release"
    )
    register.add_argument("database", type=Path)
    register.add_argument("candidate_directory", type=Path)
    info = subparsers.add_parser("info", help="Trace one registered road candidate")
    info.add_argument("database", type=Path)
    info.add_argument("release_key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "harvest":
            result = harvest_candidate(args.staging_root, timeout_seconds=args.timeout)
        elif args.command == "validate":
            result = validate_candidate(args.candidate_directory)
            result.pop("manifest", None)
        elif args.command == "register":
            result = register_candidate(args.database, args.candidate_directory)
        else:
            result = candidate_info(args.database, args.release_key)
    except (HarvestUnavailableError, HarvestContractError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
