"""Tests for Kane Condo administrative provenance and release lineage."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DATABASE_DIR = Path(__file__).resolve().parents[1]
ROOT = DATABASE_DIR.parent
KANE_DB_PATH = DATABASE_DIR / "tools" / "kane_db.py"
PROVENANCE_PATH = DATABASE_DIR / "tools" / "kane_provenance.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


kane_db = load_module("kane_db_batch009", KANE_DB_PATH)
provenance = load_module("kane_provenance_batch009", PROVENANCE_PATH)


class AdministrativeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = self.root / "provenance.gpkg"
        self.descriptor_path = self.root / "release.json"
        kane_db.initialize_database(self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def descriptor(
        self,
        *,
        release_key: str = "kane-buildings-20250730-example",
        harvest_key: str = "kane-buildings-harvest-20250730-example",
        lifecycle_status: str = "candidate",
        accepted_at: str | None = None,
    ) -> dict[str, object]:
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
                "description": "Official building footprint geometry",
                "data_kind": "buildings",
                "source_uri": "https://example.invalid/arcgis/rest/services/buildings/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": harvest_key,
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:05:00.000Z",
                "status": "succeeded",
                "source_metadata": {"object_id_field": "OBJECTID", "stable_id_field": "FPId"},
                "object_count": 208324,
            },
            "files": [
                {
                    "file_role": "source",
                    "relative_path": "buildings/kane-buildings.geojson",
                    "byte_length": 123456789,
                    "sha256": "1" * 64,
                    "media_type": "application/geo+json",
                },
                {
                    "file_role": "manifest",
                    "relative_path": "buildings/kane-buildings.geojson.manifest.json",
                    "byte_length": 4096,
                    "sha256": "2" * 64,
                    "media_type": "application/json",
                },
            ],
            "release": {
                "release_key": release_key,
                "lifecycle_status": lifecycle_status,
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": "3" * 64,
                "feature_count": 208324,
                "metadata": {"source_release": "2025-07-30"},
                "accepted_at": accepted_at,
            },
        }

    def write_descriptor(self, value: dict[str, object]) -> None:
        self.descriptor_path.write_text(json.dumps(value), encoding="utf-8")

    def test_schema_tables_and_geopackage_registrations_exist(self) -> None:
        self.assertEqual([], provenance.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM gpkg_contents WHERE table_name IN "
                    "('county','source_agency','dataset','harvest_run','source_file','source_release')"
                )
            }
            self.assertEqual(provenance.ADMIN_TABLES, tables)
            self.assertEqual(
                4,
                connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0],
            )
        finally:
            connection.close()

    def test_record_and_trace_release_lineage(self) -> None:
        self.write_descriptor(self.descriptor())
        result = provenance.record_descriptor(self.database, self.descriptor_path)
        self.assertEqual("kane-buildings-20250730-example", result["release"]["release_key"])
        self.assertEqual("buildings", result["dataset"]["dataset_key"])
        self.assertEqual("kane-county-gis", result["agency"]["agency_key"])
        self.assertEqual("17089", result["county"]["fips_code"])
        self.assertEqual(2, len(result["harvest"]["files"]))
        self.assertEqual([], provenance.validate_database(self.database))

    def test_shared_administrative_entities_must_match_exactly(self) -> None:
        first = self.descriptor()
        self.write_descriptor(first)
        provenance.record_descriptor(self.database, self.descriptor_path)
        second = self.descriptor(
            release_key="kane-buildings-20250801-example",
            harvest_key="kane-buildings-harvest-20250801-example",
        )
        second["agency"]["name"] = "Conflicting Agency Name"
        self.write_descriptor(second)
        with self.assertRaisesRegex(RuntimeError, "conflicts in fields: name"):
            provenance.record_descriptor(self.database, self.descriptor_path)

    def test_duplicate_release_is_rejected_without_extra_rows(self) -> None:
        self.write_descriptor(self.descriptor())
        provenance.record_descriptor(self.database, self.descriptor_path)
        with self.assertRaisesRegex(RuntimeError, "Source release already exists"):
            provenance.record_descriptor(self.database, self.descriptor_path)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM source_release").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM source_file").fetchone()[0])
        finally:
            connection.close()

    def test_invalid_hash_is_rejected_before_database_write(self) -> None:
        value = self.descriptor()
        value["files"][0]["sha256"] = "not-a-hash"
        self.write_descriptor(value)
        with self.assertRaisesRegex(RuntimeError, "lowercase SHA-256"):
            provenance.record_descriptor(self.database, self.descriptor_path)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM county").fetchone()[0])
        finally:
            connection.close()

    def test_release_requires_succeeded_harvest(self) -> None:
        value = self.descriptor()
        value["harvest"]["status"] = "failed"
        self.write_descriptor(value)
        with self.assertRaisesRegex(RuntimeError, "succeeded harvest"):
            provenance.record_descriptor(self.database, self.descriptor_path)

    def test_accepted_release_requires_accepted_at(self) -> None:
        self.write_descriptor(self.descriptor(lifecycle_status="accepted"))
        with self.assertRaisesRegex(RuntimeError, "requires release.accepted_at"):
            provenance.record_descriptor(self.database, self.descriptor_path)

    def test_one_accepted_release_per_dataset_is_enforced(self) -> None:
        first = self.descriptor(
            lifecycle_status="accepted", accepted_at="2025-07-30T13:00:00.000Z"
        )
        self.write_descriptor(first)
        provenance.record_descriptor(self.database, self.descriptor_path)
        second = self.descriptor(
            release_key="kane-buildings-20250801-example",
            harvest_key="kane-buildings-harvest-20250801-example",
            lifecycle_status="accepted",
            accepted_at="2025-08-01T13:00:00.000Z",
        )
        self.write_descriptor(second)
        with self.assertRaises(sqlite3.IntegrityError):
            provenance.record_descriptor(self.database, self.descriptor_path)

    def test_validation_detects_missing_source_file_lineage(self) -> None:
        self.write_descriptor(self.descriptor())
        provenance.record_descriptor(self.database, self.descriptor_path)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("DELETE FROM source_file")
            connection.commit()
        finally:
            connection.close()
        errors = provenance.validate_database(self.database)
        self.assertTrue(any("no preserved source files" in error for error in errors))

    def test_cli_record_trace_and_validate(self) -> None:
        self.write_descriptor(self.descriptor())
        record = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-provenance.sh"),
                "record",
                str(self.database),
                str(self.descriptor_path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(json.loads(record.stdout)["valid"])
        trace = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-provenance.sh"),
                "trace",
                str(self.database),
                "kane-buildings-20250730-example",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            "buildings", json.loads(trace.stdout)["lineage"]["dataset"]["dataset_key"]
        )
        validate = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-provenance.sh"), "validate", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual([], json.loads(validate.stdout)["errors"])


if __name__ == "__main__":
    unittest.main()
