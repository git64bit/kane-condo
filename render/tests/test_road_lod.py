#!/usr/bin/env python3
"""Regression tests for the Batch 028 road levels of detail."""

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
MODULE_PATH = ROOT / "render/tools/kane_road_lod.py"
WRAPPER = ROOT / "render/kane-road-lod.sh"
FORMAT_DOC = ROOT / "render/ROAD_LOD_FORMAT.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROAD_LOD = load_module("_kane_road_lod_test", MODULE_PATH)
GEOMETRY = load_module("_kane_road_lod_geometry_test", ROOT / "database/tools/kane_geometry.py")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_json_coordinates(value):
    if isinstance(value, tuple):
        return [as_json_coordinates(item) for item in value]
    if isinstance(value, list):
        return [as_json_coordinates(item) for item in value]
    return value


class RoadLodTests(unittest.TestCase):
    FEATURE_COUNT = 300

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.output = self.root / "roads-lod.krf"
        self.source_geometries: dict[str, tuple[str, object]] = {}
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
            """
        )
        connection.execute(
            "INSERT INTO county VALUES (1, 'kane-county-il', 'Kane County', 'IL', '17089')"
        )
        connection.execute("INSERT INTO dataset VALUES (1, 'roads', 1)")
        connection.execute(
            "INSERT INTO source_release VALUES (1, 1, 'kane-roads-test', 'accepted', ?, ?)",
            ("a" * 64, self.FEATURE_COUNT),
        )
        for index in range(self.FEATURE_COUNT):
            source_id = str(index + 1)
            col = index % 30
            row = index // 30
            x = -88.60 + col * 0.010
            y = 41.72 + row * 0.040
            length = 0.001 + index * 0.000012
            wiggle = 0.000008
            first = [
                [x, y],
                [x + length * 0.25, y + wiggle],
                [x + length * 0.50, y],
                [x + length * 0.75, y - wiggle],
                [x + length, y],
            ]
            if index % 50 == 0:
                second = [
                    [x + length, y],
                    [x + length * 1.15, y + wiggle],
                    [x + length * 1.30, y],
                ]
                geometry_type = "MultiLineString"
                coordinates = [first, second]
            else:
                geometry_type = "LineString"
                coordinates = first
            blob, wkb, bounds = GEOMETRY.encode_geopackage_geometry(
                geometry_type, coordinates
            )
            self.source_geometries[source_id] = (geometry_type, coordinates)
            connection.execute(
                "INSERT INTO source_map_feature VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    index + 1,
                    source_id,
                    index + 1,
                    blob,
                    geometry_type,
                    sha256(wkb),
                    *bounds,
                ),
            )
        connection.commit()
        connection.close()

    def build(self):
        return ROAD_LOD.write_container(self.database, self.output)

    def read(self):
        return ROAD_LOD.read_container_bytes(self.output.read_bytes())

    def test_build_is_byte_deterministic_without_sidecars(self) -> None:
        first = self.build()
        first_bytes = self.output.read_bytes()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["sha256"], sha256(first_bytes))
        self.assertFalse((self.root / "roads-lod.krf.sha256").exists())

    def test_levels_are_monotonic_and_detail_is_complete(self) -> None:
        self.build()
        index, levels = self.read()
        orientation = {record["source_feature_id"] for record in levels["orientation"]}
        context = {record["source_feature_id"] for record in levels["context"]}
        detail = {record["source_feature_id"] for record in levels["detail"]}
        self.assertTrue(orientation)
        self.assertLess(len(orientation), len(context))
        self.assertLess(len(context), len(detail))
        self.assertTrue(orientation.issubset(context))
        self.assertTrue(context.issubset(detail))
        self.assertEqual(self.FEATURE_COUNT, len(detail))
        self.assertEqual(self.FEATURE_COUNT, index["source"]["feature_count"])

    def test_detail_preserves_exact_source_geometry(self) -> None:
        self.build()
        _index, levels = self.read()
        detail = {record["source_feature_id"]: record for record in levels["detail"]}
        for source_id, (geometry_type, coordinates) in self.source_geometries.items():
            record = detail[source_id]
            self.assertEqual(geometry_type, record["geometry_type"])
            self.assertEqual(as_json_coordinates(coordinates), record["coordinates"])

    def test_simplification_preserves_line_endpoints(self) -> None:
        self.build()
        index, levels = self.read()
        by_level = {item["key"]: item for item in index["levels"]}
        self.assertLess(
            by_level["orientation"]["vertex_count"],
            by_level["orientation"]["source_vertex_count"],
        )
        self.assertLess(
            by_level["context"]["vertex_count"],
            by_level["context"]["source_vertex_count"],
        )
        for key in ("orientation", "context"):
            for record in levels[key]:
                source_type, source_coordinates = self.source_geometries[record["source_feature_id"]]
                source_lines = ROAD_LOD.geometry_lines(source_type, source_coordinates)
                output_lines = ROAD_LOD.geometry_lines(record["geometry_type"], record["coordinates"])
                self.assertEqual(len(source_lines), len(output_lines))
                for source_line, output_line in zip(source_lines, output_lines):
                    self.assertEqual(list(source_line[0]), list(output_line[0]))
                    self.assertEqual(list(source_line[-1]), list(output_line[-1]))

    def test_chunks_keep_whole_features_and_have_no_duplicate_identity(self) -> None:
        self.build()
        index, levels = self.read()
        detail_index = next(level for level in index["levels"] if level["key"] == "detail")
        self.assertEqual(2, len(detail_index["chunks"]))
        self.assertEqual(256, detail_index["chunks"][0]["feature_count"])
        self.assertEqual(44, detail_index["chunks"][1]["feature_count"])
        identities = [record["source_feature_id"] for record in levels["detail"]]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(self.FEATURE_COUNT, len(identities))

    def test_tampered_payload_is_rejected(self) -> None:
        self.build()
        data = bytearray(self.output.read_bytes())
        data[-1] ^= 0x01
        with self.assertRaisesRegex(RuntimeError, "payload SHA-256|compression"):
            ROAD_LOD.read_container_bytes(bytes(data))

    def test_rejects_ambiguous_accepted_road_release(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO source_release VALUES (2, 1, 'other-roads', 'accepted', ?, 0)",
            ("b" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "count is 2"):
            ROAD_LOD.build_container(self.database)

    def test_rejects_release_count_and_geometry_hash_mismatch(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE source_release SET feature_count = feature_count - 1")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "stored feature count"):
            ROAD_LOD.build_container(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE source_release SET feature_count = ?", (self.FEATURE_COUNT,))
        connection.execute(
            "UPDATE source_map_feature SET geometry_sha256 = ? WHERE source_map_feature_id = 1",
            ("0" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "geometry SHA-256"):
            ROAD_LOD.build_container(self.database)

    def test_contract_excludes_unavailable_semantics_and_obsolete_grid_state(self) -> None:
        self.build()
        index, _levels = self.read()
        text = json.dumps(index, sort_keys=True).lower()
        self.assertEqual("kane-condo-road-lod", index["format"])
        self.assertEqual(1, index["version"])
        self.assertEqual(4326, index["srs_id"])
        self.assertEqual("deterministic-coordinate-length-score", index["selection"]["basis"])
        for forbidden in (
            "void",
            "sector",
            "inspection_cell",
            "created_at",
            "timestamp",
            "functional_class",
            "route_name",
        ):
            self.assertNotIn(forbidden, text)
        document = FORMAT_DOC.read_text(encoding="utf-8")
        self.assertIn("does **not**\nclaim", document)
        self.assertIn("Features are never clipped to chunk boundaries", document)

    def test_shell_entry_point_builds_and_inspects_container(self) -> None:
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        build = subprocess.run(
            ["bash", str(WRAPPER), "build", str(self.database), str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(build.stdout)
        self.assertEqual(str(self.output.resolve()), summary["output_file"])
        inspect = subprocess.run(
            ["bash", str(WRAPPER), "inspect", str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        inspected = json.loads(inspect.stdout)
        self.assertEqual(summary["sha256"], inspected["sha256"])
        self.assertEqual("kane-roads-test", inspected["source_release"])
        self.assertEqual(self.FEATURE_COUNT, inspected["level_feature_counts"]["detail"])


if __name__ == "__main__":
    unittest.main()
