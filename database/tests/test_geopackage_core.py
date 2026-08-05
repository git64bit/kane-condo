"""Tests for the Kane Condo GeoPackage 1.4.0 foundation."""

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

DATABASE_DIR = Path(__file__).resolve().parents[1]
ROOT = DATABASE_DIR.parent
MODULE_PATH = DATABASE_DIR / "tools" / "kane_db.py"
MIGRATION_PATH = DATABASE_DIR / "migrations" / "0001_geopackage_core.sql"
SPEC = importlib.util.spec_from_file_location("kane_db", MODULE_PATH)
kane_db = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = kane_db
assert SPEC.loader is not None
SPEC.loader.exec_module(kane_db)


class GeoPackageCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Path(self.tempdir.name) / "foundation.gpkg"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def initialize(self) -> None:
        kane_db.initialize_database(self.database)

    def test_initialize_and_validate_empty_geopackage(self) -> None:
        self.initialize()
        self.assertEqual([], kane_db.validate_database(self.database))
        self.assertEqual(b"SQLite format 3\x00", self.database.read_bytes()[:16])

        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                kane_db.GPKG_APPLICATION_ID,
                connection.execute("PRAGMA application_id").fetchone()[0],
            )
            self.assertEqual(
                kane_db.GPKG_USER_VERSION,
                connection.execute("PRAGMA user_version").fetchone()[0],
            )
            self.assertEqual([("ok",)], connection.execute("PRAGMA integrity_check").fetchall())
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())
        finally:
            connection.close()

    def test_core_tables_and_required_srs_rows_exist(self) -> None:
        self.initialize()
        connection = sqlite3.connect(self.database)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(kane_db.REQUIRED_TABLES, tables)
            self.assertEqual(
                3, connection.execute("SELECT COUNT(*) FROM gpkg_geometry_columns").fetchone()[0]
            )
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM gpkg_extensions").fetchone()[0]
            )
            rows = connection.execute(
                "SELECT srs_id, organization, organization_coordsys_id, definition "
                "FROM gpkg_spatial_ref_sys ORDER BY srs_id"
            ).fetchall()
            self.assertEqual((-1, "NONE", -1, "undefined"), rows[0])
            self.assertEqual((0, "NONE", 0, "undefined"), rows[1])
            self.assertEqual(4326, rows[2][0])
            self.assertEqual("EPSG", rows[2][1])
            self.assertEqual(4326, rows[2][2])
        finally:
            connection.close()

    def test_migration_ledger_records_exact_file_identity(self) -> None:
        self.initialize()
        expected_hash = hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest()
        connection = sqlite3.connect(self.database)
        try:
            row = connection.execute(
                "SELECT migration_id, filename, sha256, applied_at FROM schema_migration"
            ).fetchone()
            content = connection.execute(
                "SELECT data_type, identifier, srs_id "
                "FROM gpkg_contents WHERE table_name = 'schema_migration'"
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(1, row[0])
        self.assertEqual(MIGRATION_PATH.name, row[1])
        self.assertEqual(expected_hash, row[2])
        self.assertRegex(row[3], kane_db.DATETIME_PATTERN)
        self.assertEqual(
            ("attributes", "Kane Condo schema migrations", None),
            content,
        )

    def test_database_info_reports_core_identity(self) -> None:
        self.initialize()
        info = kane_db.database_info(self.database)
        self.assertTrue(info["valid"])
        self.assertEqual("1.4.0", info["geopackage_version"])
        self.assertEqual(kane_db.GPKG_APPLICATION_ID, info["application_id"])
        self.assertEqual(kane_db.GPKG_USER_VERSION, info["user_version"])
        self.assertEqual(7, len(info["migrations"]))
        self.assertEqual(MIGRATION_PATH.name, info["migrations"][0]["filename"])

    def test_refuses_non_geopackage_extension(self) -> None:
        with self.assertRaisesRegex(RuntimeError, r"\.gpkg extension"):
            kane_db.initialize_database(Path(self.tempdir.name) / "foundation.sqlite")

    def test_refuses_overwrite(self) -> None:
        self.initialize()
        original = self.database.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            kane_db.initialize_database(self.database)
        self.assertEqual(original, self.database.read_bytes())

    def test_detects_wrong_application_id(self) -> None:
        self.initialize()
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("PRAGMA application_id = 0")
        finally:
            connection.close()
        errors = kane_db.validate_database(self.database)
        self.assertTrue(any("application_id" in error for error in errors))

    def test_detects_migration_hash_tampering(self) -> None:
        self.initialize()
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE schema_migration SET sha256 = ? WHERE migration_id = 1",
                ("0" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        errors = kane_db.validate_database(self.database)
        self.assertTrue(any("migration identity" in error.lower() for error in errors))

    def test_cli_initializes_and_validates(self) -> None:
        init_result = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-db.sh"), "init", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        init_info = json.loads(init_result.stdout)
        self.assertTrue(init_info["valid"])

        validate_result = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-db.sh"), "validate", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        validate_info = json.loads(validate_result.stdout)
        self.assertTrue(validate_info["valid"])
        self.assertEqual([], validate_info["errors"])


if __name__ == "__main__":
    unittest.main()
