"""Tests for Kane Condo current classifications and append-only history."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DATABASE_DIR = Path(__file__).resolve().parents[1]
ROOT = DATABASE_DIR.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


kane_db = load_module("kane_db_batch014", DATABASE_DIR / "tools" / "kane_db.py")
provenance = load_module(
    "kane_provenance_batch014", DATABASE_DIR / "tools" / "kane_provenance.py"
)
buildings = load_module(
    "kane_buildings_batch014", DATABASE_DIR / "tools" / "kane_buildings.py"
)
project = load_module(
    "kane_project_buildings_batch014",
    DATABASE_DIR / "tools" / "kane_project_buildings.py",
)
classifications = load_module(
    "kane_classifications_batch014",
    DATABASE_DIR / "tools" / "kane_classifications.py",
)


class ClassificationHistoryTests(unittest.TestCase):
    RELEASE_KEY = "kane-buildings-20250730-classification-example"

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_tempdir = tempfile.TemporaryDirectory()
        root = Path(cls.fixture_tempdir.name)
        cls.seeded_template = root / "seeded.gpkg"
        kane_db.initialize_database(cls.seeded_template)
        features = [cls.polygon_feature("B-1"), cls.polygon_feature("B-2", 0.02)]
        raw = json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        geojson = root / "buildings.geojson"
        geojson.write_bytes(raw)
        descriptor = cls.descriptor(raw, len(features))
        descriptor_path = root / "release.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        provenance.record_descriptor(cls.seeded_template, descriptor_path)
        buildings.import_buildings(cls.seeded_template, cls.RELEASE_KEY, geojson)
        project.seed_project_buildings(cls.seeded_template, cls.RELEASE_KEY)
        connection = sqlite3.connect(cls.seeded_template)
        try:
            cls.building_keys = [
                row[0]
                for row in connection.execute(
                    "SELECT building_key FROM project_building ORDER BY project_building_id"
                )
            ]
        finally:
            connection.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_tempdir.cleanup()

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "classifications.gpkg"
        shutil.copy2(self.seeded_template, self.database)
        self.first = self.building_keys[0]
        self.second = self.building_keys[1]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def polygon_feature(feature_id: str, offset: float = 0.0) -> dict[str, object]:
        west = -88.50 + offset
        east = west + 0.01
        south = 41.90 + offset
        north = south + 0.01
        return {
            "type": "Feature",
            "properties": {"FPId": feature_id, "CommonName": f"Building {feature_id}"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south], [east, north],
                    [west, north], [west, south],
                ]],
            },
        }

    @classmethod
    def descriptor(cls, raw: bytes, feature_count: int) -> dict[str, object]:
        digest = hashlib.sha256(raw).hexdigest()
        return {
            "county": {
                "county_key": "kane-county-il",
                "name": "Kane County",
                "state_code": "IL",
                "country_code": "US",
                "fips_code": "17089",
            },
            "agency": {
                "agency_key": "kane-county-gis",
                "name": "Kane County GIS-Technologies",
                "jurisdiction": "Kane County, Illinois",
                "homepage_uri": "https://www.kanecountyil.gov/",
            },
            "dataset": {
                "dataset_key": "buildings",
                "name": "Kane County Building Footprints",
                "description": "Synthetic classification fixture",
                "data_kind": "buildings",
                "source_uri": "https://example.invalid/buildings/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": cls.RELEASE_KEY + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": "FPId"},
                "object_count": feature_count,
            },
            "files": [{
                "file_role": "source",
                "relative_path": "buildings/classification-fixture.geojson",
                "byte_length": len(raw),
                "sha256": digest,
                "media_type": "application/geo+json",
            }],
            "release": {
                "release_key": cls.RELEASE_KEY,
                "lifecycle_status": "accepted",
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": digest,
                "feature_count": feature_count,
                "metadata": {"id_property": "FPId"},
                "accepted_at": "2025-07-30T13:00:00.000Z",
            },
        }

    def event_count(self) -> int:
        connection = sqlite3.connect(self.database)
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM building_classification_event"
            ).fetchone()[0]
        finally:
            connection.close()

    def test_schema_registration_and_default_unclassified_state(self) -> None:
        self.assertEqual([], classifications.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                classifications.EVENT_COLUMNS,
                classifications.table_columns(connection, classifications.EVENT_TABLE),
            )
            self.assertEqual(
                classifications.CURRENT_COLUMNS,
                classifications.table_columns(connection, classifications.CURRENT_TABLE),
            )
            self.assertEqual(
                7,
                connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0],
            )
            self.assertEqual(
                0,
                connection.execute(
                    "SELECT COUNT(*) FROM building_classification_current"
                ).fetchone()[0],
            )
        finally:
            connection.close()
        info = classifications.classification_info(self.database)
        self.assertEqual(
            {"unclassified": 2, "other": 0, "condominium": 0, "apartments": 0},
            info["classification_counts"],
        )

    def test_set_classification_writes_current_and_history(self) -> None:
        result = classifications.set_classification(
            self.database, self.first, "other", "event:set-other"
        )
        self.assertTrue(result["changed"])
        self.assertEqual("other", result["classification"])
        connection = sqlite3.connect(self.database)
        try:
            current = connection.execute(
                "SELECT classification, classification_event_id "
                "FROM building_classification_current"
            ).fetchone()
            event = connection.execute(
                "SELECT event_kind, previous_classification, new_classification "
                "FROM building_classification_event"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(("other", result["classification_event_id"]), current)
        self.assertEqual(("classification", "unclassified", "other"), event)

    def test_same_classification_creates_no_redundant_event(self) -> None:
        classifications.set_classification(
            self.database, self.first, "other", "event:first"
        )
        result = classifications.set_classification(
            self.database, self.first, "other", "event:no-op"
        )
        self.assertFalse(result["changed"])
        self.assertFalse(result["replayed"])
        self.assertEqual(1, self.event_count())

    def test_correction_and_return_to_unclassified_preserve_history(self) -> None:
        first = classifications.set_classification(
            self.database, self.first, "other", "event:other"
        )
        second = classifications.set_classification(
            self.database, self.first, "condominium", "event:condo",
            expected_event_id=first["classification_event_id"],
        )
        third = classifications.set_classification(
            self.database, self.first, "unclassified", "event:reset",
            expected_event_id=second["classification_event_id"],
        )
        self.assertEqual("unclassified", third["classification"])
        self.assertEqual(3, self.event_count())
        connection = sqlite3.connect(self.database)
        try:
            self.assertIsNone(
                connection.execute(
                    "SELECT classification FROM building_classification_current"
                ).fetchone()
            )
            chain = connection.execute(
                "SELECT event_kind, previous_classification, new_classification "
                "FROM building_classification_event ORDER BY classification_event_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [
                ("classification", "unclassified", "other"),
                ("correction", "other", "condominium"),
                ("correction", "condominium", "unclassified"),
            ],
            chain,
        )

    def test_undo_reverses_latest_event_and_appends_history(self) -> None:
        first = classifications.set_classification(
            self.database, self.first, "other", "event:other"
        )
        second = classifications.set_classification(
            self.database, self.first, "apartments", "event:apartments"
        )
        undo = classifications.undo_classification(
            self.database,
            self.first,
            "event:undo",
            expected_event_id=second["classification_event_id"],
        )
        self.assertEqual("other", undo["classification"])
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT event_kind, previous_classification, new_classification, "
                "predecessor_event_id, reverses_event_id "
                "FROM building_classification_event ORDER BY classification_event_id DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(
            ("undo", "apartments", "other", second["classification_event_id"],
             second["classification_event_id"]),
            row,
        )
        self.assertEqual(3, self.event_count())
        self.assertNotEqual(first["classification_event_id"], undo["classification_event_id"])

    def test_undo_without_history_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no classification event"):
            classifications.undo_classification(
                self.database, self.first, "event:undo-empty"
            )

    def test_event_key_retry_is_idempotent(self) -> None:
        first = classifications.set_classification(
            self.database, self.first, "condominium", "request:123"
        )
        replay = classifications.set_classification(
            self.database, self.first, "condominium", "request:123",
            expected_event_id=999999,
        )
        self.assertFalse(replay["changed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["classification_event_id"], replay["classification_event_id"])
        self.assertEqual(1, self.event_count())

    def test_event_key_conflict_is_rejected(self) -> None:
        classifications.set_classification(
            self.database, self.first, "other", "request:conflict"
        )
        with self.assertRaisesRegex(RuntimeError, "different classification action"):
            classifications.set_classification(
                self.database, self.second, "other", "request:conflict"
            )
        with self.assertRaisesRegex(RuntimeError, "different classification action"):
            classifications.set_classification(
                self.database, self.first, "apartments", "request:conflict"
            )
        self.assertEqual(1, self.event_count())

    def test_stale_expected_event_is_rejected(self) -> None:
        current = classifications.set_classification(
            self.database, self.first, "other", "event:current"
        )
        with self.assertRaisesRegex(RuntimeError, "Stale classification state"):
            classifications.set_classification(
                self.database, self.first, "apartments", "event:stale",
                expected_event_id=current["classification_event_id"] + 1,
            )
        self.assertEqual(1, self.event_count())

    def test_invalid_classification_and_event_key_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "classification must be"):
            classifications.set_classification(
                self.database, self.first, "factory", "event:invalid-class"
            )
        with self.assertRaisesRegex(RuntimeError, "event_key must be"):
            classifications.set_classification(
                self.database, self.first, "other", "invalid event key"
            )
        self.assertEqual(0, self.event_count())

    def test_inactive_building_cannot_be_classified(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE project_building SET lifecycle_status = 'inactive' "
                "WHERE building_key = ?",
                (self.first,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "Only active"):
            classifications.set_classification(
                self.database, self.first, "other", "event:inactive"
            )

    def test_history_is_append_only(self) -> None:
        result = classifications.set_classification(
            self.database, self.first, "other", "event:immutable"
        )
        connection = sqlite3.connect(self.database)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE building_classification_event SET new_classification = "
                    "'apartments' WHERE classification_event_id = ?",
                    (result["classification_event_id"],),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "DELETE FROM building_classification_event "
                    "WHERE classification_event_id = ?",
                    (result["classification_event_id"],),
                )
        finally:
            connection.close()

    def test_current_row_must_match_event(self) -> None:
        classifications.set_classification(
            self.database, self.first, "other", "event:match"
        )
        connection = sqlite3.connect(self.database)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "does not match"):
                connection.execute(
                    "UPDATE building_classification_current "
                    "SET classification = 'apartments'"
                )
        finally:
            connection.close()

    def test_validation_detects_stale_current_row(self) -> None:
        classifications.set_classification(
            self.database, self.first, "other", "event:stale-current"
        )
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("DROP TRIGGER tr_classification_current_update_match")
            connection.execute(
                "UPDATE building_classification_current SET classification = 'apartments'"
            )
            connection.executescript(
                "CREATE TRIGGER tr_classification_current_update_match "
                "BEFORE UPDATE ON building_classification_current BEGIN "
                "SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM "
                "building_classification_event event WHERE "
                "event.classification_event_id = NEW.classification_event_id AND "
                "event.project_building_id = NEW.project_building_id AND "
                "event.new_classification = NEW.classification) THEN "
                "RAISE(ABORT, 'current classification does not match its event') END; END;"
            )
            connection.commit()
        finally:
            connection.close()
        errors = classifications.validate_database(self.database)
        self.assertTrue(any("current classification is stale" in error for error in errors))

    def test_validation_detects_broken_event_chain(self) -> None:
        classifications.set_classification(
            self.database, self.first, "other", "event:chain-1"
        )
        classifications.set_classification(
            self.database, self.first, "condominium", "event:chain-2"
        )
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("DROP TRIGGER tr_classification_event_no_update")
            connection.execute(
                "UPDATE building_classification_event SET previous_classification = "
                "'apartments' WHERE event_key = 'event:chain-2'"
            )
            connection.executescript(
                "CREATE TRIGGER tr_classification_event_no_update "
                "BEFORE UPDATE ON building_classification_event BEGIN "
                "SELECT RAISE(ABORT, 'building classification history is append-only'); END;"
            )
            connection.commit()
        finally:
            connection.close()
        errors = classifications.validate_database(self.database)
        self.assertTrue(any("previous state breaks the chain" in error for error in errors))

    def test_get_history_and_info_omit_geometry(self) -> None:
        classifications.set_classification(
            self.database, self.first, "condominium", "event:reports"
        )
        current = classifications.classification_get(self.database, self.first)
        history = classifications.classification_history(self.database, self.first)
        info = classifications.classification_info(self.database)
        self.assertEqual("condominium", current["classification"])
        self.assertEqual(1, len(history["events"]))
        self.assertEqual(1, info["classification_counts"]["condominium"])
        self.assertEqual(1, info["classification_counts"]["unclassified"])
        self.assertNotIn("geometry", json.dumps([current, history, info]))

    def test_cli_set_get_history_undo_and_validate(self) -> None:
        command = str(DATABASE_DIR / "kane-classifications.sh")
        set_result = subprocess.run(
            ["bash", command, "set", str(self.database), self.first,
             "apartments", "cli:set"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        event_id = json.loads(set_result.stdout)["classification_event_id"]
        get_result = subprocess.run(
            ["bash", command, "get", str(self.database), self.first],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("apartments", json.loads(get_result.stdout)["classification"])
        history_result = subprocess.run(
            ["bash", command, "history", str(self.database), self.first],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, len(json.loads(history_result.stdout)["events"]))
        undo_result = subprocess.run(
            ["bash", command, "undo", str(self.database), self.first, "cli:undo",
             "--expected-event-id", str(event_id)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("unclassified", json.loads(undo_result.stdout)["classification"])
        validated = subprocess.run(
            ["bash", command, "validate", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(json.loads(validated.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
