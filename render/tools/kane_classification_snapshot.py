#!/usr/bin/env python3
"""Build the deterministic Batch 031 Kane Condo classification snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Mapping, Sequence

FORMAT = "kane-condo-classification-snapshot"
VERSION = 1
DATASET_KEY = "buildings"
CLASSIFICATIONS = ("unclassified", "other", "condominium", "apartments")
EXPLICIT_CLASSIFICATIONS = CLASSIFICATIONS[1:]
BUILDING_KEY_PATTERN = re.compile(r"^kcb-[0-9a-f]{64}$")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_keys(value: object, expected: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Classification snapshot {label} is not an object")
    actual = set(value)
    if actual != expected:
        raise RuntimeError(
            f"Classification snapshot {label} fields are invalid: "
            f"expected {sorted(expected)!r}, found {sorted(actual)!r}"
        )
    return value


def load_snapshot_state(database: Path) -> dict[str, object]:
    database = database.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        releases = connection.execute(
            "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count "
            "FROM source_release sr "
            "JOIN dataset d ON d.dataset_id = sr.dataset_id "
            "WHERE d.dataset_key = ? AND sr.lifecycle_status = 'accepted' "
            "ORDER BY sr.source_release_id",
            (DATASET_KEY,),
        ).fetchall()
        if len(releases) != 1:
            raise RuntimeError(
                f"Accepted building-release count is {len(releases)}; expected 1"
            )
        release = releases[0]
        rows = connection.execute(
            "SELECT sb.source_building_id, sb.source_ordinal, "
            "COUNT(DISTINCT m.project_building_id) AS confirmed_mapping_count, "
            "MIN(pb.project_building_id) AS project_building_id, "
            "MIN(pb.building_key) AS building_key, "
            "MIN(pb.lifecycle_status) AS lifecycle_status "
            "FROM source_building sb "
            "LEFT JOIN project_building_source_mapping m "
            "ON m.source_building_id = sb.source_building_id "
            "AND m.mapping_status = 'confirmed' "
            "LEFT JOIN project_building pb "
            "ON pb.project_building_id = m.project_building_id "
            "WHERE sb.source_release_id = ? "
            "GROUP BY sb.source_building_id "
            "ORDER BY sb.source_ordinal",
            (release["source_release_id"],),
        ).fetchall()

        project_to_key: dict[int, str] = {}
        building_keys: list[str] = []
        for expected_ordinal, row in enumerate(rows, 1):
            if int(row["source_ordinal"]) != expected_ordinal:
                raise RuntimeError(
                    "Accepted building source ordinals are not contiguous: "
                    f"expected {expected_ordinal}, found {row['source_ordinal']}"
                )
            mapping_count = int(row["confirmed_mapping_count"])
            if mapping_count != 1:
                raise RuntimeError(
                    f"Accepted building ordinal {expected_ordinal} has {mapping_count} "
                    "confirmed project mappings; expected 1"
                )
            if str(row["lifecycle_status"]) != "active":
                raise RuntimeError(
                    f"Accepted building ordinal {expected_ordinal} maps to non-active "
                    f"project building {row['building_key']}"
                )
            building_key = str(row["building_key"])
            if BUILDING_KEY_PATTERN.fullmatch(building_key) is None:
                raise RuntimeError(
                    f"Accepted building ordinal {expected_ordinal} has invalid building_key"
                )
            project_id = int(row["project_building_id"])
            if project_id in project_to_key:
                raise RuntimeError(
                    f"Project building {building_key} is mapped to more than one accepted footprint"
                )
            project_to_key[project_id] = building_key
            building_keys.append(building_key)

        if int(release["feature_count"]) != len(rows):
            raise RuntimeError(
                f"Accepted building release feature_count is {release['feature_count']}; "
                f"stored feature count is {len(rows)}"
            )
        if not rows:
            raise RuntimeError("Accepted building release contains no stored features")
        if len(set(building_keys)) != len(building_keys):
            raise RuntimeError("Accepted building mappings contain duplicate building_key values")

        current_rows = connection.execute(
            "SELECT current.project_building_id, current.classification, "
            "current.classification_event_id, pb.building_key, pb.lifecycle_status, "
            "event.project_building_id AS event_project_building_id, "
            "event.new_classification AS event_classification "
            "FROM building_classification_current current "
            "JOIN project_building pb "
            "ON pb.project_building_id = current.project_building_id "
            "LEFT JOIN building_classification_event event "
            "ON event.classification_event_id = current.classification_event_id "
            "ORDER BY pb.building_key"
        ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Unable to read classification snapshot state: {exc}") from exc
    finally:
        connection.close()

    records: list[list[str]] = []
    non_rendered_explicit_count = 0
    for row in current_rows:
        project_id = int(row["project_building_id"])
        classification = str(row["classification"])
        if classification not in EXPLICIT_CLASSIFICATIONS:
            raise RuntimeError(
                f"Project building {row['building_key']} has invalid explicit classification"
            )
        if row["event_project_building_id"] != project_id or row["event_classification"] != classification:
            raise RuntimeError(
                f"Project building {row['building_key']} current classification does not match its event"
            )
        building_key = project_to_key.get(project_id)
        if building_key is None:
            non_rendered_explicit_count += 1
            continue
        if str(row["lifecycle_status"]) != "active":
            raise RuntimeError(
                f"Rendered project building {building_key} is not active"
            )
        records.append([building_key, classification])

    records.sort(key=lambda record: record[0])
    sorted_keys = sorted(building_keys)
    identity_bytes = canonical_json_bytes(sorted_keys)
    record_bytes = canonical_json_bytes(records)
    counts = {classification: 0 for classification in CLASSIFICATIONS}
    for _building_key, classification in records:
        counts[classification] += 1
    counts["unclassified"] = len(sorted_keys) - len(records)

    return {
        "classifications": list(CLASSIFICATIONS),
        "default_classification": "unclassified",
        "explicit": {
            "count": len(records),
            "counts": counts,
            "non_rendered_explicit_count": non_rendered_explicit_count,
            "records": records,
            "records_sha256": sha256_bytes(record_bytes),
        },
        "format": FORMAT,
        "identity": {
            "field": "building_key",
            "kind": "kane-condo-project-building",
            "render_building_count": len(sorted_keys),
            "render_identity_sha256": sha256_bytes(identity_bytes),
        },
        "source": {
            "dataset_key": DATASET_KEY,
            "feature_count": int(release["feature_count"]),
            "release_content_sha256": str(release["content_sha256"]),
            "release_key": str(release["release_key"]),
        },
        "version": VERSION,
    }


def validate_snapshot_document(document: object) -> dict[str, object]:
    top = _require_keys(
        document,
        {
            "classifications",
            "default_classification",
            "explicit",
            "format",
            "identity",
            "source",
            "version",
        },
        "document",
    )
    if top["format"] != FORMAT or top["version"] != VERSION:
        raise RuntimeError("Classification snapshot format/version is unsupported")
    if top["classifications"] != list(CLASSIFICATIONS):
        raise RuntimeError("Classification snapshot class contract is invalid")
    if top["default_classification"] != "unclassified":
        raise RuntimeError("Classification snapshot default classification is invalid")

    identity = _require_keys(
        top["identity"],
        {"field", "kind", "render_building_count", "render_identity_sha256"},
        "identity",
    )
    if identity["field"] != "building_key" or identity["kind"] != "kane-condo-project-building":
        raise RuntimeError("Classification snapshot identity contract is invalid")
    render_count = int(identity["render_building_count"])
    if render_count < 0:
        raise RuntimeError("Classification snapshot render building count is invalid")
    if not isinstance(identity["render_identity_sha256"], str) or len(identity["render_identity_sha256"]) != 64:
        raise RuntimeError("Classification snapshot render identity SHA-256 is invalid")

    source = _require_keys(
        top["source"],
        {"dataset_key", "feature_count", "release_content_sha256", "release_key"},
        "source",
    )
    if source["dataset_key"] != DATASET_KEY or int(source["feature_count"]) != render_count:
        raise RuntimeError("Classification snapshot source identity is inconsistent")
    if not isinstance(source["release_key"], str) or not source["release_key"]:
        raise RuntimeError("Classification snapshot release key is invalid")
    if not isinstance(source["release_content_sha256"], str) or len(source["release_content_sha256"]) != 64:
        raise RuntimeError("Classification snapshot release content SHA-256 is invalid")

    explicit = _require_keys(
        top["explicit"],
        {"count", "counts", "non_rendered_explicit_count", "records", "records_sha256"},
        "explicit",
    )
    records = explicit["records"]
    if not isinstance(records, list):
        raise RuntimeError("Classification snapshot explicit records are not an array")
    normalized: list[list[str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            raise RuntimeError("Classification snapshot record is not a two-item array")
        building_key, classification = record
        if not isinstance(building_key, str) or BUILDING_KEY_PATTERN.fullmatch(building_key) is None:
            raise RuntimeError("Classification snapshot record building_key is invalid")
        if building_key in seen:
            raise RuntimeError("Classification snapshot contains duplicate building_key")
        seen.add(building_key)
        if classification not in EXPLICIT_CLASSIFICATIONS:
            raise RuntimeError("Classification snapshot record contains invalid explicit classification")
        normalized.append([building_key, str(classification)])
    if normalized != sorted(normalized, key=lambda record: record[0]):
        raise RuntimeError("Classification snapshot records are not sorted by building_key")
    if int(explicit["count"]) != len(normalized) or len(normalized) > render_count:
        raise RuntimeError("Classification snapshot explicit count is invalid")
    if int(explicit["non_rendered_explicit_count"]) < 0:
        raise RuntimeError("Classification snapshot non-rendered explicit count is invalid")
    if explicit["records_sha256"] != sha256_bytes(canonical_json_bytes(normalized)):
        raise RuntimeError("Classification snapshot record SHA-256 is invalid")

    counts = explicit["counts"]
    if not isinstance(counts, Mapping) or set(counts) != set(CLASSIFICATIONS):
        raise RuntimeError("Classification snapshot class counts are invalid")
    expected_counts = {classification: 0 for classification in CLASSIFICATIONS}
    for _building_key, classification in normalized:
        expected_counts[classification] += 1
    expected_counts["unclassified"] = render_count - len(normalized)
    actual_counts = {key: int(counts[key]) for key in CLASSIFICATIONS}
    if actual_counts != expected_counts:
        raise RuntimeError("Classification snapshot class counts are inconsistent")
    return dict(top)


def read_snapshot_bytes(data: bytes) -> dict[str, object]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Classification snapshot is invalid JSON: {exc}") from exc
    if canonical_json_bytes(document) != data:
        raise RuntimeError("Classification snapshot is not canonical JSON")
    return validate_snapshot_document(document)


def write_snapshot(database: Path, output: Path) -> dict[str, object]:
    database = database.resolve()
    output = output.resolve()
    if output == database:
        raise RuntimeError("Classification snapshot output must not replace the authoritative database")
    document = load_snapshot_state(database)
    payload = canonical_json_bytes(document)
    read_snapshot_bytes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "byte_length": len(payload),
        "explicit_count": document["explicit"]["count"],
        "output_file": str(output),
        "render_building_count": document["identity"]["render_building_count"],
        "sha256": sha256_bytes(payload),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build deterministic classification snapshot")
    build.add_argument("database", type=Path)
    build.add_argument("output", type=Path)
    inspect = subparsers.add_parser("inspect", help="validate and summarize a classification snapshot")
    inspect.add_argument("snapshot", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = write_snapshot(args.database, args.output)
        else:
            data = args.snapshot.resolve().read_bytes()
            document = read_snapshot_bytes(data)
            result = {
                "byte_length": len(data),
                "classification_counts": document["explicit"]["counts"],
                "explicit_count": document["explicit"]["count"],
                "render_building_count": document["identity"]["render_building_count"],
                "render_identity_sha256": document["identity"]["render_identity_sha256"],
                "sha256": sha256_bytes(data),
                "source_release": document["source"]["release_key"],
            }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
