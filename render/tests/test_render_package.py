#!/usr/bin/env python3
"""Regression tests for Batch 033 reproducible complete render-package builds."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "render/tools/kane_render_package.py"
WRAPPER = ROOT / "render/kane-render-package.sh"
FORMAT_DOC = ROOT / "render/REPRODUCIBLE_PACKAGE_BUILD.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE = load_module("_kane_render_package_test", MODULE_PATH)
GEOMETRY = load_module("_kane_render_package_geometry_test", ROOT / "database/tools/kane_geometry.py")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RenderPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.package = self.root / "package"
        self.second = self.root / "package-second"
        self._create_database()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE county (
                county_id INTEGER PRIMARY KEY,
                county_key TEXT NOT NULL,
                name TEXT NOT NULL,
                state_code TEXT NOT NULL,
                fips_code TEXT NOT NULL
            );
            CREATE TABLE dataset (
                dataset_id INTEGER PRIMARY KEY,
                dataset_key TEXT NOT NULL,
                county_id INTEGER NOT NULL
            );
            CREATE TABLE source_release (
                source_release_id INTEGER PRIMARY KEY,
                dataset_id INTEGER NOT NULL,
                release_key TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                feature_count INTEGER NOT NULL
            );
            CREATE TABLE source_county_boundary (
                source_boundary_id INTEGER PRIMARY KEY,
                source_release_id INTEGER NOT NULL,
                source_feature_id TEXT NOT NULL,
                geometry BLOB NOT NULL,
                geometry_type TEXT NOT NULL,
                geometry_sha256 TEXT NOT NULL,
                min_x REAL NOT NULL,
                min_y REAL NOT NULL,
                max_x REAL NOT NULL,
                max_y REAL NOT NULL
            );
            CREATE TABLE source_map_feature (
                source_map_feature_id INTEGER PRIMARY KEY,
                source_release_id INTEGER NOT NULL,
                source_feature_id TEXT NOT NULL,
                source_ordinal INTEGER NOT NULL,
                geometry BLOB NOT NULL,
                geometry_type TEXT NOT NULL,
                geometry_sha256 TEXT NOT NULL,
                min_x REAL NOT NULL,
                min_y REAL NOT NULL,
                max_x REAL NOT NULL,
                max_y REAL NOT NULL
            );
            CREATE TABLE source_building (
                source_building_id INTEGER PRIMARY KEY,
                source_release_id INTEGER NOT NULL,
                source_feature_id TEXT NOT NULL,
                source_ordinal INTEGER NOT NULL,
                geometry BLOB NOT NULL,
                geometry_type TEXT NOT NULL,
                geometry_sha256 TEXT NOT NULL,
                min_x REAL NOT NULL,
                min_y REAL NOT NULL,
                max_x REAL NOT NULL,
                max_y REAL NOT NULL
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
        connection.execute(
            "INSERT INTO county VALUES (1, 'kane-county-il', 'Kane County', 'IL', '17089')"
        )
        datasets = (
            (1, "county-boundary"),
            (2, "roads"),
            (3, "water-fox-river"),
            (4, "water-creeks"),
            (5, "buildings"),
        )
        for dataset_id, key in datasets:
            connection.execute("INSERT INTO dataset VALUES (?, ?, 1)", (dataset_id, key))
            connection.execute(
                "INSERT INTO source_release VALUES (?, ?, ?, 'accepted', ?, 1)",
                (dataset_id, dataset_id, f"{key}-test", f"{dataset_id:x}" * 64),
            )

        boundary = [
            [-88.60, 41.72],
            [-88.24, 41.72],
            [-88.24, 42.15],
            [-88.60, 42.15],
            [-88.60, 41.72],
        ]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_polygon("Polygon", [boundary])
        connection.execute(
            "INSERT INTO source_county_boundary VALUES (1, 1, 'boundary-1', ?, 'Polygon', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )

        road = [[-88.58, 41.75], [-88.50, 41.90], [-88.35, 42.10]]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_geometry("LineString", road)
        connection.execute(
            "INSERT INTO source_map_feature VALUES (1, 2, 'road-1', 1, ?, 'LineString', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )

        fox = [
            [-88.31, 41.73],
            [-88.29, 41.73],
            [-88.29, 42.14],
            [-88.31, 42.14],
            [-88.31, 41.73],
        ]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_polygon("Polygon", [fox])
        connection.execute(
            "INSERT INTO source_map_feature VALUES (2, 3, 'fox-1', 1, ?, 'Polygon', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )

        creek = [[-88.55, 41.80], [-88.45, 41.88], [-88.30, 41.95]]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_geometry("LineString", creek)
        connection.execute(
            "INSERT INTO source_map_feature VALUES (3, 4, 'creek-1', 1, ?, 'LineString', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )

        building = [
            [-88.40, 41.90],
            [-88.399, 41.90],
            [-88.399, 41.901],
            [-88.40, 41.901],
            [-88.40, 41.90],
        ]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_polygon("Polygon", [building])
        connection.execute(
            "INSERT INTO source_building VALUES (1, 5, 'FP-1', 1, ?, 'Polygon', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )
        building_key = "kcb-" + sha256(b"FP-1")
        connection.execute(
            "INSERT INTO project_building VALUES (1, ?, 'active')", (building_key,)
        )
        connection.execute(
            "INSERT INTO project_building_source_mapping VALUES (1, 1, 1, 'confirmed')"
        )
        connection.execute(
            "INSERT INTO building_classification_event VALUES (1, 1, 'other')"
        )
        connection.execute(
            "INSERT INTO building_classification_current VALUES (1, 'other', 1)"
        )
        connection.commit()
        connection.close()

    def build(self, target: Path | None = None, created_at: str | None = None):
        return PACKAGE.build_package(
            self.database, target or self.package, created_at=created_at
        )

    def test_build_creates_exact_complete_inventory_and_validates(self) -> None:
        result = self.build(created_at="2026-08-14T20:10:00Z")
        self.assertEqual("built", result["status"])
        self.assertEqual(set(PACKAGE.PACKAGE_FILES.values()), {p.name for p in self.package.iterdir()})
        validated = PACKAGE.validate_package(self.database, self.package)
        self.assertEqual("valid", validated["status"])
        self.assertEqual(result["package_content_sha256"], validated["package_content_sha256"])

    def test_repeated_build_with_same_created_at_is_byte_identical(self) -> None:
        created = "2026-08-14T20:11:00Z"
        self.build(self.package, created)
        self.build(self.second, created)
        for filename in PACKAGE.PACKAGE_FILES.values():
            self.assertEqual((self.package / filename).read_bytes(), (self.second / filename).read_bytes())
        compared = PACKAGE.compare_packages(self.database, self.package, self.second)
        self.assertTrue(compared["manifest_bytes_identical"])
        self.assertEqual("reproducible", compared["status"])

    def test_different_created_at_is_only_intentional_difference(self) -> None:
        first = self.build(self.package, "2026-08-14T20:12:00Z")
        second = self.build(self.second, "2026-08-14T20:12:01Z")
        self.assertEqual(first["package_content_sha256"], second["package_content_sha256"])
        compared = PACKAGE.compare_packages(self.database, self.package, self.second)
        self.assertFalse(compared["manifest_bytes_identical"])
        self.assertEqual(
            ["2026-08-14T20:12:00Z", "2026-08-14T20:12:01Z"], compared["created_at"]
        )

    def test_rebuild_regenerates_tampered_component_instead_of_reusing_it(self) -> None:
        self.build(self.package, "2026-08-14T20:13:00Z")
        original = (self.package / "roads-lod.krf").read_bytes()
        (self.package / "roads-lod.krf").write_bytes(b"not a road container")
        self.build(self.package, "2026-08-14T20:13:00Z")
        self.assertEqual(original, (self.package / "roads-lod.krf").read_bytes())
        self.assertEqual("valid", PACKAGE.validate_package(self.database, self.package)["status"])

    def test_failed_staged_build_preserves_existing_complete_package(self) -> None:
        self.build(self.package, "2026-08-14T20:14:00Z")
        before = {name: (self.package / name).read_bytes() for name in PACKAGE.PACKAGE_FILES.values()}
        with mock.patch.object(PACKAGE.BUILDING, "write_container", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                self.build(self.package, "2026-08-14T20:14:01Z")
        after = {name: (self.package / name).read_bytes() for name in PACKAGE.PACKAGE_FILES.values()}
        self.assertEqual(before, after)
        self.assertFalse(any(p.name.startswith(".package.stage-") for p in self.root.iterdir()))

    def test_promotion_failure_rolls_back_existing_package(self) -> None:
        self.build(self.package, "2026-08-14T20:15:00Z")
        before = {name: (self.package / name).read_bytes() for name in PACKAGE.PACKAGE_FILES.values()}
        real_replace = os.replace

        def fail_new_into_destination(src, dst):
            src_path = Path(src)
            dst_path = Path(dst)
            if src_path.name.startswith(".package.stage-") and dst_path == self.package:
                raise OSError("promotion failure")
            return real_replace(src, dst)

        with mock.patch.object(PACKAGE.os, "replace", side_effect=fail_new_into_destination):
            with self.assertRaisesRegex(OSError, "promotion failure"):
                self.build(self.package, "2026-08-14T20:15:01Z")
        after = {name: (self.package / name).read_bytes() for name in PACKAGE.PACKAGE_FILES.values()}
        self.assertEqual(before, after)
        self.assertFalse(PACKAGE._backup_path(self.package).exists())

    def test_interrupted_promotion_recovery_restores_old_and_cleans_stage(self) -> None:
        self.build(self.package, "2026-08-14T20:16:00Z")
        backup = PACKAGE._backup_path(self.package)
        os.replace(self.package, backup)
        stale = self.root / ".package.stage-stale"
        stale.mkdir()
        (stale / "partial").write_text("partial", encoding="utf-8")
        PACKAGE.recover_interrupted_promotion(self.package)
        self.assertTrue(self.package.is_dir())
        self.assertFalse(backup.exists())
        self.assertFalse(stale.exists())
        self.assertEqual("valid", PACKAGE.validate_package(self.database, self.package)["status"])

    def test_validation_rejects_tampered_component(self) -> None:
        self.build(self.package, "2026-08-14T20:17:00Z")
        target = self.package / "classification-snapshot.json"
        data = bytearray(target.read_bytes())
        data[-1] ^= 0x01
        target.write_bytes(bytes(data))
        with self.assertRaises(RuntimeError):
            PACKAGE.validate_package(self.database, self.package)

    def test_exact_inventory_rejects_extra_or_non_regular_component(self) -> None:
        self.build(self.package, "2026-08-14T20:18:00Z")
        (self.package / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            PACKAGE.summarize_package(self.package)
        (self.package / "extra.txt").unlink()
        manifest = self.package / "render-package-manifest.json"
        manifest.unlink()
        manifest.mkdir()
        with self.assertRaisesRegex(RuntimeError, "regular file"):
            PACKAGE.summarize_package(self.package)

    def test_shell_entry_point_and_documented_exclusions(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        doc = FORMAT_DOC.read_text(encoding="utf-8").lower()
        self.assertIn("created_at", doc)
        self.assertIn("rollback", doc)
        self.assertNotIn("county field map sectors", doc.replace("does not use county field map sectors", ""))

        first = subprocess.run(
            [
                "bash", str(WRAPPER), "build", str(self.database), str(self.package),
                "--created-at", "2026-08-14T20:19:00Z",
            ],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual("built", json.loads(first.stdout)["status"])
        validate = subprocess.run(
            ["bash", str(WRAPPER), "validate", str(self.database), str(self.package)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual("valid", json.loads(validate.stdout)["status"])
        inspect = subprocess.run(
            ["bash", str(WRAPPER), "inspect", str(self.package)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual("2026-08-14T20:19:00Z", json.loads(inspect.stdout)["created_at"])
        subprocess.run(
            [
                "bash", str(WRAPPER), "build", str(self.database), str(self.second),
                "--created-at", "2026-08-14T20:19:00Z",
            ],
            check=True, capture_output=True, text=True,
        )
        compare = subprocess.run(
            ["bash", str(WRAPPER), "compare", str(self.database), str(self.package), str(self.second)],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual("reproducible", json.loads(compare.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
