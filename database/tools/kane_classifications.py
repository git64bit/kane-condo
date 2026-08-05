#!/usr/bin/env python3
"""Write, validate, and inspect Kane Condo building classifications."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

EVENT_TABLE = "building_classification_event"
CURRENT_TABLE = "building_classification_current"
CLASSIFICATIONS = ("unclassified", "other", "condominium", "apartments")
EXPLICIT_CLASSIFICATIONS = CLASSIFICATIONS[1:]
EVENT_KINDS = ("classification", "correction", "undo")
EVENT_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
EVENT_COLUMNS = (
    "classification_event_id",
    "event_key",
    "project_building_id",
    "predecessor_event_id",
    "event_kind",
    "previous_classification",
    "new_classification",
    "reverses_event_id",
    "created_at",
)
CURRENT_COLUMNS = (
    "project_building_id",
    "classification",
    "classification_event_id",
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
project = load_sibling("kane_project_buildings")


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = table.replace('"', '""')
    return tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{quoted}")'))


def validate_schema(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    tables = kane_db.table_names(connection)
    for table, columns in (
        (EVENT_TABLE, EVENT_COLUMNS),
        (CURRENT_TABLE, CURRENT_COLUMNS),
    ):
        if table not in tables:
            errors.append(f"Missing classification table: {table}")
            continue
        actual = table_columns(connection, table)
        if actual != columns:
            errors.append(
                f"Unexpected {table} columns: expected {columns!r}, found {actual!r}"
            )
    expected = {
        EVENT_TABLE: "Kane Condo classification history",
        CURRENT_TABLE: "Kane Condo current classifications",
    }
    registrations = {
        str(row[0]): (str(row[1]), str(row[2]), row[3])
        for row in connection.execute(
            "SELECT table_name, data_type, identifier, srs_id FROM gpkg_contents "
            "WHERE table_name IN (?, ?)",
            (EVENT_TABLE, CURRENT_TABLE),
        )
    }
    for table, identifier in expected.items():
        row = registrations.get(table)
        if row != ("attributes", identifier, None):
            errors.append(f"Unexpected {table} gpkg_contents registration: {row!r}")
    trigger_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE "
            "'tr_classification_%'"
        )
    }
    required_triggers = {
        "tr_classification_event_no_update",
        "tr_classification_event_no_delete",
        "tr_classification_current_insert_match",
        "tr_classification_current_update_match",
    }
    missing_triggers = sorted(required_triggers - trigger_names)
    if missing_triggers:
        errors.append("Missing classification triggers: " + ", ".join(missing_triggers))
    return errors


def project_row(connection: sqlite3.Connection, building_key: str) -> sqlite3.Row:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT project_building_id, building_key, lifecycle_status "
        "FROM project_building WHERE building_key = ?",
        (building_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Unknown project building: {building_key}")
    return row


def latest_event(
    connection: sqlite3.Connection, project_building_id: int
) -> sqlite3.Row | None:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        "SELECT * FROM building_classification_event "
        "WHERE project_building_id = ? ORDER BY classification_event_id DESC LIMIT 1",
        (project_building_id,),
    ).fetchone()


def event_by_key(connection: sqlite3.Connection, event_key: str) -> sqlite3.Row | None:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        "SELECT * FROM building_classification_event WHERE event_key = ?",
        (event_key,),
    ).fetchone()


def current_classification(latest: sqlite3.Row | None) -> str:
    return "unclassified" if latest is None else str(latest["new_classification"])


def validate_event_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT event.*, pb.lifecycle_status FROM building_classification_event event "
        "JOIN project_building pb "
        "ON pb.project_building_id = event.project_building_id "
        "ORDER BY event.project_building_id, event.classification_event_id"
    ).fetchall()
    previous_by_project: dict[int, sqlite3.Row] = {}
    for row in rows:
        event_id = int(row["classification_event_id"])
        project_id = int(row["project_building_id"])
        if EVENT_KEY_PATTERN.fullmatch(str(row["event_key"])) is None:
            errors.append(f"Classification event {event_id} event_key is invalid")
        if row["event_kind"] not in EVENT_KINDS:
            errors.append(f"Classification event {event_id} event_kind is invalid")
        if row["previous_classification"] not in CLASSIFICATIONS:
            errors.append(f"Classification event {event_id} previous state is invalid")
        if row["new_classification"] not in CLASSIFICATIONS:
            errors.append(f"Classification event {event_id} new state is invalid")
        if row["previous_classification"] == row["new_classification"]:
            errors.append(f"Classification event {event_id} does not change state")
        if not kane_db.valid_datetime(row["created_at"]):
            errors.append(f"Classification event {event_id} created_at is invalid")
        predecessor = previous_by_project.get(project_id)
        if predecessor is None:
            if row["predecessor_event_id"] is not None:
                errors.append(f"Classification event {event_id} has an unexpected predecessor")
            if row["previous_classification"] != "unclassified":
                errors.append(f"Classification event {event_id} must begin from Unclassified")
            if row["event_kind"] != "classification":
                errors.append(f"Classification event {event_id} first event kind is invalid")
        else:
            predecessor_id = int(predecessor["classification_event_id"])
            if row["predecessor_event_id"] != predecessor_id:
                errors.append(f"Classification event {event_id} predecessor is not the prior event")
            if row["previous_classification"] != predecessor["new_classification"]:
                errors.append(f"Classification event {event_id} previous state breaks the chain")
            if row["event_kind"] == "classification":
                errors.append(f"Classification event {event_id} repeats initial event kind")
        if row["event_kind"] == "undo":
            if predecessor is None or row["reverses_event_id"] != predecessor["classification_event_id"]:
                errors.append(f"Classification event {event_id} undo target is invalid")
            elif row["new_classification"] != predecessor["previous_classification"]:
                errors.append(f"Classification event {event_id} does not reverse its target")
        elif row["reverses_event_id"] is not None:
            errors.append(f"Classification event {event_id} has an unexpected reversal target")
        previous_by_project[project_id] = row
    return errors


def validate_current_rows(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    connection.row_factory = sqlite3.Row
    project_ids = [
        int(row[0])
        for row in connection.execute(
            "SELECT project_building_id FROM project_building ORDER BY project_building_id"
        )
    ]
    for project_id in project_ids:
        latest = latest_event(connection, project_id)
        current = connection.execute(
            "SELECT classification, classification_event_id "
            "FROM building_classification_current WHERE project_building_id = ?",
            (project_id,),
        ).fetchone()
        expected = current_classification(latest)
        if expected == "unclassified":
            if current is not None:
                errors.append(
                    f"Project building {project_id} stores a current row for Unclassified"
                )
        elif current is None:
            errors.append(f"Project building {project_id} lacks its current classification row")
        elif (
            current["classification"] != expected
            or current["classification_event_id"] != latest["classification_event_id"]
        ):
            errors.append(f"Project building {project_id} current classification is stale")
    orphan_count = connection.execute(
        "SELECT COUNT(*) FROM building_classification_current current "
        "LEFT JOIN project_building pb "
        "ON pb.project_building_id = current.project_building_id "
        "WHERE pb.project_building_id IS NULL"
    ).fetchone()[0]
    if orphan_count:
        errors.append(f"Current classifications contain {orphan_count} orphan rows")
    return errors


def validate_contents(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table in (EVENT_TABLE, CURRENT_TABLE):
        row = connection.execute(
            "SELECT last_change FROM gpkg_contents WHERE table_name = ?", (table,)
        ).fetchone()
        if row is None or not kane_db.valid_datetime(row[0]):
            errors.append(f"{table} gpkg_contents last_change is invalid")
    return errors


def validate_data(connection: sqlite3.Connection) -> list[str]:
    return validate_event_rows(connection) + validate_current_rows(connection) + validate_contents(connection)


def validate_database(path: Path) -> list[str]:
    errors = list(project.validate_database(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        errors = validate_schema(connection)
        if not errors:
            errors.extend(validate_data(connection))
        return errors
    except sqlite3.Error as exc:
        return [f"Classification validation failed: {exc}"]
    finally:
        connection.close()


def validate_foundation(path: Path) -> list[str]:
    errors = list(project.validate_database(path))
    if errors:
        return errors
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        return validate_schema(connection)
    except sqlite3.Error as exc:
        return [f"Classification foundation validation failed: {exc}"]
    finally:
        connection.close()


def validate_event_key(event_key: str) -> str:
    value = event_key.strip()
    if EVENT_KEY_PATTERN.fullmatch(value) is None:
        raise RuntimeError(
            "event_key must be 1-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return value


def validate_classification(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in CLASSIFICATIONS:
        raise RuntimeError(
            "classification must be one of: " + ", ".join(CLASSIFICATIONS)
        )
    return normalized


def check_expected_event(latest: sqlite3.Row | None, expected: int | None) -> None:
    if expected is None:
        return
    actual = None if latest is None else int(latest["classification_event_id"])
    if actual != expected:
        raise RuntimeError(
            f"Stale classification state: expected event {expected}, current event is {actual}"
        )


def replay_result(
    existing: sqlite3.Row,
    project_building_id: int,
    target: str | None,
    *,
    undo: bool,
) -> None:
    same_building = int(existing["project_building_id"]) == project_building_id
    same_action = (
        existing["event_kind"] == "undo"
        if undo
        else existing["event_kind"] != "undo"
        and existing["new_classification"] == target
    )
    if not same_building or not same_action:
        raise RuntimeError("event_key is already used for a different classification action")

def apply_current(
    connection: sqlite3.Connection,
    project_building_id: int,
    classification: str,
    event_id: int,
) -> None:
    if classification == "unclassified":
        connection.execute(
            "DELETE FROM building_classification_current WHERE project_building_id = ?",
            (project_building_id,),
        )
    else:
        connection.execute(
            "INSERT INTO building_classification_current ("
            "project_building_id, classification, classification_event_id"
            ") VALUES (?, ?, ?) ON CONFLICT(project_building_id) DO UPDATE SET "
            "classification = excluded.classification, "
            "classification_event_id = excluded.classification_event_id",
            (project_building_id, classification, event_id),
        )


def action_result(
    connection: sqlite3.Connection,
    database: Path,
    building: sqlite3.Row,
    event: sqlite3.Row | None,
    *,
    changed: bool,
    replayed: bool = False,
) -> dict[str, object]:
    classification = current_classification(event)
    return {
        "valid": True,
        "path": str(database),
        "building_key": building["building_key"],
        "project_building_id": building["project_building_id"],
        "lifecycle_status": building["lifecycle_status"],
        "classification": classification,
        "classification_event_id": (
            None if event is None else event["classification_event_id"]
        ),
        "event_key": None if event is None else event["event_key"],
        "changed": changed,
        "replayed": replayed,
    }


def write_action(
    database: Path,
    building_key: str,
    target_classification: str | None,
    event_key: str,
    *,
    expected_event_id: int | None = None,
    undo: bool = False,
) -> dict[str, object]:
    database = database.resolve()
    target = (
        None if target_classification is None
        else validate_classification(target_classification)
    )
    key = validate_event_key(event_key)
    errors = validate_database(database)
    if errors:
        raise RuntimeError(
            "Database failed validation before classification write:\n- "
            + "\n- ".join(errors)
        )
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        building = project_row(connection, building_key)
        if building["lifecycle_status"] != "active":
            raise RuntimeError("Only active project buildings may be classified")
        project_id = int(building["project_building_id"])
        existing = event_by_key(connection, key)
        if existing is not None:
            replay_result(existing, project_id, target, undo=undo)
            connection.rollback()
            return action_result(
                connection, database, building, existing, changed=False, replayed=True
            )
        latest = latest_event(connection, project_id)
        check_expected_event(latest, expected_event_id)
        if undo:
            if latest is None:
                raise RuntimeError("Building has no classification event to undo")
            target = str(latest["previous_classification"])
        assert target is not None
        prior = current_classification(latest)
        event_kind = "undo" if undo else ("classification" if latest is None else "correction")
        reverses = None if not undo else int(latest["classification_event_id"])
        if prior == target:
            connection.rollback()
            return action_result(
                connection, database, building, latest, changed=False
            )
        now = kane_db.utc_now()
        cursor = connection.execute(
            "INSERT INTO building_classification_event ("
            "event_key, project_building_id, predecessor_event_id, event_kind, "
            "previous_classification, new_classification, reverses_event_id, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                building["project_building_id"],
                None if latest is None else latest["classification_event_id"],
                event_kind,
                prior,
                target,
                reverses,
                now,
            ),
        )
        event_id = int(cursor.lastrowid)
        apply_current(
            connection, project_id, target, event_id
        )
        connection.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name IN (?, ?)",
            (now, EVENT_TABLE, CURRENT_TABLE),
        )
        transaction_errors = validate_schema(connection) + validate_data(connection)
        if transaction_errors:
            raise RuntimeError(
                "Classification write failed validation:\n- "
                + "\n- ".join(transaction_errors)
            )
        connection.commit()
        event = event_by_key(connection, key)
        assert event is not None
        return action_result(
            connection, database, building, event, changed=True
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def set_classification(
    database: Path,
    building_key: str,
    classification: str,
    event_key: str,
    *,
    expected_event_id: int | None = None,
) -> dict[str, object]:
    return write_action(
        database,
        building_key,
        classification,
        event_key,
        expected_event_id=expected_event_id,
    )


def undo_classification(
    database: Path,
    building_key: str,
    event_key: str,
    *,
    expected_event_id: int | None = None,
) -> dict[str, object]:
    return write_action(
        database,
        building_key,
        None,
        event_key,
        expected_event_id=expected_event_id,
        undo=True,
    )

def classification_get(database: Path, building_key: str) -> dict[str, object]:
    database = database.resolve()
    errors = validate_database(database)
    if errors:
        return {"valid": False, "path": str(database), "errors": errors}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        building = project_row(connection, building_key)
        latest = latest_event(connection, int(building["project_building_id"]))
        return action_result(connection, database, building, latest, changed=False)
    finally:
        connection.close()


def classification_history(database: Path, building_key: str) -> dict[str, object]:
    database = database.resolve()
    errors = validate_database(database)
    if errors:
        return {"valid": False, "path": str(database), "errors": errors}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        building = project_row(connection, building_key)
        events = [
            dict(row)
            for row in connection.execute(
                "SELECT classification_event_id, event_key, predecessor_event_id, "
                "event_kind, previous_classification, new_classification, "
                "reverses_event_id, created_at FROM building_classification_event "
                "WHERE project_building_id = ? ORDER BY classification_event_id",
                (building["project_building_id"],),
            )
        ]
        return {
            "valid": True,
            "path": str(database),
            "building_key": building["building_key"],
            "classification": (
                "unclassified" if not events else events[-1]["new_classification"]
            ),
            "events": events,
        }
    finally:
        connection.close()


def classification_info(database: Path) -> dict[str, object]:
    database = database.resolve()
    errors = validate_database(database)
    if errors:
        return {"valid": False, "path": str(database), "errors": errors}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        project_count = connection.execute(
            "SELECT COUNT(*) FROM project_building"
        ).fetchone()[0]
        explicit = dict(
            connection.execute(
                "SELECT classification, COUNT(*) FROM building_classification_current "
                "GROUP BY classification ORDER BY classification"
            )
        )
        classification_counts = {
            "unclassified": project_count - sum(explicit.values()),
            "other": explicit.get("other", 0),
            "condominium": explicit.get("condominium", 0),
            "apartments": explicit.get("apartments", 0),
        }
        return {
            "valid": True,
            "path": str(database),
            "project_building_count": project_count,
            "classification_counts": classification_counts,
            "event_count": connection.execute(
                "SELECT COUNT(*) FROM building_classification_event"
            ).fetchone()[0],
            "event_kind_counts": dict(
                connection.execute(
                    "SELECT event_kind, COUNT(*) FROM building_classification_event "
                    "GROUP BY event_kind ORDER BY event_kind"
                )
            ),
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_parser = subparsers.add_parser("set", help="set one building classification")
    set_parser.add_argument("database", type=Path)
    set_parser.add_argument("building_key")
    set_parser.add_argument("classification")
    set_parser.add_argument("event_key")
    set_parser.add_argument("--expected-event-id", type=int)
    undo = subparsers.add_parser("undo", help="undo the latest classification event")
    undo.add_argument("database", type=Path)
    undo.add_argument("building_key")
    undo.add_argument("event_key")
    undo.add_argument("--expected-event-id", type=int)
    get = subparsers.add_parser("get", help="report one building classification")
    get.add_argument("database", type=Path)
    get.add_argument("building_key")
    history = subparsers.add_parser("history", help="report one building history")
    history.add_argument("database", type=Path)
    history.add_argument("building_key")
    info = subparsers.add_parser("info", help="report classification counts")
    info.add_argument("database", type=Path)
    validate = subparsers.add_parser("validate", help="validate classifications")
    validate.add_argument("database", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "set":
            result = set_classification(
                args.database,
                args.building_key,
                args.classification,
                args.event_key,
                expected_event_id=args.expected_event_id,
            )
        elif args.command == "undo":
            result = undo_classification(
                args.database,
                args.building_key,
                args.event_key,
                expected_event_id=args.expected_event_id,
            )
        elif args.command == "get":
            result = classification_get(args.database, args.building_key)
        elif args.command == "history":
            result = classification_history(args.database, args.building_key)
        elif args.command == "info":
            result = classification_info(args.database)
        else:
            errors = validate_database(args.database)
            result = {
                "valid": not errors,
                "path": str(args.database.resolve()),
                "errors": errors,
            }
    except (OSError, RuntimeError, sqlite3.Error, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
