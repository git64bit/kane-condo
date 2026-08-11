#!/usr/bin/env python3
"""Harvest, validate, and atomically register the coordinated Kane County water candidate."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
PROFILE_DIR = TOOLS_DIR.parent / "source-profiles"
UPDATE_GROUP = "water-context"
PROFILE_KEYS = (
    "kane-county-creeks",
    "kane-county-fox-river",
)
DATASET_ORDER = ("water-creeks", "water-fox-river")
CANDIDATE_SCHEMA = 1
REQUIRED_CANDIDATE_FILES = {
    "creeks.geojson",
    "creeks-layer-metadata.json",
    "creeks-object-ids.json",
    "fox-river.geojson",
    "fox-river-layer-metadata.json",
    "fox-river-object-ids.json",
    "manifest.json",
}
DEFAULT_TIMEOUT = 120.0
Requester = Callable[..., Any]


class WaterCandidateError(RuntimeError):
    """Raised when coordinated water evidence violates the approved contract."""


def load_sibling(name: str):
    module_path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_kane_condo_{name}_water_candidate", module_path)
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
kane_road_candidate = load_sibling("kane_road_candidate")

canonical_bytes = kane_road_candidate.canonical_bytes
sha256_bytes = kane_road_candidate.sha256_bytes
sha256_file = kane_road_candidate.sha256_file
load_canonical_json = kane_road_candidate.load_canonical_json
http_request_json = kane_road_candidate.http_request_json
utc_now = kane_road_candidate.utc_now


def load_water_profiles() -> tuple[dict[str, dict[str, Any]], str]:
    result = kane_source_profiles.inspect_registry(PROFILE_DIR)
    if result.get("valid") is not True:
        errors = result.get("errors") or ["unknown registry validation failure"]
        raise WaterCandidateError("Source-profile registry is invalid: " + "; ".join(errors))
    profiles: dict[str, dict[str, Any]] = {}
    for profile in result["registry"]["profiles"]:
        if profile["profile_key"] in PROFILE_KEYS:
            profiles[profile["dataset_key"]] = dict(profile)
    if tuple(sorted(profile["profile_key"] for profile in profiles.values())) != tuple(sorted(PROFILE_KEYS)):
        raise WaterCandidateError("Registry must contain exactly the approved Fox River and creek profiles")
    if set(profiles) != set(DATASET_ORDER):
        raise WaterCandidateError("Water registry datasets are incomplete")
    if any(profile.get("update_group") != UPDATE_GROUP for profile in profiles.values()):
        raise WaterCandidateError("Fox River and creeks must share water-context")
    return profiles, str(result["registry_sha256"])


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


def _object_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WaterCandidateError(f"Feature has invalid {field}: {value!r}")
    return value


def normalize_feature_page(
    profile: Mapping[str, Any],
    payload: Any,
    expected_ids: Sequence[int],
    seen_ids: set[str],
) -> tuple[list[dict[str, Any]], list[list[Any]]]:
    if not isinstance(payload, Mapping):
        raise WaterCandidateError("Feature response must be a JSON object")
    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise WaterCandidateError("Feature query did not return a GeoJSON FeatureCollection")
    if payload.get("exceededTransferLimit") is True:
        raise WaterCandidateError("Feature query exceeded the transfer limit")
    query = profile["query"]
    object_field = query["object_id_field"]
    identity_field = query["identity_field"]
    requested_fields = list(query["out_fields"])
    allowed_geometry = tuple(profile["geometry"]["geojson_types"])
    if profile["geometry"]["missing_geometry_policy"] != "reject":
        raise WaterCandidateError("Water profiles must reject missing geometry")
    by_object: dict[int, tuple[dict[str, Any], str]] = {}
    for index, feature in enumerate(payload["features"]):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise WaterCandidateError(f"Feature response item {index} is not a Feature")
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            raise WaterCandidateError(f"Feature response item {index} has invalid properties")
        missing = [field for field in requested_fields if field not in properties]
        if missing:
            raise WaterCandidateError(
                f"Feature response item {index} is missing requested fields: {', '.join(missing)}"
            )
        object_id = _object_id(properties.get(object_field), object_field)
        if object_id in by_object:
            raise WaterCandidateError(f"Feature page contains duplicate object ID {object_id}")
        identity_value = properties.get(identity_field)
        if isinstance(identity_value, bool) or identity_value is None:
            raise WaterCandidateError(f"Feature is missing stable {identity_field}")
        stable_id = str(identity_value).strip()
        if not stable_id or stable_id in seen_ids:
            raise WaterCandidateError(f"Harvest contains invalid or duplicate stable ID {stable_id!r}")
        if feature.get("geometry") is None:
            raise WaterCandidateError(f"Feature {stable_id} has missing geometry")
        try:
            geometry_type, coordinates = kane_geometry.normalize_map_geometry(feature["geometry"])
        except RuntimeError as exc:
            raise WaterCandidateError(f"Feature {stable_id} has invalid geometry: {exc}") from exc
        if geometry_type not in allowed_geometry:
            raise WaterCandidateError(
                f"Feature {stable_id} has unsupported geometry type {geometry_type!r}"
            )
        normalized_properties = {field: properties[field] for field in requested_fields}
        normalized_properties[object_field] = object_id
        normalized_properties[identity_field] = object_id
        normalized_feature = {
            "type": "Feature",
            "id": stable_id,
            "properties": normalized_properties,
            "geometry": {
                "type": geometry_type,
                "coordinates": json.loads(canonical_bytes(coordinates)),
            },
        }
        canonical_bytes(normalized_feature)
        by_object[object_id] = (normalized_feature, stable_id)
        seen_ids.add(stable_id)
    expected_set = set(expected_ids)
    actual_set = set(by_object)
    if expected_set != actual_set:
        raise WaterCandidateError(
            f"Feature page object-ID mismatch; missing={sorted(expected_set-actual_set)}, "
            f"extra={sorted(actual_set-expected_set)}"
        )
    features: list[dict[str, Any]] = []
    identity_pairs: list[list[Any]] = []
    for object_id in expected_ids:
        feature, stable_id = by_object[object_id]
        features.append(feature)
        identity_pairs.append([object_id, stable_id])
    return features, identity_pairs


def _source_published_at(summary: Mapping[str, Any]) -> str | None:
    return kane_road_candidate._source_published_at(summary)


def _component_slug(dataset_key: str) -> str:
    return "creeks" if dataset_key == "water-creeks" else "fox-river"


def _component_release_keys(dataset_key: str, published_at: str | None, content_sha256: str) -> tuple[str, str]:
    date_token = "undated" if published_at is None else published_at[:10].replace("-", "")
    stem = "kane-water-creeks" if dataset_key == "water-creeks" else "kane-water-fox-river"
    suffix = content_sha256[:12]
    return f"{stem}-candidate-{date_token}-{suffix}", f"{stem}-harvest-{date_token}-{suffix}"


def _harvest_component(
    profile: Mapping[str, Any],
    registry_sha256: str,
    *,
    timeout_seconds: float,
    requester: Requester,
    started_at: str,
) -> dict[str, Any]:
    layer_url = profile["source"]["layer_url"]
    metadata = _request(
        requester, layer_url, {"f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=kane_road_candidate.MAX_METADATA_BYTES,
        post=False,
    )
    try:
        metadata_summary = kane_road_candidate.validate_harvest_metadata(profile, metadata)
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    inventory_payload = _request(
        requester, layer_url + "/query",
        {"where": profile["query"]["where"], "returnIdsOnly": "true", "f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=kane_road_candidate.MAX_INVENTORY_BYTES,
        post=True,
    )
    try:
        object_ids = kane_road_candidate.normalize_inventory(profile, inventory_payload)
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    max_records = int(metadata_summary["max_record_count"])
    page_size = min(int(profile["query"]["page_size"]), max_records)
    features: list[dict[str, Any]] = []
    identity_pairs: list[list[Any]] = []
    seen_ids: set[str] = set()
    page_count = 0
    for start in range(0, len(object_ids), page_size):
        requested_ids = object_ids[start:start + page_size]
        payload = _request(
            requester,
            layer_url + "/query",
            {
                "objectIds": ",".join(str(value) for value in requested_ids),
                "outFields": ",".join(profile["query"]["out_fields"]),
                "returnGeometry": "true",
                "outSR": str(profile["query"]["out_srs"]),
                "f": "geojson",
            },
            timeout_seconds=timeout_seconds,
            byte_limit=kane_road_candidate.MAX_PAGE_BYTES,
            post=True,
        )
        normalized, pairs = normalize_feature_page(profile, payload, requested_ids, seen_ids)
        features.extend(normalized)
        identity_pairs.extend(pairs)
        page_count += 1
    final_metadata = _request(
        requester, layer_url, {"f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=kane_road_candidate.MAX_METADATA_BYTES,
        post=False,
    )
    try:
        final_summary = kane_road_candidate.validate_harvest_metadata(profile, final_metadata)
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    if final_summary != metadata_summary:
        raise WaterCandidateError(f"{profile['dataset_key']} metadata changed during harvest")
    final_inventory = _request(
        requester, layer_url + "/query",
        {"where": profile["query"]["where"], "returnIdsOnly": "true", "f": "json"},
        timeout_seconds=timeout_seconds,
        byte_limit=kane_road_candidate.MAX_INVENTORY_BYTES,
        post=True,
    )
    try:
        final_object_ids = kane_road_candidate.normalize_inventory(profile, final_inventory)
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    if final_object_ids != object_ids:
        raise WaterCandidateError(f"{profile['dataset_key']} object-ID inventory changed during harvest")
    published_at = _source_published_at(metadata_summary)
    collection = {
        "type": "FeatureCollection",
        "name": profile["profile_key"],
        "source": {
            "profile_key": profile["profile_key"],
            "dataset_key": profile["dataset_key"],
            "update_group": UPDATE_GROUP,
            "layer_url": layer_url,
            "identity_field": profile["query"]["identity_field"],
            "object_id_field": profile["query"]["object_id_field"],
            "out_srs": profile["query"]["out_srs"],
            "published_at": published_at,
            "missing_geometry_policy": "reject",
            "copyright_text": profile["copyright_text"],
        },
        "features": features,
    }
    source_data = canonical_bytes(collection)
    metadata_data = canonical_bytes(metadata)
    inventory_data = canonical_bytes(object_ids)
    content_sha256 = sha256_bytes(source_data)
    release_key, harvest_key = _component_release_keys(profile["dataset_key"], published_at, content_sha256)
    return {
        "dataset_key": profile["dataset_key"],
        "profile_key": profile["profile_key"],
        "registry_filename": profile["registry_filename"],
        "registry_sha256": registry_sha256,
        "donor_commit": profile["donor"]["commit"],
        "source_published_at": published_at,
        "metadata_summary": metadata_summary,
        "started_at": started_at,
        "page_size": page_size,
        "page_count": page_count,
        "object_ids": object_ids,
        "identity_pairs": identity_pairs,
        "source_data": source_data,
        "metadata_data": metadata_data,
        "inventory_data": inventory_data,
        "content_sha256": content_sha256,
        "release_key": release_key,
        "harvest_key": harvest_key,
    }


def _group_identity(components: Mapping[str, Mapping[str, Any]]) -> tuple[str, str]:
    published = [value["source_published_at"] for value in components.values() if value["source_published_at"]]
    token = (max(published)[:10].replace("-", "") if published else "undated")
    identity = {
        "update_group": UPDATE_GROUP,
        "components": [
            {
                "dataset_key": key,
                "release_key": components[key]["release_key"],
                "content_sha256": components[key]["content_sha256"],
                "object_ids_sha256": components[key].get("object_ids_sha256") or kane_source_status.object_id_sha256(components[key]["object_ids"]),
                "source_published_at": components[key]["source_published_at"],
            }
            for key in DATASET_ORDER
        ],
    }
    digest = sha256_bytes(canonical_bytes(identity))
    return f"kane-water-context-candidate-{token}-{digest[:12]}", digest


def _write_file(path: Path, data: bytes) -> None:
    kane_road_candidate._write_file(path, data)


def _file_record(path: Path) -> dict[str, Any]:
    return kane_road_candidate._file_record(path)


def _result(candidate_dir: Path, manifest: Mapping[str, Any], *, existing: bool) -> dict[str, Any]:
    return {
        "valid": True,
        "existing": existing,
        "candidate_directory": str(candidate_dir.resolve()),
        "group_key": manifest["group_key"],
        "group_sha256": manifest["group_sha256"],
        "manifest_sha256": sha256_file(candidate_dir / "manifest.json"),
        "update_group": UPDATE_GROUP,
        "components": {
            key: {
                "release_key": manifest["components"][key]["registration"]["release_key"],
                "harvest_key": manifest["components"][key]["registration"]["harvest_key"],
                "feature_count": manifest["components"][key]["output"]["feature_count"],
                "object_count": manifest["components"][key]["inventory"]["object_count"],
                "content_sha256": manifest["components"][key]["output"]["sha256"],
                "source_published_at": manifest["components"][key]["source"]["published_at"],
            }
            for key in DATASET_ORDER
        },
    }


def harvest_candidate(
    staging_root: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    requester: Requester = http_request_json,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    profiles, registry_sha256 = load_water_profiles()
    started_at = started_at or utc_now()
    components = {
        key: _harvest_component(
            profiles[key], registry_sha256,
            timeout_seconds=timeout_seconds,
            requester=requester,
            started_at=started_at,
        )
        for key in DATASET_ORDER
    }
    completed_at = completed_at or utc_now()
    if completed_at < started_at:
        raise WaterCandidateError("Candidate harvest completed_at precedes started_at")
    group_key, group_sha256 = _group_identity(components)
    water_root = staging_root.resolve() / "water"
    water_root.mkdir(parents=True, exist_ok=True)
    if water_root.is_symlink():
        raise WaterCandidateError(f"Water staging directory must not be a symlink: {water_root}")
    final_dir = water_root / group_key
    if final_dir.exists():
        validated = validate_candidate(final_dir)
        if validated["group_sha256"] != group_sha256:
            raise WaterCandidateError(f"Existing coordinated candidate conflicts: {final_dir}")
        return _result(final_dir, validated["manifest"], existing=True)
    temporary: Path | None = Path(tempfile.mkdtemp(prefix=".water-candidate-", dir=water_root))
    try:
        component_manifest: dict[str, Any] = {}
        for key in DATASET_ORDER:
            component = components[key]
            slug = _component_slug(key)
            source_path = temporary / f"{slug}.geojson"
            metadata_path = temporary / f"{slug}-layer-metadata.json"
            inventory_path = temporary / f"{slug}-object-ids.json"
            _write_file(source_path, component["source_data"])
            _write_file(metadata_path, component["metadata_data"])
            _write_file(inventory_path, component["inventory_data"])
            component_manifest[key] = {
                "profile": {
                    "profile_key": component["profile_key"],
                    "registry_filename": component["registry_filename"],
                    "registry_sha256": component["registry_sha256"],
                    "donor_commit": component["donor_commit"],
                },
                "source": {
                    "published_at": component["source_published_at"],
                    "metadata_summary": component["metadata_summary"],
                },
                "harvest": {
                    "page_size": component["page_size"],
                    "page_count": component["page_count"],
                    "end_metadata_verified": True,
                    "end_inventory_verified": True,
                },
                "inventory": {
                    **_file_record(inventory_path),
                    "object_count": len(component["object_ids"]),
                    "object_ids_sha256": kane_source_status.object_id_sha256(component["object_ids"]),
                },
                "output": {
                    **_file_record(source_path),
                    "feature_count": len(component["object_ids"]),
                    "stable_id_count": len(component["identity_pairs"]),
                    "identity_map_sha256": sha256_bytes(canonical_bytes(component["identity_pairs"])),
                },
                "metadata_file": _file_record(metadata_path),
                "registration": {
                    "release_key": component["release_key"],
                    "harvest_key": component["harvest_key"],
                    "lifecycle_status": "candidate",
                },
            }
        manifest = {
            "water_candidate_schema": CANDIDATE_SCHEMA,
            "candidate_kind": "official-water-context",
            "update_group": UPDATE_GROUP,
            "group_key": group_key,
            "group_sha256": group_sha256,
            "registry_sha256": registry_sha256,
            "harvest": {"started_at": started_at, "completed_at": completed_at},
            "components": component_manifest,
        }
        _write_file(temporary / "manifest.json", canonical_bytes(manifest))
        validate_candidate(temporary, require_final_layout=False)
        os.replace(temporary, final_dir)
        temporary = None
        return _result(final_dir, manifest, existing=False)
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _validate_file_set(candidate_dir: Path) -> None:
    if not candidate_dir.is_dir() or candidate_dir.is_symlink():
        raise WaterCandidateError(f"Candidate directory is missing or is a symlink: {candidate_dir}")
    names: set[str] = set()
    for path in candidate_dir.iterdir():
        if path.is_symlink():
            raise WaterCandidateError(f"Candidate contains a symlink: {path.name}")
        if not path.is_file():
            raise WaterCandidateError(f"Candidate contains a non-file entry: {path.name}")
        names.add(path.name)
    if names != REQUIRED_CANDIDATE_FILES:
        raise WaterCandidateError(
            f"Candidate file set mismatch; missing={sorted(REQUIRED_CANDIDATE_FILES-names)}, "
            f"extra={sorted(names-REQUIRED_CANDIDATE_FILES)}"
        )


def _validate_component(
    candidate_dir: Path,
    profile: Mapping[str, Any],
    registry_sha256: str,
    manifest_component: Mapping[str, Any],
) -> dict[str, Any]:
    dataset_key = profile["dataset_key"]
    slug = _component_slug(dataset_key)
    metadata, _ = load_canonical_json(candidate_dir / f"{slug}-layer-metadata.json")
    try:
        metadata_summary = kane_road_candidate.validate_harvest_metadata(profile, metadata)
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    inventory, _ = load_canonical_json(candidate_dir / f"{slug}-object-ids.json")
    try:
        object_ids = kane_source_status.normalize_object_ids(inventory, f"{dataset_key} object IDs")
    except Exception as exc:
        raise WaterCandidateError(str(exc)) from exc
    if not object_ids or object_ids != inventory:
        raise WaterCandidateError(f"{dataset_key} object inventory must be nonempty and ascending")
    collection, source_raw = load_canonical_json(candidate_dir / f"{slug}.geojson")
    if not isinstance(collection, Mapping) or set(collection) != {"type", "name", "source", "features"}:
        raise WaterCandidateError(f"{dataset_key} candidate has an unexpected key set")
    expected_source = {
        "profile_key": profile["profile_key"],
        "dataset_key": dataset_key,
        "update_group": UPDATE_GROUP,
        "layer_url": profile["source"]["layer_url"],
        "identity_field": profile["query"]["identity_field"],
        "object_id_field": profile["query"]["object_id_field"],
        "out_srs": profile["query"]["out_srs"],
        "published_at": _source_published_at(metadata_summary),
        "missing_geometry_policy": "reject",
        "copyright_text": profile["copyright_text"],
    }
    if collection.get("type") != "FeatureCollection" or collection.get("name") != profile["profile_key"]:
        raise WaterCandidateError(f"{dataset_key} candidate FeatureCollection identity is invalid")
    if collection.get("source") != expected_source:
        raise WaterCandidateError(f"{dataset_key} source summary does not match profile and metadata")
    features = collection.get("features")
    if not isinstance(features, list) or len(features) != len(object_ids):
        raise WaterCandidateError(f"{dataset_key} feature count does not match object inventory")
    seen: set[str] = set()
    identity_pairs: list[list[Any]] = []
    for feature, object_id in zip(features, object_ids):
        normalized, pairs = normalize_feature_page(
            profile, {"type": "FeatureCollection", "features": [feature]}, [object_id], seen
        )
        if normalized[0] != feature:
            raise WaterCandidateError(f"{dataset_key} feature serialization is not normalized")
        identity_pairs.extend(pairs)
    published_at = expected_source["published_at"]
    content_sha256 = sha256_bytes(source_raw)
    release_key, harvest_key = _component_release_keys(dataset_key, published_at, content_sha256)
    expected_manifest = {
        "profile": {
            "profile_key": profile["profile_key"],
            "registry_filename": profile["registry_filename"],
            "registry_sha256": registry_sha256,
            "donor_commit": profile["donor"]["commit"],
        },
        "source": {
            "published_at": published_at,
            "metadata_summary": metadata_summary,
        },
        "harvest": dict(manifest_component.get("harvest") or {}),
        "inventory": {
            **_file_record(candidate_dir / f"{slug}-object-ids.json"),
            "object_count": len(object_ids),
            "object_ids_sha256": kane_source_status.object_id_sha256(object_ids),
        },
        "output": {
            **_file_record(candidate_dir / f"{slug}.geojson"),
            "feature_count": len(features),
            "stable_id_count": len(seen),
            "identity_map_sha256": sha256_bytes(canonical_bytes(identity_pairs)),
        },
        "metadata_file": _file_record(candidate_dir / f"{slug}-layer-metadata.json"),
        "registration": {
            "release_key": release_key,
            "harvest_key": harvest_key,
            "lifecycle_status": "candidate",
        },
    }
    harvest = expected_manifest["harvest"]
    if set(harvest) != {"page_size", "page_count", "end_metadata_verified", "end_inventory_verified"}:
        raise WaterCandidateError(f"{dataset_key} harvest contract is invalid")
    expected_page_size = min(int(profile["query"]["page_size"]), int(metadata_summary["max_record_count"]))
    expected_page_count = (len(object_ids) + expected_page_size - 1) // expected_page_size
    if harvest != {
        "page_size": expected_page_size,
        "page_count": expected_page_count,
        "end_metadata_verified": True,
        "end_inventory_verified": True,
    }:
        raise WaterCandidateError(f"{dataset_key} harvest paging evidence is invalid")
    if dict(manifest_component) != expected_manifest:
        raise WaterCandidateError(f"{dataset_key} manifest component does not match staged evidence")
    return {
        "dataset_key": dataset_key,
        "release_key": release_key,
        "harvest_key": harvest_key,
        "source_published_at": published_at,
        "object_count": len(object_ids),
        "feature_count": len(features),
        "stable_id_count": len(seen),
        "content_sha256": content_sha256,
        "object_ids_sha256": kane_source_status.object_id_sha256(object_ids),
    }


def validate_candidate(candidate_dir: Path, *, require_final_layout: bool = True) -> dict[str, Any]:
    candidate_dir = candidate_dir.absolute()
    if candidate_dir.is_symlink():
        raise WaterCandidateError(f"Candidate directory must not be a symlink: {candidate_dir}")
    candidate_dir = candidate_dir.resolve()
    _validate_file_set(candidate_dir)
    manifest, manifest_raw = load_canonical_json(candidate_dir / "manifest.json")
    if not isinstance(manifest, Mapping):
        raise WaterCandidateError("Water candidate manifest must be a JSON object")
    if set(manifest) != {
        "water_candidate_schema", "candidate_kind", "update_group", "group_key",
        "group_sha256", "registry_sha256", "harvest", "components"
    }:
        raise WaterCandidateError("Water candidate manifest has an unexpected key set")
    if manifest["water_candidate_schema"] != CANDIDATE_SCHEMA or manifest["candidate_kind"] != "official-water-context":
        raise WaterCandidateError("Water candidate manifest identity is invalid")
    if manifest["update_group"] != UPDATE_GROUP:
        raise WaterCandidateError("Water candidate update group is invalid")
    harvest = manifest.get("harvest")
    if not isinstance(harvest, Mapping) or set(harvest) != {"started_at", "completed_at"}:
        raise WaterCandidateError("Water candidate harvest timestamps are invalid")
    if not kane_provenance.valid_datetime(harvest["started_at"]) or not kane_provenance.valid_datetime(harvest["completed_at"]):
        raise WaterCandidateError("Water candidate harvest timestamps are invalid")
    if harvest["completed_at"] < harvest["started_at"]:
        raise WaterCandidateError("Water candidate completed_at precedes started_at")
    profiles, registry_sha256 = load_water_profiles()
    if manifest["registry_sha256"] != registry_sha256:
        raise WaterCandidateError("Water candidate registry hash is stale")
    components_manifest = manifest.get("components")
    if not isinstance(components_manifest, Mapping) or set(components_manifest) != set(DATASET_ORDER):
        raise WaterCandidateError("Water candidate must contain both coordinated components")
    components = {
        key: _validate_component(candidate_dir, profiles[key], registry_sha256, components_manifest[key])
        for key in DATASET_ORDER
    }
    group_key, group_sha256 = _group_identity(components)
    if manifest["group_key"] != group_key or manifest["group_sha256"] != group_sha256:
        raise WaterCandidateError("Water candidate group identity is invalid")
    if require_final_layout and (candidate_dir.parent.name != "water" or candidate_dir.name != group_key):
        raise WaterCandidateError("Water candidate directory must be water/GROUP_KEY")
    return {
        "valid": True,
        "candidate_directory": str(candidate_dir),
        "group_key": group_key,
        "group_sha256": group_sha256,
        "manifest_sha256": sha256_bytes(manifest_raw),
        "update_group": UPDATE_GROUP,
        "components": components,
        "manifest": dict(manifest),
    }


def _database_context(database: Path, profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    errors = kane_map_layers.validate_database(database)
    if errors:
        raise WaterCandidateError("Database validation failed before water registration:\n- " + "\n- ".join(errors))
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, dict[str, Any]] = {}
        for key in DATASET_ORDER:
            rows = connection.execute(
                "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count, "
                "d.dataset_key, d.name AS dataset_name, d.description, d.data_kind, d.source_uri, "
                "c.county_key, c.name AS county_name, c.state_code, c.country_code, c.fips_code, "
                "a.agency_key, a.name AS agency_name, a.jurisdiction, a.homepage_uri "
                "FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id "
                "JOIN county c ON c.county_id=d.county_id "
                "JOIN source_agency a ON a.source_agency_id=d.source_agency_id "
                "WHERE d.dataset_key=? AND sr.lifecycle_status='accepted'",
                (key,),
            ).fetchall()
            if len(rows) != 1:
                raise WaterCandidateError(f"{key} must have exactly one accepted release, found {len(rows)}")
            row = dict(rows[0])
            profile = profiles[key]
            if row["agency_key"] != profile["agency_key"] or row["data_kind"] != "water" or row["source_uri"] != profile["source"]["layer_url"]:
                raise WaterCandidateError(f"Accepted {key} provenance does not match the approved profile")
            result[key] = row
        return result
    finally:
        connection.close()


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
        return {table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) for table in PROTECTED_TABLES}
    finally:
        connection.close()


def _descriptor(candidate_dir: Path, validated: Mapping[str, Any], context: Mapping[str, Any], profile: Mapping[str, Any], companion_release_key: str) -> dict[str, Any]:
    key = profile["dataset_key"]
    slug = _component_slug(key)
    component = validated["components"][key]
    manifest = validated["manifest"]
    component_manifest = manifest["components"][key]
    roles = {
        f"{slug}.geojson": ("source", "application/geo+json"),
        f"{slug}-layer-metadata.json": ("metadata", "application/json"),
        f"{slug}-object-ids.json": ("inventory", "application/json"),
        "manifest.json": ("manifest", "application/json"),
    }
    files = []
    for name in sorted(roles):
        role, media_type = roles[name]
        path = candidate_dir / name
        files.append({
            "file_role": role,
            "relative_path": f"water/{validated['group_key']}/{name}",
            "byte_length": path.stat().st_size,
            "sha256": sha256_file(path),
            "media_type": media_type,
        })
    group_metadata = {
        "update_group": UPDATE_GROUP,
        "water_group_key": validated["group_key"],
        "water_group_sha256": validated["group_sha256"],
        "water_group_manifest_sha256": validated["manifest_sha256"],
        "companion_release_key": companion_release_key,
    }
    return {
        "county": {
            "county_key": context["county_key"], "name": context["county_name"],
            "state_code": context["state_code"], "country_code": context["country_code"],
            "fips_code": context["fips_code"],
        },
        "agency": {
            "agency_key": context["agency_key"], "name": context["agency_name"],
            "jurisdiction": context["jurisdiction"], "homepage_uri": context["homepage_uri"],
        },
        "dataset": {
            "dataset_key": context["dataset_key"], "name": context["dataset_name"],
            "description": context["description"], "data_kind": context["data_kind"],
            "source_uri": context["source_uri"],
        },
        "harvest": {
            "harvest_key": component["harvest_key"],
            "started_at": manifest["harvest"]["started_at"],
            "completed_at": manifest["harvest"]["completed_at"],
            "status": "succeeded",
            "source_metadata": {
                "profile_key": profile["profile_key"],
                "registry_sha256": manifest["registry_sha256"],
                "id_property": profile["query"]["identity_field"],
                "object_id_field": profile["query"]["object_id_field"],
                "object_ids_sha256": component_manifest["inventory"]["object_ids_sha256"],
                "identity_map_sha256": component_manifest["output"]["identity_map_sha256"],
                **group_metadata,
            },
            "object_count": component["object_count"],
        },
        "files": files,
        "release": {
            "release_key": component["release_key"],
            "lifecycle_status": "candidate",
            "source_published_at": component["source_published_at"],
            "content_sha256": component["content_sha256"],
            "feature_count": component["feature_count"],
            "metadata": {
                "profile_key": profile["profile_key"],
                "registry_sha256": manifest["registry_sha256"],
                **group_metadata,
            },
            "accepted_at": None,
        },
    }


def _record_descriptors_atomic(database: Path, descriptors: Sequence[Mapping[str, Any]]) -> None:
    normalized = [kane_provenance.normalize_descriptor(descriptor) for descriptor in descriptors]
    if kane_provenance.validate_database(database):
        raise WaterCandidateError("Database failed administrative provenance validation before write")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        for descriptor in normalized:
            county_id = kane_provenance.ensure_entity(connection, "county", "county_key", descriptor["county"])
            agency_id = kane_provenance.ensure_entity(connection, "source_agency", "agency_key", descriptor["agency"])
            dataset_id = kane_provenance.ensure_entity(
                connection, "dataset", "dataset_key",
                dict(descriptor["dataset"], county_id=county_id, source_agency_id=agency_id),
            )
            harvest_id = kane_provenance.ensure_entity(
                connection, "harvest_run", "harvest_key",
                dict(descriptor["harvest"], dataset_id=dataset_id),
            )
            release_key = descriptor["release"]["release_key"]
            if connection.execute("SELECT 1 FROM source_release WHERE release_key=?", (release_key,)).fetchone():
                raise WaterCandidateError(f"Source release already exists: {release_key}")
            if connection.execute("SELECT COUNT(*) FROM source_file WHERE harvest_run_id=?", (harvest_id,)).fetchone()[0]:
                raise WaterCandidateError(f"Harvest already has source files: {descriptor['harvest']['harvest_key']}")
            for source_file in descriptor["files"]:
                values = dict(source_file, harvest_run_id=harvest_id)
                columns = tuple(values)
                connection.execute(
                    f"INSERT INTO source_file ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(values[column] for column in columns),
                )
            release_values = dict(descriptor["release"], dataset_id=dataset_id, harvest_run_id=harvest_id)
            columns = tuple(release_values)
            connection.execute(
                f"INSERT INTO source_release ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                tuple(release_values[column] for column in columns),
            )
        changed_at = kane_provenance.utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET last_change=? WHERE table_name IN "
            "('county','source_agency','dataset','harvest_run','source_file','source_release')",
            (changed_at,),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _candidate_rows(database: Path, group_key: str) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, str] = {}
        for row in connection.execute(
            "SELECT sr.release_key, sr.metadata_json, d.dataset_key FROM source_release sr "
            "JOIN dataset d ON d.dataset_id=sr.dataset_id "
            "WHERE d.dataset_key IN ('water-creeks','water-fox-river') AND sr.lifecycle_status='candidate'"
        ):
            try:
                metadata = json.loads(row["metadata_json"])
            except json.JSONDecodeError:
                continue
            if metadata.get("water_group_key") == group_key:
                result[row["dataset_key"]] = row["release_key"]
        return result
    finally:
        connection.close()


def _assert_trace(trace: Mapping[str, Any], descriptor: Mapping[str, Any]) -> None:
    if trace["dataset"]["dataset_key"] != descriptor["dataset"]["dataset_key"]:
        raise WaterCandidateError("Registered water candidate belongs to the wrong dataset")
    release = descriptor["release"]
    for field in ("release_key", "lifecycle_status", "source_published_at", "content_sha256", "feature_count", "accepted_at"):
        if trace["release"][field] != release[field]:
            raise WaterCandidateError("Registered water release provenance conflicts with staged evidence")
    if trace["release"]["metadata"] != release["metadata"]:
        raise WaterCandidateError("Registered water release metadata conflicts with staged evidence")
    harvest = descriptor["harvest"]
    for field in ("harvest_key", "started_at", "completed_at", "status", "object_count"):
        if trace["harvest"][field] != harvest[field]:
            raise WaterCandidateError("Registered water harvest provenance conflicts with staged evidence")
    if trace["harvest"]["source_metadata"] != harvest["source_metadata"]:
        raise WaterCandidateError("Registered water harvest metadata conflicts with staged evidence")


def register_candidate(database: Path, candidate_dir: Path) -> dict[str, Any]:
    database = database.resolve()
    if not database.is_file():
        raise WaterCandidateError(f"Database does not exist: {database}")
    validated = validate_candidate(candidate_dir)
    profiles, _ = load_water_profiles()
    contexts = _database_context(database, profiles)
    protected_before = _protected_counts(database)
    release_keys = {key: validated["components"][key]["release_key"] for key in DATASET_ORDER}
    descriptors = {
        key: _descriptor(
            Path(validated["candidate_directory"]), validated, contexts[key], profiles[key],
            release_keys["water-fox-river" if key == "water-creeks" else "water-creeks"],
        )
        for key in DATASET_ORDER
    }
    existing = _candidate_rows(database, validated["group_key"])
    if existing:
        if set(existing) != set(DATASET_ORDER) or existing != release_keys:
            raise WaterCandidateError("Partial or conflicting coordinated water registration detected")
        traces = {key: kane_provenance.trace_release(database, release_keys[key]) for key in DATASET_ORDER}
        for key in DATASET_ORDER:
            _assert_trace(traces[key], descriptors[key])
        if _protected_counts(database) != protected_before:
            raise WaterCandidateError("Protected project state changed unexpectedly")
        return {
            "valid": True, "registered": True, "existing": True,
            "group_key": validated["group_key"], "update_group": UPDATE_GROUP,
            "accepted_releases_unchanged": True, "protected_state_unchanged": True,
            "candidate_directory": validated["candidate_directory"], "traces": traces,
        }
    if any(_candidate_rows(database, validated["group_key"]).values()):
        raise WaterCandidateError("Partial coordinated water registration detected")
    _record_descriptors_atomic(database, [descriptors[key] for key in DATASET_ORDER])
    errors = kane_map_layers.validate_database(database)
    if errors:
        raise WaterCandidateError("Database validation failed after water registration:\n- " + "\n- ".join(errors))
    after_contexts = _database_context(database, profiles)
    for key in DATASET_ORDER:
        for field in ("source_release_id", "release_key", "content_sha256", "feature_count"):
            if after_contexts[key][field] != contexts[key][field]:
                raise WaterCandidateError(f"Accepted {key} release changed during candidate registration")
    if _protected_counts(database) != protected_before:
        raise WaterCandidateError("Protected project state changed unexpectedly")
    traces = {key: kane_provenance.trace_release(database, release_keys[key]) for key in DATASET_ORDER}
    for key in DATASET_ORDER:
        _assert_trace(traces[key], descriptors[key])
    if _candidate_rows(database, validated["group_key"]) != release_keys:
        raise WaterCandidateError("Coordinated water candidate registration is incomplete")
    return {
        "valid": True, "registered": True, "existing": False,
        "group_key": validated["group_key"], "update_group": UPDATE_GROUP,
        "accepted_releases_unchanged": True, "protected_state_unchanged": True,
        "candidate_directory": validated["candidate_directory"], "traces": traces,
    }


def candidate_info(database: Path, group_key: str) -> dict[str, Any]:
    rows = _candidate_rows(database.resolve(), group_key)
    if set(rows) != set(DATASET_ORDER):
        raise WaterCandidateError(f"Unknown or partial coordinated water candidate: {group_key}")
    traces = {key: kane_provenance.trace_release(database.resolve(), rows[key]) for key in DATASET_ORDER}
    for key in DATASET_ORDER:
        metadata = traces[key]["release"]["metadata"]
        if metadata.get("water_group_key") != group_key or metadata.get("update_group") != UPDATE_GROUP:
            raise WaterCandidateError("Water candidate group metadata is inconsistent")
    return {"valid": True, "group_key": group_key, "update_group": UPDATE_GROUP, "candidates": traces}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    harvest = subparsers.add_parser("harvest", help="Harvest one complete coordinated water candidate")
    harvest.add_argument("staging_root", type=Path)
    harvest.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    validate = subparsers.add_parser("validate", help="Validate one staged coordinated candidate")
    validate.add_argument("candidate_directory", type=Path)
    register = subparsers.add_parser("register", help="Atomically register both water candidates")
    register.add_argument("database", type=Path)
    register.add_argument("candidate_directory", type=Path)
    info = subparsers.add_parser("info", help="Trace a coordinated registered water candidate")
    info.add_argument("database", type=Path)
    info.add_argument("group_key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "harvest":
            result = harvest_candidate(args.staging_root, timeout_seconds=args.timeout)
        elif args.command == "validate":
            result = validate_candidate(args.candidate_directory)
            result.pop("manifest", None)
        elif args.command == "register":
            result = register_candidate(args.database, args.candidate_directory)
        else:
            result = candidate_info(args.database, args.group_key)
    except (WaterCandidateError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
