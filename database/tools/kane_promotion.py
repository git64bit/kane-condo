#!/usr/bin/env python3
"""Prepare, atomically promote, verify, and roll back Kane Condo source refreshes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

PROMOTION_SCHEMA = 1
ARTIFACT_DIRNAME = "promotion"
DATABASE_FILENAME = "kane-condo-promoted.gpkg"
MANIFEST_FILENAME = "promotion.json"
REQUIRED_FILES = {DATABASE_FILENAME, MANIFEST_FILENAME}
DATASET_ORDER = (
    "buildings",
    "county-boundary",
    "roads",
    "water-creeks",
    "water-fox-river",
)


def load_sibling(name: str):
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_kane_condo_{name}_promotion", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


kane_db = load_sibling("kane_db")
kane_provenance = load_sibling("kane_provenance")
kane_boundary = load_sibling("kane_boundary")
kane_map_layers = load_sibling("kane_map_layers")
kane_buildings = load_sibling("kane_buildings")
kane_project = load_sibling("kane_project_buildings")
kane_classifications = load_sibling("kane_classifications")
kane_reconcile = load_sibling("kane_building_reconcile")
kane_compare = load_sibling("kane_candidate_compare")
kane_road_candidate = load_sibling("kane_road_candidate")
kane_water_candidate = load_sibling("kane_water_candidate")
kane_boundary_candidate = load_sibling("kane_boundary_candidate")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_text(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_constant(token: str) -> None:
    raise ValueError(f"Invalid JSON constant: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    raw = path.read_bytes()
    if not raw:
        raise RuntimeError(f"JSON file is empty: {path.name}")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"JSON file must not contain a UTF-8 BOM: {path.name}")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Unable to parse JSON {path.name}: {exc}") from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_artifact_layout(directory: Path) -> None:
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError(f"Promotion directory is missing or is a symlink: {directory}")
    names: set[str] = set()
    for path in directory.iterdir():
        if path.is_symlink():
            raise RuntimeError(f"Promotion artifact contains a symlink: {path.name}")
        if not path.is_file():
            raise RuntimeError(f"Promotion artifact contains a non-file entry: {path.name}")
        names.add(path.name)
    if names != REQUIRED_FILES:
        raise RuntimeError(
            f"Promotion artifact file set mismatch; missing={sorted(REQUIRED_FILES - names)}, "
            f"extra={sorted(names - REQUIRED_FILES)}"
        )


def _database_snapshot(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        accepted = {
            str(row["dataset_key"]): {
                "release_key": str(row["release_key"]),
                "content_sha256": str(row["content_sha256"]),
                "feature_count": int(row["feature_count"]),
            }
            for row in connection.execute(
                "SELECT d.dataset_key, sr.release_key, sr.content_sha256, sr.feature_count "
                "FROM dataset d JOIN source_release sr ON sr.dataset_id = d.dataset_id "
                "WHERE sr.lifecycle_status = 'accepted' AND d.dataset_key IN "
                "('buildings','county-boundary','roads','water-creeks','water-fox-river') "
                "ORDER BY d.dataset_key"
            )
        }
        if set(accepted) != set(DATASET_ORDER):
            raise RuntimeError(
                f"Accepted source-release set is incomplete: {sorted(accepted)}"
            )
        classifications = {
            "current_count": int(connection.execute(
                "SELECT COUNT(*) FROM building_classification_current"
            ).fetchone()[0]),
            "event_count": int(connection.execute(
                "SELECT COUNT(*) FROM building_classification_event"
            ).fetchone()[0]),
            "current_sha256": sha256_value([
                list(row) for row in connection.execute(
                    "SELECT pb.building_key, c.classification, e.event_key "
                    "FROM building_classification_current c "
                    "JOIN project_building pb ON pb.project_building_id = c.project_building_id "
                    "JOIN building_classification_event e "
                    "ON e.classification_event_id = c.classification_event_id "
                    "ORDER BY pb.building_key"
                )
            ]),
            "history_sha256": sha256_value([
                list(row) for row in connection.execute(
                    "SELECT e.event_key, pb.building_key, e.event_kind, "
                    "e.previous_classification, e.new_classification, "
                    "COALESCE(pre.event_key,''), COALESCE(rev.event_key,'') "
                    "FROM building_classification_event e "
                    "JOIN project_building pb ON pb.project_building_id = e.project_building_id "
                    "LEFT JOIN building_classification_event pre "
                    "ON pre.classification_event_id = e.predecessor_event_id "
                    "LEFT JOIN building_classification_event rev "
                    "ON rev.classification_event_id = e.reverses_event_id "
                    "ORDER BY e.classification_event_id"
                )
            ]),
        }
        project = {
            "count": int(connection.execute("SELECT COUNT(*) FROM project_building").fetchone()[0]),
            "active_count": int(connection.execute(
                "SELECT COUNT(*) FROM project_building WHERE lifecycle_status = 'active'"
            ).fetchone()[0]),
            "mapping_count": int(connection.execute(
                "SELECT COUNT(*) FROM project_building_source_mapping"
            ).fetchone()[0]),
        }
        return {
            "accepted_releases": accepted,
            "classifications": classifications,
            "project": project,
        }
    finally:
        connection.close()


def _migrated_copy(source: Path, target: Path) -> None:
    _copy_file(source, target)
    kane_db.migrate_database(target)


def _validate_full_database(database: Path) -> None:
    validators = (
        kane_provenance.validate_database,
        kane_boundary.validate_database,
        kane_map_layers.validate_database,
        kane_buildings.validate_database,
        kane_project.validate_database,
        kane_classifications.validate_database,
    )
    for validator in validators:
        errors = list(validator(database))
        if errors:
            raise RuntimeError(
                f"Database failed {validator.__module__} validation:\n- "
                + "\n- ".join(errors)
            )
    _validate_promotion_history(database)


def _validate_promotion_history(database: Path) -> None:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT * FROM refresh_promotion_event ORDER BY promotion_event_id"
        ).fetchall()
        by_id = {int(row["promotion_event_id"]): row for row in rows}
        for row in rows:
            if not kane_db.valid_datetime(row["created_at"]):
                raise RuntimeError(
                    f"Promotion event {row['event_key']} has invalid created_at"
                )
            try:
                details = json.loads(str(row["details_json"]))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Promotion event {row['event_key']} details_json is invalid"
                ) from exc
            if canonical_text(details) != str(row["details_json"]):
                raise RuntimeError(
                    f"Promotion event {row['event_key']} details_json is not canonical"
                )
            if details.get("promotion_key") != row["promotion_key"]:
                raise RuntimeError(
                    f"Promotion event {row['event_key']} promotion key is inconsistent"
                )
            if details.get("promotion_plan_sha256") != row["promotion_plan_sha256"]:
                raise RuntimeError(
                    f"Promotion event {row['event_key']} plan hash is inconsistent"
                )
            if row["event_kind"] == "rollback":
                related = by_id.get(int(row["related_event_id"]))
                if related is None or related["event_kind"] != "promotion":
                    raise RuntimeError(
                        f"Rollback event {row['event_key']} has invalid related promotion"
                    )
                if related["promotion_key"] != row["promotion_key"]:
                    raise RuntimeError(
                        f"Rollback event {row['event_key']} crosses promotion keys"
                    )
    finally:
        connection.close()


def _release_rows(database: Path) -> dict[str, dict[str, sqlite3.Row]]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, dict[str, sqlite3.Row]] = {}
        for dataset_key in DATASET_ORDER:
            rows = connection.execute(
                "SELECT sr.* FROM source_release sr JOIN dataset d ON d.dataset_id = sr.dataset_id "
                "WHERE d.dataset_key = ? ORDER BY sr.source_release_id",
                (dataset_key,),
            ).fetchall()
            result[dataset_key] = {str(row["release_key"]): row for row in rows}
        return result
    finally:
        connection.close()


def _reconciliation_report(reconciliation_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    validation = kane_reconcile.validate_reconciliation(reconciliation_dir)
    if not validation["valid"] or not validation["ready_for_promotion"]:
        raise RuntimeError("Building reconciliation is not ready for promotion")
    report = _mapping(
        kane_reconcile.load_json(reconciliation_dir / kane_reconcile.REPORT_FILENAME),
        "Reconciliation report",
    )
    if report["ambiguity_count"] != 0 or report["candidate_mapping"]["unmapped_source_count"] != 0:
        raise RuntimeError("Promotion requires zero building ambiguities and complete mapping")
    return dict(validation), dict(report)


def _candidate_inputs(
    database_for_comparison: Path,
    road_dir: Path,
    water_dir: Path,
    boundary_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    road = kane_road_candidate.validate_candidate(road_dir)
    water = kane_water_candidate.validate_candidate(water_dir)
    boundary = kane_boundary_candidate.validate_candidate(boundary_dir)
    comparisons = {
        "roads": kane_compare.compare_candidate(database_for_comparison, road_dir),
        "water": kane_compare.compare_candidate(database_for_comparison, water_dir),
        "boundary": kane_compare.compare_candidate(database_for_comparison, boundary_dir),
    }
    return dict(road), dict(water), dict(boundary), comparisons


def _transition_plan(
    database: Path,
    reconciliation_report: Mapping[str, Any],
    road: Mapping[str, Any],
    water: Mapping[str, Any],
    boundary: Mapping[str, Any],
    comparisons: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = _database_snapshot(database)
    accepted = snapshot["accepted_releases"]
    water_components = _mapping(water["components"], "water components")
    new = {
        "buildings": str(reconciliation_report["candidate_release"]["release_key"]),
        "county-boundary": str(boundary["release_key"]),
        "roads": str(road["release_key"]),
        "water-creeks": str(water_components["water-creeks"]["release_key"]),
        "water-fox-river": str(water_components["water-fox-river"]["release_key"]),
    }
    rows = _release_rows(database)
    transitions: dict[str, Any] = {}
    comparison_hashes = {
        "buildings": str(reconciliation_report["comparison_sha256"]),
        "county-boundary": str(comparisons["boundary"]["comparison_sha256"]),
        "roads": str(comparisons["roads"]["comparison_sha256"]),
        "water-creeks": str(comparisons["water"]["comparison_sha256"]),
        "water-fox-river": str(comparisons["water"]["comparison_sha256"]),
    }
    for dataset_key in DATASET_ORDER:
        previous = str(accepted[dataset_key]["release_key"])
        candidate = new[dataset_key]
        candidate_row = rows[dataset_key].get(candidate)
        if candidate_row is None or candidate_row["lifecycle_status"] != "candidate":
            raise RuntimeError(
                f"Selected {dataset_key} release is not a registered candidate: {candidate}"
            )
        transitions[dataset_key] = {
            "previous_release_key": previous,
            "candidate_release_key": candidate,
            "comparison_sha256": comparison_hashes[dataset_key],
        }
    return transitions


def _plan_body(
    accepted_database_sha256: str,
    source_snapshot: Mapping[str, Any],
    reconciliation_report: Mapping[str, Any],
    transitions: Mapping[str, Any],
    road: Mapping[str, Any],
    water: Mapping[str, Any],
    boundary: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = {
        "buildings": {
            "reconciliation_key": reconciliation_report["reconciliation_key"],
            "reconciliation_sha256": reconciliation_report["reconciliation_sha256"],
            "candidate_content_sha256": reconciliation_report["candidate_release"]["content_sha256"],
            "candidate_manifest_sha256": reconciliation_report["candidate_release"]["manifest_sha256"],
        },
        "roads": {
            "candidate_content_sha256": road["content_sha256"],
            "candidate_manifest_sha256": road["manifest_sha256"],
            "object_count": road["object_count"],
            "feature_count": road["feature_count"],
            "excluded_count": road["excluded_count"],
        },
        "water": {
            "group_key": water["group_key"],
            "group_sha256": water["group_sha256"],
            "manifest_sha256": water["manifest_sha256"],
        },
        "boundary": {
            "candidate_content_sha256": boundary["content_sha256"],
            "candidate_manifest_sha256": boundary["manifest_sha256"],
            "candidate_bounds": boundary["candidate_bounds"],
        },
    }
    core = {
        "promotion_schema": PROMOTION_SCHEMA,
        "previous_database_sha256": accepted_database_sha256,
        "previous_state": source_snapshot,
        "reconciliation_key": reconciliation_report["reconciliation_key"],
        "reconciliation_sha256": reconciliation_report["reconciliation_sha256"],
        "release_transitions": {key: transitions[key] for key in DATASET_ORDER},
        "candidate_evidence": evidence,
        "authorization_kind": "explicit-command",
    }
    digest = sha256_value(core)
    return {
        **core,
        "promotion_key": f"kane-condo-promotion-{digest[:12]}",
        "promotion_plan_sha256": digest,
    }


def _promotion_event_details(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: plan[key]
        for key in (
            "promotion_schema", "previous_database_sha256", "previous_state",
            "reconciliation_key", "reconciliation_sha256", "release_transitions",
            "candidate_evidence", "authorization_kind", "promotion_key",
            "promotion_plan_sha256",
        )
    }


def _insert_promotion_event(
    connection: sqlite3.Connection,
    plan: Mapping[str, Any],
    prepared_candidate_sha256: str,
    *,
    created_at: str | None = None,
) -> str:
    created = created_at or kane_db.utc_now()
    event_key = f"{plan['promotion_key']}:promotion"
    connection.execute(
        "INSERT INTO refresh_promotion_event ("
        "event_key, promotion_key, event_kind, related_event_id, previous_database_sha256, "
        "prepared_candidate_sha256, promotion_plan_sha256, reconciliation_key, "
        "reconciliation_sha256, authorization_kind, details_json, created_at"
        ") VALUES (?, ?, 'promotion', NULL, ?, ?, ?, ?, ?, 'explicit-command', ?, ?)",
        (
            event_key,
            plan["promotion_key"],
            plan["previous_database_sha256"],
            prepared_candidate_sha256,
            plan["promotion_plan_sha256"],
            plan["reconciliation_key"],
            plan["reconciliation_sha256"],
            canonical_text(_promotion_event_details(plan)),
            created,
        ),
    )
    return created


def _promote_release_rows(
    database: Path,
    plan: Mapping[str, Any],
    prepared_candidate_sha256: str,
) -> str:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        now = kane_db.utc_now()
        for dataset_key in DATASET_ORDER:
            transition = plan["release_transitions"][dataset_key]
            previous = connection.execute(
                "SELECT sr.source_release_id, sr.lifecycle_status FROM source_release sr "
                "JOIN dataset d ON d.dataset_id = sr.dataset_id "
                "WHERE d.dataset_key = ? AND sr.release_key = ?",
                (dataset_key, transition["previous_release_key"]),
            ).fetchone()
            candidate = connection.execute(
                "SELECT sr.source_release_id, sr.lifecycle_status FROM source_release sr "
                "JOIN dataset d ON d.dataset_id = sr.dataset_id "
                "WHERE d.dataset_key = ? AND sr.release_key = ?",
                (dataset_key, transition["candidate_release_key"]),
            ).fetchone()
            if previous is None or previous["lifecycle_status"] != "accepted":
                raise RuntimeError(f"Previous {dataset_key} release is no longer accepted")
            if candidate is None or candidate["lifecycle_status"] != "candidate":
                raise RuntimeError(f"Selected {dataset_key} release is no longer candidate")
            connection.execute(
                "UPDATE source_release SET lifecycle_status = 'superseded', "
                "superseded_by_release_id = ? WHERE source_release_id = ?",
                (candidate["source_release_id"], previous["source_release_id"]),
            )
            connection.execute(
                "UPDATE source_release SET lifecycle_status = 'accepted', accepted_at = ?, "
                "superseded_by_release_id = NULL WHERE source_release_id = ?",
                (now, candidate["source_release_id"]),
            )
        event_created = _insert_promotion_event(
            connection, plan, prepared_candidate_sha256, created_at=now
        )
        connection.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name = 'refresh_promotion_event'",
            (now,),
        )
        connection.commit()
        return event_created
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _accepted_release_keys(database: Path) -> dict[str, str]:
    return {
        key: value["release_key"]
        for key, value in _database_snapshot(database)["accepted_releases"].items()
    }


def _verify_promoted_state(database: Path, manifest: Mapping[str, Any]) -> None:
    _validate_full_database(database)
    expected = {
        key: str(manifest["release_transitions"][key]["candidate_release_key"])
        for key in DATASET_ORDER
    }
    actual = _accepted_release_keys(database)
    if actual != expected:
        raise RuntimeError(
            f"Promoted accepted-release set is wrong: expected {expected}, found {actual}"
        )
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        event = connection.execute(
            "SELECT * FROM refresh_promotion_event WHERE event_key = ?",
            (f"{manifest['promotion_key']}:promotion",),
        ).fetchone()
        if event is None:
            raise RuntimeError("Promoted database is missing its promotion event")
        if event["promotion_plan_sha256"] != manifest["promotion_plan_sha256"]:
            raise RuntimeError("Promoted database promotion-event plan hash is wrong")
        if event["prepared_candidate_sha256"] != manifest["prepared_candidate_sha256"]:
            raise RuntimeError("Promoted database prepared-candidate hash is wrong")
        for dataset_key in DATASET_ORDER:
            transition = manifest["release_transitions"][dataset_key]
            rows = connection.execute(
                "SELECT sr.source_release_id, sr.release_key, sr.lifecycle_status, "
                "sr.superseded_by_release_id FROM source_release sr "
                "JOIN dataset d ON d.dataset_id = sr.dataset_id "
                "WHERE d.dataset_key = ? AND sr.release_key IN (?, ?)",
                (
                    dataset_key,
                    transition["previous_release_key"],
                    transition["candidate_release_key"],
                ),
            ).fetchall()
            by_key = {str(row["release_key"]): row for row in rows}
            previous = by_key.get(str(transition["previous_release_key"]))
            candidate = by_key.get(str(transition["candidate_release_key"]))
            if previous is None or candidate is None:
                raise RuntimeError(f"Promotion transition rows are missing for {dataset_key}")
            if previous["lifecycle_status"] != "superseded":
                raise RuntimeError(f"Previous {dataset_key} release is not superseded")
            if candidate["lifecycle_status"] != "accepted":
                raise RuntimeError(f"Candidate {dataset_key} release is not accepted")
            if int(previous["superseded_by_release_id"]) != int(candidate["source_release_id"]):
                raise RuntimeError(f"Previous {dataset_key} release has wrong supersession target")
    finally:
        connection.close()


def prepare_promotion(
    accepted_database: Path,
    reconciliation_dir: Path,
    road_dir: Path,
    water_dir: Path,
    boundary_dir: Path,
    output_root: Path,
) -> dict[str, Any]:
    accepted_database = accepted_database.resolve()
    reconciliation_dir = reconciliation_dir.resolve()
    road_dir = road_dir.resolve()
    water_dir = water_dir.resolve()
    boundary_dir = boundary_dir.resolve()
    output_root = output_root.resolve()
    if not accepted_database.is_file():
        raise RuntimeError(f"Accepted database does not exist: {accepted_database}")
    accepted_sha = sha256_file(accepted_database)
    reconciliation_validation, reconciliation_report = _reconciliation_report(reconciliation_dir)
    if reconciliation_report["accepted_database_sha256"] != accepted_sha:
        raise RuntimeError("Reconciliation was not prepared from the current accepted database")
    with tempfile.TemporaryDirectory(prefix="kane-promotion-source-") as temp_root:
        migrated_source = Path(temp_root) / "accepted-current-schema.gpkg"
        _migrated_copy(accepted_database, migrated_source)
        _validate_full_database(migrated_source)
        source_snapshot = _database_snapshot(migrated_source)
        road, water, boundary, comparisons = _candidate_inputs(
            migrated_source, road_dir, water_dir, boundary_dir
        )
        transitions = _transition_plan(
            migrated_source,
            reconciliation_report,
            road,
            water,
            boundary,
            comparisons,
        )
    plan = _plan_body(
        accepted_sha,
        source_snapshot,
        reconciliation_report,
        transitions,
        road,
        water,
        boundary,
    )
    final_dir = output_root / ARTIFACT_DIRNAME / str(plan["promotion_key"])
    if final_dir.exists():
        validation = validate_promotion(final_dir)
        return {**validation, "promotion_directory": str(final_dir), "existing": True}
    parent = final_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".kane-promotion-", dir=parent))
    try:
        candidate_database = temp_dir / DATABASE_FILENAME
        reconciliation_database = reconciliation_dir / kane_reconcile.DATABASE_FILENAME
        _copy_file(reconciliation_database, candidate_database)
        kane_db.migrate_database(candidate_database)
        kane_map_layers.import_map_layers(
            candidate_database,
            [
                (str(road["release_key"]), road_dir / "roads.geojson"),
                (
                    str(water["components"]["water-creeks"]["release_key"]),
                    water_dir / "creeks.geojson",
                ),
                (
                    str(water["components"]["water-fox-river"]["release_key"]),
                    water_dir / "fox-river.geojson",
                ),
            ],
        )
        kane_boundary.import_boundary(
            candidate_database,
            str(boundary["release_key"]),
            boundary_dir / "boundary.geojson",
        )
        before_promotion = _database_snapshot(candidate_database)
        if before_promotion["accepted_releases"] != source_snapshot["accepted_releases"]:
            raise RuntimeError("Candidate preparation changed accepted releases before promotion")
        if before_promotion["classifications"] != source_snapshot["classifications"]:
            raise RuntimeError("Candidate preparation changed authoritative classifications")
        prepared_sha = sha256_file(candidate_database)
        event_created_at = _promote_release_rows(candidate_database, plan, prepared_sha)
        _verify_promoted_state(candidate_database, {**plan, "prepared_candidate_sha256": prepared_sha})
        after = _database_snapshot(candidate_database)
        if after["classifications"] != source_snapshot["classifications"]:
            raise RuntimeError("Promotion candidate changed authoritative classifications")
        database_info = {
            "filename": DATABASE_FILENAME,
            "byte_length": candidate_database.stat().st_size,
            "sha256": sha256_file(candidate_database),
        }
        manifest = {
            **plan,
            "prepared_candidate_sha256": prepared_sha,
            "promotion_event_created_at": event_created_at,
            "promoted_state": after,
            "final_candidate_database": database_info,
        }
        (temp_dir / MANIFEST_FILENAME).write_bytes(canonical_bytes(manifest) + b"\n")
        os.replace(temp_dir, final_dir)
        _fsync_directory(parent)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    validation = validate_promotion(final_dir)
    return {**validation, "promotion_directory": str(final_dir), "existing": False}


def validate_promotion(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    _validate_artifact_layout(directory)
    manifest_path = directory / MANIFEST_FILENAME
    manifest_raw = manifest_path.read_bytes()
    manifest = _mapping(load_json(manifest_path), "Promotion manifest")
    if manifest_raw != canonical_bytes(manifest) + b"\n":
        raise RuntimeError("Promotion manifest is not canonical JSON")
    required = {
        "promotion_schema", "previous_database_sha256", "previous_state",
        "reconciliation_key", "reconciliation_sha256", "release_transitions",
        "candidate_evidence", "authorization_kind", "promotion_key",
        "promotion_plan_sha256", "prepared_candidate_sha256",
        "promotion_event_created_at", "promoted_state", "final_candidate_database",
    }
    if set(manifest) != required:
        raise RuntimeError("Promotion manifest has an unexpected key set")
    if manifest["promotion_schema"] != PROMOTION_SCHEMA:
        raise RuntimeError(f"promotion_schema must be {PROMOTION_SCHEMA}")
    plan = {
        key: manifest[key]
        for key in (
            "promotion_schema", "previous_database_sha256", "previous_state",
            "reconciliation_key", "reconciliation_sha256", "release_transitions",
            "candidate_evidence", "authorization_kind",
        )
    }
    if manifest["promotion_plan_sha256"] != sha256_value(plan):
        raise RuntimeError("Promotion plan SHA-256 is invalid")
    if manifest["promotion_key"] != f"kane-condo-promotion-{manifest['promotion_plan_sha256'][:12]}":
        raise RuntimeError("Promotion key is invalid")
    if set(manifest["release_transitions"]) != set(DATASET_ORDER):
        raise RuntimeError("Promotion release transition set is incomplete")
    if manifest["authorization_kind"] != "explicit-command":
        raise RuntimeError("Promotion authorization kind is invalid")
    if not kane_db.valid_datetime(manifest["promotion_event_created_at"]):
        raise RuntimeError("Promotion event timestamp is invalid")
    database_info = _mapping(manifest["final_candidate_database"], "final_candidate_database")
    if set(database_info) != {"filename", "byte_length", "sha256"}:
        raise RuntimeError("final_candidate_database has an unexpected key set")
    if database_info["filename"] != DATABASE_FILENAME:
        raise RuntimeError("Promotion database filename is invalid")
    database = directory / DATABASE_FILENAME
    if database.stat().st_size != database_info["byte_length"]:
        raise RuntimeError("Promotion database byte length is invalid")
    if sha256_file(database) != database_info["sha256"]:
        raise RuntimeError("Promotion database SHA-256 is invalid")
    _verify_promoted_state(database, manifest)
    if _database_snapshot(database) != manifest["promoted_state"]:
        raise RuntimeError("Promotion manifest promoted_state does not match candidate database")
    return {
        "valid": True,
        "promotion_key": manifest["promotion_key"],
        "promotion_plan_sha256": manifest["promotion_plan_sha256"],
        "previous_database_sha256": manifest["previous_database_sha256"],
        "prepared_candidate_sha256": manifest["prepared_candidate_sha256"],
        "promoted_database_sha256": database_info["sha256"],
        "manifest_sha256": sha256_bytes(manifest_raw),
        "release_transitions": manifest["release_transitions"],
        "reconciliation_key": manifest["reconciliation_key"],
    }


def promotion_info(directory: Path) -> dict[str, Any]:
    validation = validate_promotion(directory)
    manifest = _mapping(load_json(directory.resolve() / MANIFEST_FILENAME), "Promotion manifest")
    return {
        **validation,
        "candidate_evidence": manifest["candidate_evidence"],
        "previous_state": manifest["previous_state"],
    }


def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_bytes(dict(value)) + b"\n")
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _backup_directory(backup_root: Path, promotion_key: str) -> Path:
    return backup_root.resolve() / promotion_key


def _restore_database_from_backup(
    active_database: Path,
    backup_database: Path,
    manifest: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise RuntimeError("Rollback reason must not be empty")
    parent = active_database.parent
    temp = parent / f".{active_database.stem}.{manifest['promotion_key']}.rollback.gpkg"
    temp.unlink(missing_ok=True)
    _copy_file(backup_database, temp)
    kane_db.migrate_database(temp)
    connection = sqlite3.connect(temp)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        promotion_event = connection.execute(
            "SELECT promotion_event_id FROM refresh_promotion_event WHERE event_key = ?",
            (f"{manifest['promotion_key']}:promotion",),
        ).fetchone()
        if promotion_event is None:
            _insert_promotion_event(
                connection,
                manifest,
                str(manifest["prepared_candidate_sha256"]),
                created_at=str(manifest["promotion_event_created_at"]),
            )
            promotion_event_id = int(connection.execute(
                "SELECT promotion_event_id FROM refresh_promotion_event WHERE event_key = ?",
                (f"{manifest['promotion_key']}:promotion",),
            ).fetchone()[0])
        else:
            promotion_event_id = int(promotion_event[0])
        rollback_body = {
            "promotion_key": manifest["promotion_key"],
            "promotion_plan_sha256": manifest["promotion_plan_sha256"],
            "reason": reason,
            "restored_release_keys": {
                key: manifest["release_transitions"][key]["previous_release_key"]
                for key in DATASET_ORDER
            },
        }
        rollback_digest = sha256_value(rollback_body)
        event_key = f"{manifest['promotion_key']}:rollback:{rollback_digest[:12]}"
        existing = connection.execute(
            "SELECT 1 FROM refresh_promotion_event WHERE event_key = ?", (event_key,)
        ).fetchone()
        if existing is None:
            now = kane_db.utc_now()
            connection.execute(
                "INSERT INTO refresh_promotion_event ("
                "event_key, promotion_key, event_kind, related_event_id, previous_database_sha256, "
                "prepared_candidate_sha256, promotion_plan_sha256, reconciliation_key, "
                "reconciliation_sha256, authorization_kind, details_json, created_at"
                ") VALUES (?, ?, 'rollback', ?, ?, ?, ?, ?, ?, 'explicit-command', ?, ?)",
                (
                    event_key,
                    manifest["promotion_key"],
                    promotion_event_id,
                    manifest["previous_database_sha256"],
                    manifest["prepared_candidate_sha256"],
                    manifest["promotion_plan_sha256"],
                    manifest["reconciliation_key"],
                    manifest["reconciliation_sha256"],
                    canonical_text({**rollback_body, "event_kind": "rollback"}),
                    now,
                ),
            )
            connection.execute(
                "UPDATE gpkg_contents SET last_change = ? WHERE table_name = 'refresh_promotion_event'",
                (now,),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        temp.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    _validate_full_database(temp)
    expected_previous = {
        key: str(manifest["release_transitions"][key]["previous_release_key"])
        for key in DATASET_ORDER
    }
    if _accepted_release_keys(temp) != expected_previous:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Rollback database does not restore the previous accepted releases")
    os.replace(temp, active_database)
    _fsync_directory(parent)
    _validate_full_database(active_database)
    return {
        "rolled_back": True,
        "promotion_key": manifest["promotion_key"],
        "reason": reason,
        "active_database_sha256": sha256_file(active_database),
        "restored_release_keys": expected_previous,
    }


def promote_database(
    active_database: Path,
    promotion_dir: Path,
    backup_root: Path,
    *,
    post_verify=None,
) -> dict[str, Any]:
    active_database = active_database.resolve()
    promotion_dir = promotion_dir.resolve()
    backup_root = backup_root.resolve()
    validation = validate_promotion(promotion_dir)
    manifest = _mapping(load_json(promotion_dir / MANIFEST_FILENAME), "Promotion manifest")
    candidate_database = promotion_dir / DATABASE_FILENAME
    if not active_database.is_file():
        raise RuntimeError(f"Active database does not exist: {active_database}")
    current_sha = sha256_file(active_database)
    if current_sha == validation["promoted_database_sha256"]:
        _verify_promoted_state(active_database, manifest)
        return {
            "valid": True,
            "promoted": True,
            "existing": True,
            "promotion_key": manifest["promotion_key"],
            "active_database_sha256": current_sha,
        }
    if current_sha != manifest["previous_database_sha256"]:
        raise RuntimeError(
            "Active database changed after promotion preparation; rebuild reconciliation/promotion"
        )
    backup_dir = _backup_directory(backup_root, str(manifest["promotion_key"]))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_database = backup_dir / "previous.gpkg"
    if backup_database.exists():
        if sha256_file(backup_database) != current_sha:
            raise RuntimeError("Existing rollback backup does not match the active database")
    else:
        _copy_file(active_database, backup_database)
        if sha256_file(backup_database) != current_sha:
            raise RuntimeError("Rollback backup SHA-256 does not match active database")
    _fsync_directory(backup_dir)
    temp = active_database.parent / f".{active_database.name}.{manifest['promotion_key']}.promote.tmp"
    temp.unlink(missing_ok=True)
    _copy_file(candidate_database, temp)
    if sha256_file(temp) != validation["promoted_database_sha256"]:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Staged promotion database SHA-256 changed during copy")
    if sha256_file(active_database) != manifest["previous_database_sha256"]:
        temp.unlink(missing_ok=True)
        raise RuntimeError("Active database changed immediately before atomic promotion")
    os.replace(temp, active_database)
    _fsync_directory(active_database.parent)
    verifier = post_verify or _verify_promoted_state
    try:
        verifier(active_database, manifest)
    except Exception as exc:
        rollback = _restore_database_from_backup(
            active_database,
            backup_database,
            manifest,
            reason="automatic-post-verification-failure",
        )
        receipt = {
            "promotion_key": manifest["promotion_key"],
            "promoted": False,
            "rolled_back": True,
            "error": str(exc),
            "rollback": rollback,
            "backup_database_sha256": sha256_file(backup_database),
        }
        _write_receipt(backup_dir / "activation.json", receipt)
        raise RuntimeError(
            "Post-promotion verification failed; prior accepted state was restored: " + str(exc)
        ) from exc
    active_sha = sha256_file(active_database)
    receipt = {
        "promotion_key": manifest["promotion_key"],
        "promoted": True,
        "rolled_back": False,
        "active_database_sha256": active_sha,
        "backup_database_sha256": sha256_file(backup_database),
        "previous_database_sha256": manifest["previous_database_sha256"],
    }
    _write_receipt(backup_dir / "activation.json", receipt)
    _fsync_directory(backup_dir)
    return {
        "valid": True,
        "promoted": True,
        "existing": False,
        "promotion_key": manifest["promotion_key"],
        "active_database_sha256": active_sha,
        "backup_database": str(backup_database),
        "backup_database_sha256": receipt["backup_database_sha256"],
        "release_keys": _accepted_release_keys(active_database),
    }


def rollback_database(
    active_database: Path,
    promotion_dir: Path,
    backup_root: Path,
    reason: str,
) -> dict[str, Any]:
    active_database = active_database.resolve()
    promotion_dir = promotion_dir.resolve()
    backup_root = backup_root.resolve()
    validate_promotion(promotion_dir)
    manifest = _mapping(load_json(promotion_dir / MANIFEST_FILENAME), "Promotion manifest")
    backup_dir = _backup_directory(backup_root, str(manifest["promotion_key"]))
    backup_database = backup_dir / "previous.gpkg"
    if not backup_database.is_file():
        raise RuntimeError(f"Rollback backup is missing: {backup_database}")
    if sha256_file(backup_database) != manifest["previous_database_sha256"]:
        raise RuntimeError("Rollback backup does not match the pre-promotion database SHA-256")
    current_snapshot = _database_snapshot(active_database)
    current_keys = {
        key: value["release_key"]
        for key, value in current_snapshot["accepted_releases"].items()
    }
    previous_keys = {
        key: str(manifest["release_transitions"][key]["previous_release_key"])
        for key in DATASET_ORDER
    }
    if current_keys == previous_keys:
        _validate_full_database(active_database)
        return {
            "valid": True,
            "rolled_back": True,
            "existing": True,
            "promotion_key": manifest["promotion_key"],
            "active_database_sha256": sha256_file(active_database),
            "release_keys": current_keys,
        }
    promoted_keys = {
        key: str(manifest["release_transitions"][key]["candidate_release_key"])
        for key in DATASET_ORDER
    }
    if current_keys != promoted_keys:
        raise RuntimeError("Active database is neither the promoted nor previous release set")
    promoted_state = _mapping(manifest["promoted_state"], "promoted_state")
    if current_snapshot["classifications"] != promoted_state["classifications"]:
        raise RuntimeError(
            "Rollback refused because authoritative classifications changed after promotion"
        )
    if current_snapshot["project"] != promoted_state["project"]:
        raise RuntimeError(
            "Rollback refused because project-building state changed after promotion"
        )
    retained_promoted = backup_dir / "promoted-before-rollback.gpkg"
    if retained_promoted.exists():
        if sha256_file(retained_promoted) != sha256_file(active_database):
            raise RuntimeError("Existing retained promoted database does not match active state")
    else:
        _copy_file(active_database, retained_promoted)
    result = _restore_database_from_backup(
        active_database, backup_database, manifest, reason=reason
    )
    receipt = {
        **result,
        "backup_database_sha256": sha256_file(backup_database),
        "retained_promoted_database_sha256": sha256_file(retained_promoted),
    }
    _write_receipt(backup_dir / "rollback.json", receipt)
    _fsync_directory(backup_dir)
    return {"valid": True, **receipt}


def database_promotion_info(database: Path) -> dict[str, Any]:
    _validate_full_database(database)
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        events = []
        for row in connection.execute(
            "SELECT event_key, promotion_key, event_kind, previous_database_sha256, "
            "prepared_candidate_sha256, promotion_plan_sha256, reconciliation_key, "
            "reconciliation_sha256, authorization_kind, details_json, created_at "
            "FROM refresh_promotion_event ORDER BY promotion_event_id"
        ):
            events.append({
                "event_key": row["event_key"],
                "promotion_key": row["promotion_key"],
                "event_kind": row["event_kind"],
                "previous_database_sha256": row["previous_database_sha256"],
                "prepared_candidate_sha256": row["prepared_candidate_sha256"],
                "promotion_plan_sha256": row["promotion_plan_sha256"],
                "reconciliation_key": row["reconciliation_key"],
                "reconciliation_sha256": row["reconciliation_sha256"],
                "authorization_kind": row["authorization_kind"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            })
        return {
            "valid": True,
            "database_sha256": sha256_file(database),
            "accepted_release_keys": _accepted_release_keys(database),
            "promotion_events": events,
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Build a fully promoted candidate database artifact")
    prepare.add_argument("database", type=Path)
    prepare.add_argument("reconciliation_directory", type=Path)
    prepare.add_argument("road_candidate_directory", type=Path)
    prepare.add_argument("water_candidate_directory", type=Path)
    prepare.add_argument("boundary_candidate_directory", type=Path)
    prepare.add_argument("output_root", type=Path)
    validate = sub.add_parser("validate", help="Validate a promotion artifact")
    validate.add_argument("promotion_directory", type=Path)
    info = sub.add_parser("info", help="Inspect a promotion artifact")
    info.add_argument("promotion_directory", type=Path)
    promote = sub.add_parser("promote", help="Atomically activate a validated promotion artifact")
    promote.add_argument("database", type=Path)
    promote.add_argument("promotion_directory", type=Path)
    promote.add_argument("backup_root", type=Path)
    rollback = sub.add_parser("rollback", help="Atomically restore the retained prior accepted state")
    rollback.add_argument("database", type=Path)
    rollback.add_argument("promotion_directory", type=Path)
    rollback.add_argument("backup_root", type=Path)
    rollback.add_argument("reason")
    history = sub.add_parser("history", help="Inspect authoritative promotion history")
    history.add_argument("database", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_promotion(
                args.database,
                args.reconciliation_directory,
                args.road_candidate_directory,
                args.water_candidate_directory,
                args.boundary_candidate_directory,
                args.output_root,
            )
        elif args.command == "validate":
            result = validate_promotion(args.promotion_directory)
        elif args.command == "info":
            result = promotion_info(args.promotion_directory)
        elif args.command == "promote":
            result = promote_database(
                args.database, args.promotion_directory, args.backup_root
            )
        elif args.command == "rollback":
            result = rollback_database(
                args.database,
                args.promotion_directory,
                args.backup_root,
                args.reason,
            )
        elif args.command == "history":
            result = database_promotion_info(args.database)
        else:
            raise RuntimeError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
