#!/usr/bin/env python3
"""Build and validate a reconciled Kane Condo building candidate database."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping, Sequence

RECONCILIATION_SCHEMA = 1
RECONCILIATION_DIRNAME = "reconciliation"
DATABASE_FILENAME = "kane-condo-candidate.gpkg"
REPORT_FILENAME = "reconciliation.json"
REQUIRED_FILES = {DATABASE_FILENAME, REPORT_FILENAME}
OVERLAP_GRID_DEGREES = 0.01
MAX_GRID_CELLS_PER_BOUNDS = 4096


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
kane_buildings = load_sibling("kane_buildings")
kane_project = load_sibling("kane_project_buildings")
kane_classifications = load_sibling("kane_classifications")
kane_candidate = load_sibling("kane_building_candidate")
kane_compare = load_sibling("kane_candidate_compare")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


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


def _read_only(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _database_backup(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def _classification_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    current = [
        list(row)
        for row in connection.execute(
            "SELECT project_building_id, classification, classification_event_id "
            "FROM building_classification_current ORDER BY project_building_id"
        )
    ]
    events = [
        list(row)
        for row in connection.execute(
            "SELECT classification_event_id, event_key, project_building_id, "
            "predecessor_event_id, event_kind, previous_classification, "
            "new_classification, reverses_event_id, created_at "
            "FROM building_classification_event ORDER BY classification_event_id"
        )
    ]
    return {
        "current_count": len(current),
        "event_count": len(events),
        "current_sha256": sha256_value(current),
        "event_sha256": sha256_value(events),
    }


def _project_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = [
        [row[0], row[1], row[2]]
        for row in connection.execute(
            "SELECT project_building_id, building_key, lifecycle_status "
            "FROM project_building ORDER BY project_building_id"
        )
    ]
    return {
        "count": len(rows),
        "identity_sha256": sha256_value([[row[0], row[1]] for row in rows]),
        "state_sha256": sha256_value(rows),
    }


def _accepted_release(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, "
        "sr.feature_count FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "WHERE d.dataset_key = 'buildings' AND sr.lifecycle_status = 'accepted'"
    ).fetchall()
    if len(row) != 1:
        raise RuntimeError(f"Expected exactly one accepted building release, found {len(row)}")
    return row[0]


def _candidate_release(connection: sqlite3.Connection, release_key: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT sr.source_release_id, sr.release_key, sr.content_sha256, sr.feature_count, "
        "sr.lifecycle_status, sr.metadata_json FROM source_release sr "
        "JOIN dataset d ON d.dataset_id = sr.dataset_id "
        "WHERE d.dataset_key = 'buildings' AND sr.release_key = ?",
        (release_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Candidate release is not registered: {release_key}")
    if row["lifecycle_status"] != "candidate":
        raise RuntimeError(f"Building reconciliation requires candidate lifecycle: {release_key}")
    return row


def _accepted_sources(connection: sqlite3.Connection, release_id: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    rows = connection.execute(
        "SELECT sb.source_building_id, sb.source_feature_id, sb.geometry_sha256, "
        "sb.min_x, sb.min_y, sb.max_x, sb.max_y, sb.source_ordinal, "
        "pb.project_building_id, pb.building_key, pb.lifecycle_status, m.relationship_type "
        "FROM source_building sb "
        "LEFT JOIN project_building_source_mapping m "
        "ON m.source_building_id = sb.source_building_id AND m.mapping_status = 'confirmed' "
        "LEFT JOIN project_building pb ON pb.project_building_id = m.project_building_id "
        "WHERE sb.source_release_id = ? "
        "ORDER BY sb.source_ordinal, pb.project_building_id",
        (release_id,),
    ).fetchall()
    for row in rows:
        identity = str(row["source_feature_id"])
        entry = result.setdefault(
            identity,
            {
                "source_building_id": int(row["source_building_id"]),
                "geometry_sha256": str(row["geometry_sha256"]),
                "bounds": [
                    float(row["min_x"]),
                    float(row["min_y"]),
                    float(row["max_x"]),
                    float(row["max_y"]),
                ],
                "projects": [],
            },
        )
        if row["project_building_id"] is not None:
            entry["projects"].append(
                {
                    "project_building_id": int(row["project_building_id"]),
                    "building_key": str(row["building_key"]),
                    "lifecycle_status": str(row["lifecycle_status"]),
                    "relationship_type": str(row["relationship_type"]),
                }
            )
    for identity, entry in result.items():
        if not entry["projects"]:
            raise RuntimeError(f"Accepted building {identity} has no confirmed project mapping")
    return result


def _classification_by_project(connection: sqlite3.Connection) -> dict[int, str]:
    return {
        int(row["project_building_id"]): str(row["classification"])
        for row in connection.execute(
            "SELECT project_building_id, classification "
            "FROM building_classification_current ORDER BY project_building_id"
        )
    }


def _candidate_sources(candidate_dir: Path, expected_count: int) -> dict[str, dict[str, Any]]:
    _, features = kane_buildings.load_feature_collection(
        candidate_dir / "buildings.geojson", expected_count
    )
    normalized = kane_buildings.normalize_features(features, "FPId")
    result: dict[str, dict[str, Any]] = {}
    for feature in normalized:
        identity = str(feature["source_feature_id"])
        result[identity] = {
            "geometry_sha256": str(feature["geometry_sha256"]),
            "bounds": [float(value) for value in feature["bounds"]],
        }
    return result


def _bbox_overlap(first: Sequence[float], second: Sequence[float]) -> bool:
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def _bbox_cells(bounds: Sequence[float]) -> list[tuple[int, int]] | None:
    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    x0 = math.floor(min_x / OVERLAP_GRID_DEGREES)
    x1 = math.floor(max_x / OVERLAP_GRID_DEGREES)
    y0 = math.floor(min_y / OVERLAP_GRID_DEGREES)
    y1 = math.floor(max_y / OVERLAP_GRID_DEGREES)
    cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
    if cell_count > MAX_GRID_CELLS_PER_BOUNDS:
        return None
    return [
        (x_index, y_index)
        for x_index in range(x0, x1 + 1)
        for y_index in range(y0, y1 + 1)
    ]


def _overlap_edges(
    accepted_sources: Mapping[str, Mapping[str, Any]],
    candidate_sources: Mapping[str, Mapping[str, Any]],
    old_identities: set[str],
    new_identities: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    old_edges: dict[str, set[str]] = {identity: set() for identity in old_identities}
    new_edges: dict[str, set[str]] = {identity: set() for identity in new_identities}
    grid: dict[tuple[int, int], set[str]] = defaultdict(set)
    broad_new: set[str] = set()
    for identity in sorted(new_identities):
        cells = _bbox_cells(candidate_sources[identity]["bounds"])
        if cells is None:
            broad_new.add(identity)
            continue
        for cell in cells:
            grid[cell].add(identity)
    for old_identity in sorted(old_identities):
        cells = _bbox_cells(accepted_sources[old_identity]["bounds"])
        if cells is None:
            candidates = set(new_identities)
        else:
            candidates = set(broad_new)
            for cell in cells:
                candidates.update(grid.get(cell, ()))
        for new_identity in sorted(candidates):
            if _bbox_overlap(
                accepted_sources[old_identity]["bounds"],
                candidate_sources[new_identity]["bounds"],
            ):
                old_edges[old_identity].add(new_identity)
                new_edges[new_identity].add(old_identity)
    return old_edges, new_edges


def _pair_hash(pairs: Sequence[Sequence[Any]]) -> str:
    return sha256_value(sorted([list(pair) for pair in pairs]))


def build_plan(database: Path, candidate_dir: Path) -> dict[str, Any]:
    database = database.resolve()
    candidate_dir = candidate_dir.resolve()
    accepted_database_sha256 = sha256_file(database)
    errors = kane_classifications.validate_database(database)
    if errors:
        raise RuntimeError("Database failed validation before reconciliation:\n- " + "\n- ".join(errors))
    validated = kane_candidate.validate_candidate(candidate_dir)
    comparison = kane_compare.compare_candidate(database, candidate_dir)
    if comparison.get("candidate_kind") != "official-buildings":
        raise RuntimeError("Building reconciliation requires an official-building candidate")
    datasets = comparison.get("datasets")
    if not isinstance(datasets, list) or len(datasets) != 1 or datasets[0].get("dataset_key") != "buildings":
        raise RuntimeError("Building comparison report is malformed")
    connection = _read_only(database)
    try:
        accepted = _accepted_release(connection)
        candidate_release = _candidate_release(connection, str(validated["release_key"]))
        if candidate_release["content_sha256"] != validated["content_sha256"]:
            raise RuntimeError("Registered building candidate content hash does not match staged candidate")
        accepted_sources = _accepted_sources(connection, int(accepted["source_release_id"]))
        candidate_sources = _candidate_sources(candidate_dir, int(validated["feature_count"]))
        classification_snapshot = _classification_snapshot(connection)
        project_snapshot = _project_snapshot(connection)
        explicit_classifications = _classification_by_project(connection)
    finally:
        connection.close()

    accepted_ids = set(accepted_sources)
    candidate_ids = set(candidate_sources)
    common_ids = sorted(accepted_ids & candidate_ids)
    unmatched_old = set(accepted_ids - candidate_ids)
    unmatched_new = set(candidate_ids - accepted_ids)

    mapping_actions: list[dict[str, Any]] = []
    mapped_projects: set[int] = set()

    for identity in common_ids:
        old = accepted_sources[identity]
        geometry_changed = old["geometry_sha256"] != candidate_sources[identity]["geometry_sha256"]
        for project in old["projects"]:
            relationship = "reappearance" if project["lifecycle_status"] == "inactive" else "continuation"
            if project["lifecycle_status"] == "retired":
                raise RuntimeError(
                    f"Retired project building unexpectedly appears in accepted release mapping: {project['building_key']}"
                )
            mapping_actions.append(
                {
                    "candidate_identity": identity,
                    "project_building_id": project["project_building_id"],
                    "building_key": project["building_key"],
                    "relationship_type": relationship,
                    "geometry_redraw": geometry_changed,
                }
            )
            mapped_projects.add(project["project_building_id"])

    old_by_geometry: dict[str, list[str]] = defaultdict(list)
    new_by_geometry: dict[str, list[str]] = defaultdict(list)
    for identity in unmatched_old:
        old_by_geometry[accepted_sources[identity]["geometry_sha256"]].append(identity)
    for identity in unmatched_new:
        new_by_geometry[candidate_sources[identity]["geometry_sha256"]].append(identity)
    automatic_replacements: list[list[str]] = []
    for geometry_hash in sorted(set(old_by_geometry) & set(new_by_geometry)):
        olds = sorted(old_by_geometry[geometry_hash])
        news = sorted(new_by_geometry[geometry_hash])
        if len(olds) != 1 or len(news) != 1:
            continue
        old_identity, new_identity = olds[0], news[0]
        for project in accepted_sources[old_identity]["projects"]:
            mapping_actions.append(
                {
                    "candidate_identity": new_identity,
                    "project_building_id": project["project_building_id"],
                    "building_key": project["building_key"],
                    "relationship_type": "replacement",
                    "geometry_redraw": False,
                }
            )
            mapped_projects.add(project["project_building_id"])
        automatic_replacements.append([old_identity, new_identity])
        unmatched_old.remove(old_identity)
        unmatched_new.remove(new_identity)

    old_edges, new_edges = _overlap_edges(
        accepted_sources, candidate_sources, unmatched_old, unmatched_new
    )

    clear_additions = sorted(identity for identity in unmatched_new if not new_edges[identity])
    clear_removed_sources = sorted(identity for identity in unmatched_old if not old_edges[identity])

    ambiguous_components: list[dict[str, Any]] = []
    visited_old: set[str] = set()
    visited_new: set[str] = set()
    for start in sorted(identity for identity in unmatched_old if old_edges[identity]):
        if start in visited_old:
            continue
        queue: deque[tuple[str, str]] = deque([("old", start)])
        component_old: set[str] = set()
        component_new: set[str] = set()
        while queue:
            side, identity = queue.popleft()
            if side == "old":
                if identity in visited_old:
                    continue
                visited_old.add(identity)
                component_old.add(identity)
                for other in sorted(old_edges[identity]):
                    if other not in visited_new:
                        queue.append(("new", other))
            else:
                if identity in visited_new:
                    continue
                visited_new.add(identity)
                component_new.add(identity)
                for other in sorted(new_edges[identity]):
                    if other not in visited_old:
                        queue.append(("old", other))
        old_list = sorted(component_old)
        new_list = sorted(component_new)
        if len(old_list) == 1 and len(new_list) == 1:
            kind = "uncertain_replacement"
        elif len(old_list) == 1 and len(new_list) > 1:
            kind = "split"
        elif len(old_list) > 1 and len(new_list) == 1:
            kind = "merge"
        else:
            kind = "complex"
        affected_projects = sorted(
            {
                (
                    project["building_key"],
                    explicit_classifications.get(
                        project["project_building_id"], "unclassified"
                    ),
                )
                for old_identity in old_list
                for project in accepted_sources[old_identity]["projects"]
            }
        )
        ambiguous_components.append(
            {
                "kind": kind,
                "accepted_identities": old_list,
                "candidate_identities": new_list,
                "affected_project_buildings": [
                    {"building_key": key, "classification": classification}
                    for key, classification in affected_projects
                ],
            }
        )

    disappearance_projects: dict[int, dict[str, Any]] = {}
    for old_identity in clear_removed_sources:
        for project in accepted_sources[old_identity]["projects"]:
            project_id = project["project_building_id"]
            if project_id in mapped_projects:
                continue
            disappearance_projects[project_id] = {
                "project_building_id": project_id,
                "building_key": project["building_key"],
                "classification": explicit_classifications.get(
                    project["project_building_id"], "unclassified"
                ),
                "accepted_identity": old_identity,
            }

    continuation_pairs = sorted(
        [action["building_key"], action["candidate_identity"]]
        for action in mapping_actions
        if action["relationship_type"] in {"continuation", "reappearance"}
    )
    replacement_pairs = sorted(
        [action["building_key"], action["candidate_identity"]]
        for action in mapping_actions
        if action["relationship_type"] == "replacement"
    )
    addition_ids = clear_additions
    disappearance_keys = sorted(value["building_key"] for value in disappearance_projects.values())
    ambiguity_body = ambiguous_components
    plan_identity = {
        "accepted_database_sha256": accepted_database_sha256,
        "accepted_release_key": str(accepted["release_key"]),
        "accepted_release_sha256": str(accepted["content_sha256"]),
        "candidate_release_key": str(validated["release_key"]),
        "candidate_content_sha256": str(validated["content_sha256"]),
        "comparison_sha256": str(comparison["comparison_sha256"]),
        "continuation_pairs_sha256": _pair_hash(continuation_pairs),
        "replacement_pairs_sha256": _pair_hash(replacement_pairs),
        "addition_identities_sha256": sha256_value(addition_ids),
        "disappearance_building_keys_sha256": sha256_value(disappearance_keys),
        "ambiguities_sha256": sha256_value(ambiguity_body),
    }
    reconciliation_digest = sha256_value(plan_identity)
    date_token = str(validated["source_published_at"] or "unknown")[:10].replace("-", "")
    reconciliation_key = f"kane-buildings-reconciliation-{date_token}-{reconciliation_digest[:12]}"
    ambiguous_candidate_ids = sorted(
        {identity for component in ambiguous_components for identity in component["candidate_identities"]}
    )
    return {
        "reconciliation_key": reconciliation_key,
        "accepted_database_sha256": accepted_database_sha256,
        "accepted_release": {
            "release_key": str(accepted["release_key"]),
            "content_sha256": str(accepted["content_sha256"]),
            "feature_count": int(accepted["feature_count"]),
        },
        "candidate_release": {
            "release_key": str(validated["release_key"]),
            "content_sha256": str(validated["content_sha256"]),
            "feature_count": int(validated["feature_count"]),
            "manifest_sha256": str(validated["manifest_sha256"]),
        },
        "comparison_sha256": str(comparison["comparison_sha256"]),
        "mapping_actions": mapping_actions,
        "additions": addition_ids,
        "disappearances": sorted(disappearance_projects.values(), key=lambda item: item["building_key"]),
        "ambiguities": ambiguous_components,
        "ambiguous_candidate_identities": ambiguous_candidate_ids,
        "classification_snapshot": classification_snapshot,
        "project_snapshot": project_snapshot,
        "automatic_summary": {
            "continuation_mapping_count": sum(
                1 for action in mapping_actions if action["relationship_type"] in {"continuation", "reappearance"}
            ),
            "geometry_redraw_mapping_count": sum(1 for action in mapping_actions if action["geometry_redraw"]),
            "replacement_mapping_count": sum(1 for action in mapping_actions if action["relationship_type"] == "replacement"),
            "addition_count": len(addition_ids),
            "disappearance_count": len(disappearance_projects),
            "continuation_pairs_sha256": _pair_hash(continuation_pairs),
            "replacement_pairs_sha256": _pair_hash(replacement_pairs),
            "addition_identities_sha256": sha256_value(addition_ids),
            "disappearance_building_keys_sha256": sha256_value(disappearance_keys),
        },
        "ready_for_promotion": not ambiguous_components,
        "plan_identity": plan_identity,
    }


def _candidate_source_ids(connection: sqlite3.Connection, release_key: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT sb.source_feature_id, sb.source_building_id FROM source_building sb "
            "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
            "WHERE sr.release_key = ? ORDER BY sb.source_ordinal",
            (release_key,),
        )
    }


def _apply_plan(candidate_database: Path, candidate_dir: Path, plan: Mapping[str, Any]) -> None:
    release_key = str(_mapping(plan["candidate_release"], "candidate_release")["release_key"])
    kane_buildings.import_buildings(candidate_database, release_key, candidate_dir / "buildings.geojson")
    connection = sqlite3.connect(candidate_database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        source_ids = _candidate_source_ids(connection, release_key)
        now = kane_db.utc_now()
        mapping_rows: list[tuple[int, int, str, str]] = []
        reappearance_ids: list[tuple[int]] = []
        for action in plan["mapping_actions"]:
            candidate_identity = str(action["candidate_identity"])
            source_id = source_ids.get(candidate_identity)
            if source_id is None:
                raise RuntimeError(
                    f"Candidate source identity is not stored: {candidate_identity}"
                )
            project_id = int(action["project_building_id"])
            relationship = str(action["relationship_type"])
            mapping_rows.append((project_id, source_id, relationship, now))
            if relationship == "reappearance":
                reappearance_ids.append((project_id,))
        connection.executemany(
            "INSERT INTO project_building_source_mapping ("
            "project_building_id, source_building_id, relationship_type, "
            "decision_method, mapping_status, created_at, reviewed_at"
            ") VALUES (?, ?, ?, 'automatic', 'confirmed', ?, NULL)",
            mapping_rows,
        )
        if reappearance_ids:
            connection.executemany(
                "UPDATE project_building SET lifecycle_status = 'active', retired_at = NULL "
                "WHERE project_building_id = ? AND lifecycle_status = 'inactive'",
                reappearance_ids,
            )
        for candidate_identity in plan["additions"]:
            source_id = source_ids.get(str(candidate_identity))
            if source_id is None:
                raise RuntimeError(f"Added candidate identity is not stored: {candidate_identity}")
            building_key = kane_project.project_building_key(release_key, str(candidate_identity))
            cursor = connection.execute(
                "INSERT INTO project_building (building_key, lifecycle_status, "
                "created_from_source_building_id, identity_algorithm, created_at, retired_at) "
                "VALUES (?, 'active', ?, ?, ?, NULL)",
                (building_key, source_id, kane_project.IDENTITY_ALGORITHM, now),
            )
            connection.execute(
                "INSERT INTO project_building_source_mapping ("
                "project_building_id, source_building_id, relationship_type, decision_method, "
                "mapping_status, created_at, reviewed_at) "
                "VALUES (?, ?, 'initial', 'deterministic-seed', 'confirmed', ?, NULL)",
                (cursor.lastrowid, source_id, now),
            )
        for disappearance in plan["disappearances"]:
            connection.execute(
                "UPDATE project_building SET lifecycle_status = 'inactive', retired_at = NULL "
                "WHERE project_building_id = ? AND lifecycle_status = 'active'",
                (int(disappearance["project_building_id"]),),
            )
        changed_at = kane_db.utc_now()
        connection.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name IN (?, ?)",
            (changed_at, kane_project.PROJECT_TABLE, kane_project.MAPPING_TABLE),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _candidate_mapping_summary(database: Path, release_key: str) -> dict[str, Any]:
    connection = _read_only(database)
    try:
        release = _candidate_release(connection, release_key)
        rows = connection.execute(
            "SELECT sb.source_feature_id, COUNT(DISTINCT CASE WHEN m.mapping_status = 'confirmed' "
            "THEN m.project_building_id END) AS mapped_count "
            "FROM source_building sb LEFT JOIN project_building_source_mapping m "
            "ON m.source_building_id = sb.source_building_id "
            "WHERE sb.source_release_id = ? GROUP BY sb.source_building_id "
            "ORDER BY sb.source_feature_id",
            (release["source_release_id"],),
        ).fetchall()
        unmapped = [str(row["source_feature_id"]) for row in rows if int(row["mapped_count"]) == 0]
        mapped = [str(row["source_feature_id"]) for row in rows if int(row["mapped_count"]) > 0]
        relationships = dict(
            connection.execute(
                "SELECT m.relationship_type, COUNT(*) FROM project_building_source_mapping m "
                "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
                "WHERE sb.source_release_id = ? AND m.mapping_status = 'confirmed' "
                "GROUP BY m.relationship_type ORDER BY m.relationship_type",
                (release["source_release_id"],),
            ).fetchall()
        )
        return {
            "source_building_count": len(rows),
            "mapped_source_count": len(mapped),
            "unmapped_source_count": len(unmapped),
            "unmapped_identities": sorted(unmapped),
            "unmapped_identities_sha256": sha256_value(sorted(unmapped)),
            "confirmed_relationship_counts": {str(key): int(value) for key, value in relationships.items()},
        }
    finally:
        connection.close()


def _build_report(
    source_database: Path,
    candidate_database: Path,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    connection = _read_only(candidate_database)
    try:
        classifications_after = _classification_snapshot(connection)
        project_after = _project_snapshot(connection)
    finally:
        connection.close()
    classifications_before = dict(plan["classification_snapshot"])
    if classifications_after != classifications_before:
        raise RuntimeError("Building reconciliation changed classification rows or history")
    errors = kane_classifications.validate_database(candidate_database)
    if errors:
        raise RuntimeError("Candidate database failed validation after reconciliation:\n- " + "\n- ".join(errors))
    release_key = str(plan["candidate_release"]["release_key"])
    mapping_summary = _candidate_mapping_summary(candidate_database, release_key)
    expected_unmapped = sorted(plan["ambiguous_candidate_identities"])
    if mapping_summary["unmapped_identities"] != expected_unmapped:
        raise RuntimeError("Candidate database unmapped source identities do not match reconciliation ambiguities")
    if plan["ready_for_promotion"] and mapping_summary["unmapped_source_count"] != 0:
        raise RuntimeError("Promotion-ready reconciliation contains unmapped candidate buildings")
    database_info = {
        "filename": DATABASE_FILENAME,
        "byte_length": candidate_database.stat().st_size,
        "sha256": sha256_file(candidate_database),
    }
    body = {
        "reconciliation_schema": RECONCILIATION_SCHEMA,
        "reconciliation_key": plan["reconciliation_key"],
        "accepted_database_sha256": plan["accepted_database_sha256"],
        "accepted_release": plan["accepted_release"],
        "candidate_release": plan["candidate_release"],
        "comparison_sha256": plan["comparison_sha256"],
        "automatic_summary": plan["automatic_summary"],
        "ambiguities": plan["ambiguities"],
        "ambiguity_count": len(plan["ambiguities"]),
        "ready_for_promotion": bool(plan["ready_for_promotion"]),
        "classification_preservation": {
            "before": classifications_before,
            "after": classifications_after,
            "unchanged": True,
        },
        "project_state": {
            "before": plan["project_snapshot"],
            "after": project_after,
            "new_project_building_count": int(project_after["count"]) - int(plan["project_snapshot"]["count"]),
        },
        "candidate_mapping": mapping_summary,
        "candidate_database": database_info,
    }
    return {**body, "reconciliation_sha256": sha256_value(body)}


def _validate_layout(reconciliation_dir: Path) -> None:
    if reconciliation_dir.is_symlink():
        raise RuntimeError("Reconciliation directory must not be a symlink")
    entries = list(reconciliation_dir.iterdir())
    for entry in entries:
        if entry.is_symlink():
            raise RuntimeError(f"Reconciliation artifact must not be a symlink: {entry.name}")
        if entry.is_dir():
            raise RuntimeError(f"Unexpected subdirectory in reconciliation artifact: {entry.name}")
    names = {entry.name for entry in entries}
    if names != REQUIRED_FILES:
        raise RuntimeError(f"Reconciliation artifact files are invalid: {sorted(names)!r}")


def validate_reconciliation(reconciliation_dir: Path) -> dict[str, Any]:
    reconciliation_dir = reconciliation_dir.absolute()
    if not reconciliation_dir.exists() or not reconciliation_dir.is_dir():
        raise RuntimeError(f"Reconciliation directory does not exist: {reconciliation_dir}")
    _validate_layout(reconciliation_dir)
    report = _mapping(load_json(reconciliation_dir / REPORT_FILENAME), "Reconciliation report")
    required_keys = {
        "reconciliation_schema", "reconciliation_key", "accepted_database_sha256",
        "accepted_release", "candidate_release", "comparison_sha256", "automatic_summary",
        "ambiguities", "ambiguity_count", "ready_for_promotion", "classification_preservation",
        "project_state", "candidate_mapping", "candidate_database", "reconciliation_sha256",
    }
    if set(report) != required_keys:
        raise RuntimeError("Reconciliation report has an unexpected key set")
    if report["reconciliation_schema"] != RECONCILIATION_SCHEMA:
        raise RuntimeError(f"reconciliation_schema must be {RECONCILIATION_SCHEMA}")
    body = {key: value for key, value in report.items() if key != "reconciliation_sha256"}
    if report["reconciliation_sha256"] != sha256_value(body):
        raise RuntimeError("Reconciliation report SHA-256 is invalid")
    key = str(report["reconciliation_key"])
    if reconciliation_dir.name != key or reconciliation_dir.parent.name != RECONCILIATION_DIRNAME:
        raise RuntimeError("Reconciliation directory layout does not match reconciliation_key")
    database_info = _mapping(report["candidate_database"], "candidate_database")
    if set(database_info) != {"filename", "byte_length", "sha256"}:
        raise RuntimeError("candidate_database has an unexpected key set")
    if database_info["filename"] != DATABASE_FILENAME:
        raise RuntimeError("candidate_database filename is invalid")
    database = reconciliation_dir / DATABASE_FILENAME
    if database.stat().st_size != database_info["byte_length"] or sha256_file(database) != database_info["sha256"]:
        raise RuntimeError("Candidate database file identity does not match reconciliation report")
    errors = kane_classifications.validate_database(database)
    if errors:
        raise RuntimeError("Reconciled candidate database is invalid:\n- " + "\n- ".join(errors))
    accepted_report = _mapping(report["accepted_release"], "accepted_release")
    candidate_release = _mapping(report["candidate_release"], "candidate_release")
    if set(accepted_report) != {"release_key", "content_sha256", "feature_count"}:
        raise RuntimeError("accepted_release has an unexpected key set")
    if set(candidate_release) != {
        "release_key", "content_sha256", "feature_count", "manifest_sha256"
    }:
        raise RuntimeError("candidate_release has an unexpected key set")
    mapping_summary = _candidate_mapping_summary(
        database, str(candidate_release["release_key"])
    )
    if mapping_summary != report["candidate_mapping"]:
        raise RuntimeError("Candidate mapping summary does not match reconciled database")
    preservation = _mapping(
        report["classification_preservation"], "classification_preservation"
    )
    project_state = _mapping(report["project_state"], "project_state")
    if set(project_state) != {"before", "after", "new_project_building_count"}:
        raise RuntimeError("project_state has an unexpected key set")
    connection = _read_only(database)
    try:
        current_snapshot = _classification_snapshot(connection)
        current_project_snapshot = _project_snapshot(connection)
        accepted_actual = _accepted_release(connection)
        candidate_actual = _candidate_release(
            connection, str(candidate_release["release_key"])
        )
    finally:
        connection.close()
    accepted_expected = {
        "release_key": str(accepted_actual["release_key"]),
        "content_sha256": str(accepted_actual["content_sha256"]),
        "feature_count": int(accepted_actual["feature_count"]),
    }
    if dict(accepted_report) != accepted_expected:
        raise RuntimeError("Accepted building release evidence does not match candidate database")
    candidate_metadata = _mapping(
        json.loads(str(candidate_actual["metadata_json"])),
        "candidate release metadata",
    )
    candidate_expected = {
        "release_key": str(candidate_actual["release_key"]),
        "content_sha256": str(candidate_actual["content_sha256"]),
        "feature_count": int(candidate_actual["feature_count"]),
        "manifest_sha256": candidate_metadata.get("candidate_manifest_sha256"),
    }
    if dict(candidate_release) != candidate_expected:
        raise RuntimeError("Candidate building release evidence does not match candidate database")
    if (
        preservation.get("unchanged") is not True
        or preservation.get("before") != preservation.get("after")
        or preservation.get("after") != current_snapshot
    ):
        raise RuntimeError("Classification preservation evidence is invalid")
    if project_state.get("after") != current_project_snapshot:
        raise RuntimeError("Project-building state evidence does not match candidate database")
    before_project = _mapping(project_state.get("before"), "project_state.before")
    after_project = _mapping(project_state.get("after"), "project_state.after")
    expected_new_count = int(after_project.get("count", -1)) - int(
        before_project.get("count", -1)
    )
    if project_state.get("new_project_building_count") != expected_new_count:
        raise RuntimeError("Project-building addition count evidence is invalid")
    ambiguities = report["ambiguities"]
    if not isinstance(ambiguities, list) or int(report["ambiguity_count"]) != len(ambiguities):
        raise RuntimeError("Reconciliation ambiguity count is invalid")
    expected_ready = len(ambiguities) == 0
    if bool(report["ready_for_promotion"]) != expected_ready:
        raise RuntimeError("ready_for_promotion does not match ambiguity state")
    if expected_ready and mapping_summary["unmapped_source_count"] != 0:
        raise RuntimeError("Promotion-ready candidate has unmapped source buildings")
    return {
        "valid": True,
        "reconciliation_key": key,
        "ready_for_promotion": expected_ready,
        "ambiguity_count": len(ambiguities),
        "candidate_database_sha256": database_info["sha256"],
        "candidate_release_key": candidate_release["release_key"],
        "mapped_source_count": mapping_summary["mapped_source_count"],
        "unmapped_source_count": mapping_summary["unmapped_source_count"],
        "reconciliation_sha256": report["reconciliation_sha256"],
    }


def prepare_reconciliation(database: Path, candidate_dir: Path, output_root: Path) -> dict[str, Any]:
    database = database.resolve()
    candidate_dir = candidate_dir.resolve()
    output_root = output_root.resolve()
    plan = build_plan(database, candidate_dir)
    parent = output_root / RECONCILIATION_DIRNAME
    final_dir = parent / str(plan["reconciliation_key"])
    if final_dir.exists():
        result = validate_reconciliation(final_dir)
        return {**result, "reconciliation_directory": str(final_dir), "existing": True}
    parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".building-reconcile-", dir=parent))
    try:
        candidate_database = temp_dir / DATABASE_FILENAME
        _database_backup(database, candidate_database)
        if sha256_file(database) != plan["accepted_database_sha256"]:
            raise RuntimeError("Accepted database changed during building reconciliation")
        _apply_plan(candidate_database, candidate_dir, plan)
        report = _build_report(database, candidate_database, plan)
        (temp_dir / REPORT_FILENAME).write_bytes(canonical_bytes(report) + b"\n")
        os.replace(temp_dir, final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    result = validate_reconciliation(final_dir)
    return {**result, "reconciliation_directory": str(final_dir), "existing": False}


def reconciliation_info(reconciliation_dir: Path) -> dict[str, Any]:
    validation = validate_reconciliation(reconciliation_dir)
    report = _mapping(load_json(reconciliation_dir / REPORT_FILENAME), "Reconciliation report")
    return {
        **validation,
        "accepted_release": report["accepted_release"],
        "candidate_release": report["candidate_release"],
        "automatic_summary": report["automatic_summary"],
        "ambiguities": report["ambiguities"],
        "classification_preservation": report["classification_preservation"],
        "project_state": report["project_state"],
        "candidate_mapping": report["candidate_mapping"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Build a reconciled candidate database")
    prepare.add_argument("database", type=Path)
    prepare.add_argument("candidate_directory", type=Path)
    prepare.add_argument("output_root", type=Path)
    validate = subparsers.add_parser("validate", help="Validate a reconciliation artifact")
    validate.add_argument("reconciliation_directory", type=Path)
    info = subparsers.add_parser("info", help="Inspect a reconciliation artifact")
    info.add_argument("reconciliation_directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_reconciliation(args.database, args.candidate_directory, args.output_root)
        elif args.command == "validate":
            result = validate_reconciliation(args.reconciliation_directory)
        else:
            result = reconciliation_info(args.reconciliation_directory)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
