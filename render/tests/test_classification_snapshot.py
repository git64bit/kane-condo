#!/usr/bin/env python3
"""Regression tests for the Batch 031 classification snapshot."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "render/tools/kane_classification_snapshot.py"
WRAPPER = ROOT / "render/kane-classification-snapshot.sh"
FORMAT_DOC = ROOT / "render/CLASSIFICATION_SNAPSHOT_FORMAT.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SNAPSHOT = load_module("_kane_classification_snapshot_test", MODULE_PATH)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def building_key(value: int) -> str:
    return f"kcb-{value:064x}"


class ClassificationSnapshotTests(unittest.TestCase):
    RENDER_COUNT = 6

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.output = self.root / "classification-snapshot.json"
        self.keys = {value: building_key(value) for value in range(1, 20)}
        self._create_database()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE dataset (
                dataset_id INTEGER PRIMARY KEY,
                dataset_key TEXT NOT NULL
            );
            CREATE TABLE source_release (
                source_release_id INTEGER PRIMARY KEY,
                dataset_id INTEGER NOT NULL,
                release_key TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                feature_count INTEGER NOT NULL
            );
            CREATE TABLE source_building (
                source_building_id INTEGER PRIMARY KEY,
                source_release_id INTEGER NOT NULL,
                source_ordinal INTEGER NOT NULL
            );
            CREATE TABLE project_building (
                project_building_id INTEGER PRIMARY KEY,
                building_key TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL
            );
            CREATE TABLE project_building_source_mapping (
                mapping_id INTEGER PRIMARY KEY,
                project_building_id INTEGER NOT NULL,
                source_building_id INTEGER NOT NULL,
                mapping_status TEXT NOT NULL
            );
            CREATE TABLE building_classification_event (
                classification_event_id INTEGER PRIMARY KEY,
                project_building_id INTEGER NOT NULL,
                new_classification TEXT NOT NULL
            );
            CREATE TABLE building_classification_current (
                project_building_id INTEGER PRIMARY KEY,
                classification TEXT NOT NULL,
                classification_event_id INTEGER NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO dataset VALUES (1, 'buildings')")
        connection.execute(
            "INSERT INTO source_release VALUES (1, 1, 'buildings-test', 'accepted', ?, ?)",
            ("a" * 64, self.RENDER_COUNT),
        )
        for value in range(1, self.RENDER_COUNT + 1):
            connection.execute("INSERT INTO source_building VALUES (?, 1, ?)", (value, value))
            connection.execute(
                "INSERT INTO project_building VALUES (?, ?, 'active')",
                (value, self.keys[value]),
            )
            connection.execute(
                "INSERT INTO project_building_source_mapping VALUES (?, ?, ?, 'confirmed')",
                (value, value, value),
            )
        # Historical/inactive identity is deliberately outside the current accepted geometry.
        connection.execute(
            "INSERT INTO project_building VALUES (7, ?, 'inactive')", (self.keys[7],)
        )
        self._classify(connection, 2, "other", 101)
        self._classify(connection, 4, "condominium", 102)
        self._classify(connection, 5, "apartments", 103)
        self._classify(connection, 7, "other", 104)
        connection.commit()
        connection.close()

    @staticmethod
    def _classify(
        connection: sqlite3.Connection,
        project_id: int,
        classification: str,
        event_id: int,
    ) -> None:
        connection.execute(
            "INSERT INTO building_classification_event VALUES (?, ?, ?)",
            (event_id, project_id, classification),
        )
        connection.execute(
            "INSERT INTO building_classification_current VALUES (?, ?, ?)",
            (project_id, classification, event_id),
        )

    def build(self):
        return SNAPSHOT.write_snapshot(self.database, self.output)

    def read(self):
        return SNAPSHOT.read_snapshot_bytes(self.output.read_bytes())

    def test_build_is_byte_deterministic_without_sidecars(self) -> None:
        first = self.build()
        first_bytes = self.output.read_bytes()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["sha256"], sha256(first_bytes))
        self.assertFalse((self.root / "classification-snapshot.json.sha256").exists())

    def test_snapshot_is_sparse_and_unclassified_is_default(self) -> None:
        self.build()
        document = self.read()
        self.assertEqual("unclassified", document["default_classification"])
        self.assertEqual(3, document["explicit"]["count"])
        self.assertEqual(
            {
                "apartments": 1,
                "condominium": 1,
                "other": 1,
                "unclassified": 3,
            },
            document["explicit"]["counts"],
        )
        self.assertNotIn("unclassified", [record[1] for record in document["explicit"]["records"]])

    def test_identity_fingerprint_matches_current_render_buildings(self) -> None:
        self.build()
        document = self.read()
        keys = sorted(self.keys[value] for value in range(1, self.RENDER_COUNT + 1))
        expected = sha256(SNAPSHOT.canonical_json_bytes(keys))
        self.assertEqual(self.RENDER_COUNT, document["identity"]["render_building_count"])
        self.assertEqual(expected, document["identity"]["render_identity_sha256"])
        self.assertEqual("buildings-test", document["source"]["release_key"])
        self.assertEqual("a" * 64, document["source"]["release_content_sha256"])

    def test_records_use_only_project_building_key_and_classification(self) -> None:
        self.build()
        document = self.read()
        self.assertEqual(
            [
                [self.keys[2], "other"],
                [self.keys[4], "condominium"],
                [self.keys[5], "apartments"],
            ],
            document["explicit"]["records"],
        )
        text = self.output.read_text(encoding="utf-8")
        self.assertNotIn("project_building_id", text)
        self.assertNotIn("source_feature_id", text)
        self.assertNotIn("geometry", text)

    def test_classification_change_replaces_snapshot_without_changing_identity(self) -> None:
        self.build()
        first_bytes = self.output.read_bytes()
        first = self.read()
        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE building_classification_event SET new_classification = 'apartments' "
            "WHERE classification_event_id = 101"
        )
        connection.execute(
            "UPDATE building_classification_current SET classification = 'apartments' "
            "WHERE project_building_id = 2"
        )
        connection.commit()
        connection.close()
        self.build()
        second = self.read()
        self.assertNotEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["identity"], second["identity"])
        self.assertEqual(first["source"], second["source"])
        self.assertIn([self.keys[2], "apartments"], second["explicit"]["records"])

    def test_non_rendered_explicit_classification_is_counted_but_not_emitted(self) -> None:
        self.build()
        document = self.read()
        self.assertEqual(1, document["explicit"]["non_rendered_explicit_count"])
        emitted = {record[0] for record in document["explicit"]["records"]}
        self.assertNotIn(self.keys[7], emitted)

    def test_rejects_ambiguous_accepted_building_release(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO source_release VALUES (2, 1, 'other', 'accepted', ?, 0)",
            ("b" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "count is 2"):
            SNAPSHOT.load_snapshot_state(self.database)

    def test_rejects_missing_or_ambiguous_current_render_mapping(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM project_building_source_mapping WHERE source_building_id = 1")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "0 confirmed project mappings"):
            SNAPSHOT.load_snapshot_state(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO project_building_source_mapping VALUES (20, 1, 1, 'confirmed')"
        )
        connection.execute(
            "INSERT INTO project_building VALUES (8, ?, 'active')", (self.keys[8],)
        )
        connection.execute(
            "INSERT INTO project_building_source_mapping VALUES (21, 8, 1, 'confirmed')"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "2 confirmed project mappings"):
            SNAPSHOT.load_snapshot_state(self.database)

    def test_rejects_non_active_mapping_and_stale_current_event(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE project_building SET lifecycle_status = 'inactive' WHERE project_building_id = 1")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "non-active"):
            SNAPSHOT.load_snapshot_state(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE project_building SET lifecycle_status = 'active' WHERE project_building_id = 1")
        connection.execute(
            "UPDATE building_classification_current SET classification_event_id = 102 "
            "WHERE project_building_id = 2"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "does not match its event"):
            SNAPSHOT.load_snapshot_state(self.database)

    def test_shell_build_inspect_and_reader_tamper_rejection(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        self.assertIn("building_key", FORMAT_DOC.read_text(encoding="utf-8"))
        build = subprocess.run(
            ["bash", str(WRAPPER), "build", str(self.database), str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(build.stdout)
        self.assertEqual(3, summary["explicit_count"])
        inspect = subprocess.run(
            ["bash", str(WRAPPER), "inspect", str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        inspected = json.loads(inspect.stdout)
        self.assertEqual("buildings-test", inspected["source_release"])
        document = json.loads(self.output.read_text(encoding="utf-8"))
        document["explicit"]["count"] += 1
        tampered = SNAPSHOT.canonical_json_bytes(document)
        with self.assertRaisesRegex(RuntimeError, "explicit count"):
            SNAPSHOT.read_snapshot_bytes(tampered)


if __name__ == "__main__":
    unittest.main()
