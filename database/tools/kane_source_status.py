#!/usr/bin/env python3
"""Check official Kane County source status without downloading feature geometry."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import socket
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TOOLS_DIR = Path(__file__).resolve().parent
PROFILE_DIR = TOOLS_DIR.parent / "source-profiles"
STATUS_UP_TO_DATE = "up_to_date"
STATUS_NEW = "new_source_detected"
STATUS_UNAVAILABLE = "source_unavailable"
STATUS_UNEXPECTED = "source_changed_unexpectedly"
STATUS_LABELS = {
    STATUS_UP_TO_DATE: "Up to date",
    STATUS_NEW: "New source detected",
    STATUS_UNAVAILABLE: "Source unavailable",
    STATUS_UNEXPECTED: "Source changed unexpectedly",
}
STATUS_PRECEDENCE = {
    STATUS_UP_TO_DATE: 0,
    STATUS_NEW: 1,
    STATUS_UNAVAILABLE: 2,
    STATUS_UNEXPECTED: 3,
}
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
USER_AGENT = "Kane-Condo-Source-Status/1"
DATASET_TABLES = {
    "county-boundary": "source_county_boundary",
    "buildings": "source_building",
    "roads": "source_map_feature",
    "water-fox-river": "source_map_feature",
    "water-creeks": "source_map_feature",
}


class SourceUnavailableError(RuntimeError):
    """Raised when the approved endpoint cannot be reached reliably."""


class SourceUnexpectedError(RuntimeError):
    """Raised when a response violates the approved source contract."""


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _load_registry(profile_dir: Path) -> dict[str, Any]:
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import kane_source_profiles  # type: ignore
    finally:
        sys.path.pop(0)
    result = kane_source_profiles.inspect_registry(profile_dir)
    if result.get("valid") is not True:
        errors = result.get("errors") or ["unknown registry validation failure"]
        raise RuntimeError("Source-profile registry is invalid: " + "; ".join(errors))
    return {"registry": dict(result["registry"]), "registry_sha256": result["registry_sha256"]}


def _canonical_id_bytes(object_ids: Sequence[int]) -> bytes:
    return (",".join(str(value) for value in object_ids)).encode("ascii")


def object_id_sha256(object_ids: Sequence[int]) -> str:
    """Return the deterministic identity of an ascending numeric ID inventory."""
    return hashlib.sha256(_canonical_id_bytes(object_ids)).hexdigest()


def normalize_object_ids(value: Any, label: str) -> list[int]:
    if not isinstance(value, list):
        raise SourceUnexpectedError(f"{label} must be an array")
    normalized: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise SourceUnexpectedError(
                f"{label}[{index}] must be a nonnegative JSON integer"
            )
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise SourceUnexpectedError(f"{label} contains duplicate object IDs")
    normalized.sort()
    return normalized


def _response_url_matches(actual: str, expected: str) -> bool:
    actual_parts = urllib.parse.urlsplit(actual)
    expected_parts = urllib.parse.urlsplit(expected)
    return (
        actual_parts.scheme == expected_parts.scheme
        and actual_parts.netloc == expected_parts.netloc
        and actual_parts.path == expected_parts.path
        and urllib.parse.parse_qsl(actual_parts.query, keep_blank_values=True)
        == urllib.parse.parse_qsl(expected_parts.query, keep_blank_values=True)
        and not actual_parts.fragment
    )


def _read_json_response(response: Any, expected_url: str, byte_limit: int) -> Any:
    final_url = response.geturl()
    if not _response_url_matches(final_url, expected_url):
        raise SourceUnexpectedError(f"Endpoint redirected unexpectedly to {final_url}")
    content_type = response.headers.get_content_type()
    if content_type not in {"application/json", "text/json", "text/plain"}:
        raise SourceUnexpectedError(f"Unexpected response content type: {content_type}")
    data = response.read(byte_limit + 1)
    if len(data) > byte_limit:
        raise SourceUnexpectedError(f"Response exceeds {byte_limit} bytes")
    try:
        text = data.decode("utf-8-sig")
        value = json.loads(text, parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant {token}")
        ))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceUnexpectedError(f"Response is not valid UTF-8 JSON: {exc}") from exc
    if isinstance(value, Mapping) and "error" in value:
        raise SourceUnexpectedError("ArcGIS returned an error object")
    return value


def fetch_json(
    url: str,
    *,
    timeout_seconds: float,
    byte_limit: int,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            return _read_json_response(response, url, byte_limit)
    except SourceUnexpectedError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise SourceUnavailableError(str(exc)) from exc
    except OSError as exc:
        raise SourceUnavailableError(str(exc)) from exc


def _metadata_url(profile: Mapping[str, Any]) -> str:
    return profile["source"]["layer_url"] + "?" + urllib.parse.urlencode({"f": "json"})


def _inventory_url(profile: Mapping[str, Any]) -> str:
    query = profile["query"]
    return profile["source"]["layer_url"] + "/query?" + urllib.parse.urlencode(
        {
            "where": query["where"],
            "returnIdsOnly": "true",
            "f": "json",
        }
    )


def validate_layer_metadata(profile: Mapping[str, Any], metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise SourceUnexpectedError("Layer metadata must be a JSON object")
    geometry_type = metadata.get("geometryType")
    expected_geometry = profile["geometry"]["arcgis_type"]
    if geometry_type != expected_geometry:
        raise SourceUnexpectedError(
            f"geometryType changed from {expected_geometry!r} to {geometry_type!r}"
        )
    object_id_field = metadata.get("objectIdField") or metadata.get("objectIdFieldName")
    expected_object_id = profile["query"]["object_id_field"]
    if object_id_field != expected_object_id:
        raise SourceUnexpectedError(
            f"object ID field changed from {expected_object_id!r} to {object_id_field!r}"
        )
    fields = metadata.get("fields")
    if not isinstance(fields, list):
        raise SourceUnexpectedError("Layer metadata fields must be an array")
    field_names: list[str] = []
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping) or not isinstance(field.get("name"), str):
            raise SourceUnexpectedError(f"Layer metadata fields[{index}] is malformed")
        field_names.append(field["name"])
    missing = [name for name in profile["query"]["out_fields"] if name not in field_names]
    if missing:
        raise SourceUnexpectedError("Requested fields disappeared: " + ", ".join(missing))
    max_record_count = metadata.get("maxRecordCount")
    if (
        max_record_count is not None
        and (
            isinstance(max_record_count, bool)
            or not isinstance(max_record_count, int)
            or max_record_count <= 0
        )
    ):
        raise SourceUnexpectedError("maxRecordCount must be a positive integer when present")
    edit_times: dict[str, int | None] = {
        "lastEditDate": None,
        "schemaLastEditDate": None,
        "dataLastEditDate": None,
    }
    editing_info = metadata.get("editingInfo")
    if editing_info is not None and not isinstance(editing_info, Mapping):
        raise SourceUnexpectedError("editingInfo must be an object when present")
    if isinstance(editing_info, Mapping):
        for key in edit_times:
            candidate = editing_info.get(key)
            if candidate is None:
                continue
            if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
                raise SourceUnexpectedError(
                    f"editingInfo.{key} must be a nonnegative integer"
                )
            edit_times[key] = candidate

    comparison_ms = edit_times["dataLastEditDate"]
    comparison_origin = "dataLastEditDate" if comparison_ms is not None else None
    if comparison_ms is None:
        last_edit_ms = edit_times["lastEditDate"]
        schema_edit_ms = edit_times["schemaLastEditDate"]
        if last_edit_ms is not None and last_edit_ms != schema_edit_ms:
            comparison_ms = last_edit_ms
            comparison_origin = "lastEditDate"

    return {
        "geometry_type": geometry_type,
        "object_id_field": object_id_field,
        "field_count": len(field_names),
        "max_record_count": max_record_count,
        "last_edit_ms": edit_times["lastEditDate"],
        "schema_last_edit_ms": edit_times["schemaLastEditDate"],
        "data_last_edit_ms": edit_times["dataLastEditDate"],
        "comparison_edit_ms": comparison_ms,
        "comparison_edit_origin": comparison_origin,
    }


def validate_inventory(profile: Mapping[str, Any], payload: Any) -> list[int]:
    if not isinstance(payload, Mapping):
        raise SourceUnexpectedError("Object-ID response must be a JSON object")
    expected_field = profile["query"]["object_id_field"]
    actual_field = payload.get("objectIdFieldName")
    if actual_field != expected_field:
        raise SourceUnexpectedError(
            f"Object-ID response field changed from {expected_field!r} to {actual_field!r}"
        )
    return normalize_object_ids(payload.get("objectIds"), "objectIds")


def _parse_iso_milliseconds(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError("accepted source_published_at is not text")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"accepted source_published_at is invalid: {value}") from exc
    if parsed.tzinfo is None:
        raise RuntimeError("accepted source_published_at lacks a timezone")
    return int(parsed.timestamp() * 1000)


def _accepted_release(connection: sqlite3.Connection, dataset_key: str) -> sqlite3.Row:
    rows = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.source_published_at, "
        "sr.feature_count, h.object_count "
        "FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "JOIN harvest_run h ON h.harvest_run_id = sr.harvest_run_id "
        "WHERE d.dataset_key = ? AND sr.lifecycle_status = 'accepted'",
        (dataset_key,),
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            f"dataset {dataset_key!r} must have exactly one accepted release, found {len(rows)}"
        )
    return rows[0]


def _accepted_object_ids(
    connection: sqlite3.Connection,
    profile: Mapping[str, Any],
    release_id: int,
    expected_feature_count: int,
    expected_inventory_count: int,
) -> tuple[list[int] | None, str | None]:
    table = DATASET_TABLES[profile["dataset_key"]]
    retained_count = connection.execute(
        f"SELECT COUNT(*) FROM {table} WHERE source_release_id = ?",
        (release_id,),
    ).fetchone()[0]
    if retained_count != expected_feature_count:
        raise RuntimeError(
            f"accepted feature count for {profile['dataset_key']} is inconsistent: "
            f"release declares {expected_feature_count}, table contains {retained_count}"
        )
    if retained_count != expected_inventory_count:
        return None, "accepted retained-feature count differs from harvested object inventory"

    object_field = profile["query"]["object_id_field"]
    identity_field = profile["query"]["identity_field"]
    rows = connection.execute(
        f"SELECT source_feature_id, attributes_json FROM {table} "
        "WHERE source_release_id = ? ORDER BY source_ordinal",
        (release_id,),
    )
    values: list[int] = []
    for row in rows:
        try:
            attributes = json.loads(row["attributes_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("accepted feature attributes_json is invalid") from exc
        candidate = attributes.get(object_field) if isinstance(attributes, Mapping) else None
        if candidate is None and object_field == identity_field:
            candidate = row["source_feature_id"]
        if isinstance(candidate, str) and candidate.isdigit():
            candidate = int(candidate)
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
            raise RuntimeError(f"accepted feature lacks a valid {object_field} value")
        values.append(candidate)
    if len(set(values)) != len(values):
        raise RuntimeError("accepted feature inventory contains duplicate object IDs")
    values.sort()
    return values, None


def load_accepted_state(database: Path, registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    database = Path(database).resolve()
    if not database.is_file():
        raise RuntimeError(f"Database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        result: dict[str, dict[str, Any]] = {}
        for profile in registry["profiles"]:
            release = _accepted_release(connection, profile["dataset_key"])
            object_count = release["object_count"]
            if (
                isinstance(object_count, bool)
                or not isinstance(object_count, int)
                or object_count < 0
            ):
                raise RuntimeError(
                    f"accepted harvest for {profile['dataset_key']} lacks a valid object_count"
                )
            feature_count = release["feature_count"]
            if (
                isinstance(feature_count, bool)
                or not isinstance(feature_count, int)
                or feature_count < 0
            ):
                raise RuntimeError(
                    f"accepted release for {profile['dataset_key']} lacks a valid feature_count"
                )
            accepted_ids, limitation = _accepted_object_ids(
                connection,
                profile,
                int(release["source_release_id"]),
                feature_count,
                object_count,
            )
            result[profile["profile_key"]] = {
                "accepted_release_key": release["release_key"],
                "accepted_feature_count": release["feature_count"],
                "accepted_object_count": object_count,
                "accepted_object_id_sha256": (
                    object_id_sha256(accepted_ids) if accepted_ids is not None else None
                ),
                "accepted_inventory_limitation": limitation,
                "accepted_source_published_ms": _parse_iso_milliseconds(
                    release["source_published_at"]
                ),
            }
        return result
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read accepted source state: {exc}") from exc
    finally:
        connection.close()


def _changed(
    accepted: Mapping[str, Any], live_ids: Sequence[int], live_last_edit_ms: int | None
) -> list[str]:
    reasons: list[str] = []
    if len(live_ids) != accepted["accepted_object_count"]:
        reasons.append(
            "object count changed from "
            f"{accepted['accepted_object_count']} to {len(live_ids)}"
        )
    accepted_digest = accepted["accepted_object_id_sha256"]
    live_digest = object_id_sha256(live_ids)
    if accepted_digest is not None and live_digest != accepted_digest:
        reasons.append("object-ID inventory changed")
    accepted_edit_ms = accepted["accepted_source_published_ms"]
    if live_last_edit_ms is not None and accepted_edit_ms is not None:
        if live_last_edit_ms > accepted_edit_ms:
            reasons.append("source last-edit timestamp advanced")
        elif live_last_edit_ms < accepted_edit_ms:
            raise SourceUnexpectedError("source last-edit timestamp moved backward")
    return reasons


def check_profile(
    profile: Mapping[str, Any],
    accepted: Mapping[str, Any],
    *,
    timeout_seconds: float,
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "profile_key": profile["profile_key"],
        "dataset_key": profile["dataset_key"],
        "update_group": profile.get("update_group"),
        **accepted,
        "live_object_count": None,
        "live_object_id_sha256": None,
        "live_comparison_edit_ms": None,
        "live_comparison_edit_origin": None,
        "change_reasons": [],
        "error": None,
    }
    try:
        metadata = fetcher(
            _metadata_url(profile),
            timeout_seconds=timeout_seconds,
            byte_limit=MAX_METADATA_BYTES,
        )
        metadata_summary = validate_layer_metadata(profile, metadata)
        inventory = fetcher(
            _inventory_url(profile),
            timeout_seconds=timeout_seconds,
            byte_limit=MAX_INVENTORY_BYTES,
        )
        live_ids = validate_inventory(profile, inventory)
        fixed_count = profile.get("expected_feature_count")
        if fixed_count is not None and len(live_ids) != fixed_count:
            raise SourceUnexpectedError(
                f"fixed feature count changed from {fixed_count} to {len(live_ids)}"
            )
        reasons = _changed(
            accepted,
            live_ids,
            metadata_summary["comparison_edit_ms"],
        )
        status = STATUS_NEW if reasons else STATUS_UP_TO_DATE
        result.update(
            {
                "status": status,
                "label": STATUS_LABELS[status],
                "live_object_count": len(live_ids),
                "live_object_id_sha256": object_id_sha256(live_ids),
                "live_comparison_edit_ms": metadata_summary["comparison_edit_ms"],
                "live_comparison_edit_origin": metadata_summary["comparison_edit_origin"],
                "change_reasons": reasons,
                "metadata": metadata_summary,
            }
        )
    except SourceUnavailableError as exc:
        result.update(
            {
                "status": STATUS_UNAVAILABLE,
                "label": STATUS_LABELS[STATUS_UNAVAILABLE],
                "error": str(exc),
            }
        )
    except (SourceUnexpectedError, RuntimeError) as exc:
        result.update(
            {
                "status": STATUS_UNEXPECTED,
                "label": STATUS_LABELS[STATUS_UNEXPECTED],
                "error": str(exc),
            }
        )
    return result


def aggregate_status(statuses: Sequence[str]) -> str:
    if not statuses:
        raise ValueError("At least one status is required")
    return max(statuses, key=lambda item: STATUS_PRECEDENCE[item])


def check_sources(
    database: Path,
    *,
    profile_dir: Path = PROFILE_DIR,
    timeout_seconds: float = 10.0,
    fetcher: Callable[..., Any] = fetch_json,
    checked_at: str | None = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0 or timeout_seconds > 120:
        raise RuntimeError("timeout_seconds must be greater than 0 and no more than 120")
    registry_result = _load_registry(profile_dir)
    registry = registry_result["registry"]
    accepted = load_accepted_state(database, registry)
    profiles = [
        check_profile(
            profile,
            accepted[profile["profile_key"]],
            timeout_seconds=timeout_seconds,
            fetcher=fetcher,
        )
        for profile in registry["profiles"]
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for profile_result in profiles:
        group = profile_result.get("update_group")
        if group is not None:
            groups.setdefault(group, []).append(profile_result)
    update_groups = []
    for group_key in sorted(groups):
        members = sorted(groups[group_key], key=lambda item: item["profile_key"])
        status = aggregate_status([item["status"] for item in members])
        update_groups.append(
            {
                "update_group": group_key,
                "members": [item["profile_key"] for item in members],
                "status": status,
                "label": STATUS_LABELS[status],
            }
        )
    overall = aggregate_status([item["status"] for item in profiles])
    return {
        "checked_at": checked_at or _utc_now(),
        "database": str(Path(database).resolve()),
        "registry_sha256": registry_result["registry_sha256"],
        "overall_status": overall,
        "overall_label": STATUS_LABELS[overall],
        "profiles": profiles,
        "update_groups": update_groups,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="check official source status")
    check.add_argument("database", type=Path)
    check.add_argument("--profile-dir", type=Path, default=PROFILE_DIR)
    check.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_sources(
            args.database,
            profile_dir=args.profile_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["overall_status"] in {STATUS_UP_TO_DATE, STATUS_NEW} else 1


if __name__ == "__main__":
    raise SystemExit(main())
