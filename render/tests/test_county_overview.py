#!/usr/bin/env python3
"""Regression tests for the Batch 027 county overview payload."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "render/tools/kane_county_overview.py"
WRAPPER = ROOT / "render/kane-county-overview.sh"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OVERVIEW = load_module("_kane_county_overview_test", MODULE_PATH)
GEOMETRY = load_module("_kane_county_overview_geometry_test", ROOT / "database/tools/kane_geometry.py")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CountyOverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.output = self.root / "county-overview.json"
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
            """
        )
        connection.execute(
            "INSERT INTO county VALUES (1, 'kane-county-il', 'Kane County', 'IL', '17089')"
        )
        connection.execute("INSERT INTO dataset VALUES (1, 'county-boundary', 1)")
        connection.execute(
            "INSERT INTO source_release VALUES (1, 1, 'kane-boundary-test', 'accepted', ?, 1)",
            ("a" * 64,),
        )
        ring = [
            [-88.0, 41.5], [-87.9, 41.5], [-87.8, 41.5], [-87.7, 41.5],
            [-87.7, 41.7], [-87.7, 41.9], [-87.8, 41.9], [-87.9, 41.9],
            [-88.0, 41.9], [-88.0, 41.7], [-88.0, 41.5],
        ]
        hole = [
            [-87.9, 41.6], [-87.8, 41.6], [-87.8, 41.7], [-87.9, 41.7], [-87.9, 41.6]
        ]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_polygon("Polygon", [ring, hole])
        connection.execute(
            "INSERT INTO source_county_boundary VALUES (1, 1, 'boundary-1', ?, 'Polygon', ?, ?, ?, ?, ?)",
            (blob, sha256(wkb), *bounds),
        )
        connection.commit()
        connection.close()

    def read_output(self) -> dict[str, object]:
        return json.loads(self.output.read_text(encoding="utf-8"))

    def test_build_is_deterministic(self) -> None:
        first = OVERVIEW.build_overview(self.database, self.output)
        first_bytes = self.output.read_bytes()
        second = OVERVIEW.build_overview(self.database, self.output)
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["sha256"], sha256(first_bytes))
        self.assertFalse((self.root / "county-overview.json.sha256").exists())

    def test_fit_metadata_uses_exact_source_bounds(self) -> None:
        OVERVIEW.build_overview(self.database, self.output)
        document = self.read_output()
        self.assertEqual([-88.0, 41.5, -87.7, 41.9], document["fit"]["bounds"])
        self.assertEqual([-87.85, 41.7], document["fit"]["center"])
        self.assertAlmostEqual(0.3, document["fit"]["width"])
        self.assertAlmostEqual(0.4, document["fit"]["height"])

    def test_exterior_outline_is_simplified_and_holes_omitted(self) -> None:
        OVERVIEW.build_overview(self.database, self.output)
        outline = self.read_output()["outline"]
        self.assertEqual(1, outline["ring_count"])
        self.assertEqual(1, outline["source_interior_ring_count"])
        self.assertLess(outline["vertex_count"], outline["source_vertex_count"])
        ring = outline["rings"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertGreaterEqual(len(set(map(tuple, ring[:-1]))), 3)

    def test_rejects_ambiguous_accepted_boundary(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO source_release VALUES (2, 1, 'other', 'accepted', ?, 1)",
            ("b" * 64,),
        )
        row = connection.execute(
            "SELECT geometry, geometry_type, geometry_sha256, min_x, min_y, max_x, max_y "
            "FROM source_county_boundary WHERE source_boundary_id = 1"
        ).fetchone()
        connection.execute(
            "INSERT INTO source_county_boundary VALUES (2, 2, 'boundary-2', ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "count is 2"):
            OVERVIEW.build_document(self.database)

    def test_rejects_geometry_hash_mismatch(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE source_county_boundary SET geometry_sha256 = ?", ("0" * 64,))
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "geometry SHA-256"):
            OVERVIEW.build_document(self.database)

    def test_contract_excludes_grid_void_and_variable_metadata(self) -> None:
        OVERVIEW.build_overview(self.database, self.output)
        text = self.output.read_text(encoding="utf-8").lower()
        self.assertNotIn("void", text)
        self.assertNotIn("sector", text)
        self.assertNotIn("cell", text)
        self.assertNotIn("created_at", text)
        self.assertNotIn("timestamp", text)
        document = self.read_output()
        self.assertEqual("kane-condo-county-overview", document["format"])
        self.assertEqual(1, document["version"])
        self.assertEqual(4326, document["srs_id"])

    def test_shell_entry_point_builds_payload(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        result = subprocess.run(
            ["bash", str(WRAPPER), "build", str(self.database), str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(result.stdout)
        self.assertEqual(str(self.output.resolve()), summary["output_file"])
        self.assertTrue(self.output.is_file())


if __name__ == "__main__":
    unittest.main()
