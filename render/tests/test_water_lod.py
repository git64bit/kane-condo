#!/usr/bin/env python3
"""Regression tests for the Batch 029 water levels of detail."""

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
MODULE_PATH = ROOT / "render/tools/kane_water_lod.py"
WRAPPER = ROOT / "render/kane-water-lod.sh"
FORMAT_DOC = ROOT / "render/WATER_LOD_FORMAT.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WATER_LOD = load_module("_kane_water_lod_test", MODULE_PATH)
GEOMETRY = load_module("_kane_water_lod_geometry_test", ROOT / "database/tools/kane_geometry.py")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_json_coordinates(value):
    if isinstance(value, tuple):
        return [as_json_coordinates(item) for item in value]
    if isinstance(value, list):
        return [as_json_coordinates(item) for item in value]
    return value


class WaterLodTests(unittest.TestCase):
    CREEK_COUNT = 300

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.output = self.root / "water-lod.krf"
        self.fox_geometries: dict[str, tuple[str, object]] = {}
        self.creek_geometries: dict[str, tuple[str, object]] = {}
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
        connection.execute("INSERT INTO dataset VALUES (1, 'water-fox-river', 1)")
        connection.execute("INSERT INTO dataset VALUES (2, 'water-creeks', 1)")
        connection.execute(
            "INSERT INTO source_release VALUES (1, 1, 'fox-test', 'accepted', ?, 1)",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO source_release VALUES (2, 2, 'creeks-test', 'accepted', ?, ?)",
            ("b" * 64, self.CREEK_COUNT),
        )

        outer = [
            [-88.30, 41.72],
            [-88.2998, 41.76],
            [-88.3001, 41.80],
            [-88.2997, 41.84],
            [-88.3002, 41.88],
            [-88.2998, 41.92],
            [-88.3000, 41.96],
            [-88.2900, 41.96],
            [-88.2902, 41.92],
            [-88.2898, 41.88],
            [-88.2901, 41.84],
            [-88.2897, 41.80],
            [-88.2902, 41.76],
            [-88.2900, 41.72],
            [-88.30, 41.72],
        ]
        hole = [
            [-88.297, 41.82],
            [-88.295, 41.82],
            [-88.295, 41.84],
            [-88.297, 41.84],
            [-88.297, 41.82],
        ]
        fox_type = "Polygon"
        fox_coordinates = [outer, hole]
        blob, wkb, bounds = GEOMETRY.encode_geopackage_geometry(
            fox_type, fox_coordinates
        )
        self.fox_geometries["1"] = (fox_type, fox_coordinates)
        connection.execute(
            "INSERT INTO source_map_feature VALUES (1, 1, '1', 1, ?, ?, ?, ?, ?, ?, ?)",
            (blob, fox_type, sha256(wkb), *bounds),
        )

        for index in range(self.CREEK_COUNT):
            source_id = str(index + 1)
            col = index % 30
            row = index // 30
            x = -88.59 + col * 0.010
            y = 41.73 + row * 0.035
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
            self.creek_geometries[source_id] = (geometry_type, coordinates)
            connection.execute(
                "INSERT INTO source_map_feature VALUES (?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    1000 + index,
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
        return WATER_LOD.write_container(self.database, self.output)

    def read(self):
        return WATER_LOD.read_container_bytes(self.output.read_bytes())

    def records_by_dataset(self, records, dataset_key):
        return [record for record in records if record["dataset_key"] == dataset_key]

    def test_build_is_byte_deterministic_without_sidecars(self) -> None:
        first = self.build()
        first_bytes = self.output.read_bytes()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["sha256"], sha256(first_bytes))
        self.assertFalse((self.root / "water-lod.krf.sha256").exists())

    def test_fox_river_is_present_in_every_level_and_creeks_are_progressive(self) -> None:
        self.build()
        index, levels = self.read()
        overview_fox = self.records_by_dataset(levels["overview"], "water-fox-river")
        overview_creeks = self.records_by_dataset(levels["overview"], "water-creeks")
        context_creeks = self.records_by_dataset(levels["context"], "water-creeks")
        detail_creeks = self.records_by_dataset(levels["detail"], "water-creeks")
        self.assertEqual(1, len(overview_fox))
        self.assertEqual([], overview_creeks)
        self.assertGreater(len(context_creeks), 0)
        self.assertLess(len(context_creeks), self.CREEK_COUNT)
        self.assertEqual(self.CREEK_COUNT, len(detail_creeks))
        for key in ("overview", "context", "detail"):
            self.assertEqual(
                1,
                len(self.records_by_dataset(levels[key], "water-fox-river")),
            )
        by_level = {item["key"]: item for item in index["levels"]}
        self.assertEqual(0, by_level["overview"]["creek_feature_count"])
        self.assertEqual(self.CREEK_COUNT, by_level["detail"]["creek_feature_count"])

    def test_creek_membership_is_monotonic(self) -> None:
        self.build()
        _index, levels = self.read()
        overview = {
            record["source_feature_id"]
            for record in self.records_by_dataset(levels["overview"], "water-creeks")
        }
        context = {
            record["source_feature_id"]
            for record in self.records_by_dataset(levels["context"], "water-creeks")
        }
        detail = {
            record["source_feature_id"]
            for record in self.records_by_dataset(levels["detail"], "water-creeks")
        }
        self.assertTrue(overview.issubset(context))
        self.assertTrue(context.issubset(detail))
        self.assertEqual(self.CREEK_COUNT, len(detail))

    def test_detail_preserves_exact_source_geometry(self) -> None:
        self.build()
        _index, levels = self.read()
        detail = {
            (record["dataset_key"], record["source_feature_id"]): record
            for record in levels["detail"]
        }
        for source_id, (geometry_type, coordinates) in self.fox_geometries.items():
            record = detail[("water-fox-river", source_id)]
            self.assertEqual(geometry_type, record["geometry_type"])
            self.assertEqual(as_json_coordinates(coordinates), record["coordinates"])
        for source_id, (geometry_type, coordinates) in self.creek_geometries.items():
            record = detail[("water-creeks", source_id)]
            self.assertEqual(geometry_type, record["geometry_type"])
            self.assertEqual(as_json_coordinates(coordinates), record["coordinates"])

    def test_simplification_preserves_creek_endpoints_and_polygon_rings(self) -> None:
        self.build()
        index, levels = self.read()
        by_level = {item["key"]: item for item in index["levels"]}
        self.assertLessEqual(
            by_level["overview"]["vertex_count"],
            by_level["overview"]["source_vertex_count"],
        )
        self.assertGreater(by_level["overview"]["simplification_tolerance_degrees"], 0.0)
        for record in self.records_by_dataset(levels["context"], "water-creeks"):
            source_type, source_coordinates = self.creek_geometries[record["source_feature_id"]]
            source_lines = WATER_LOD.geometry_lines(source_type, source_coordinates)
            output_lines = WATER_LOD.geometry_lines(record["geometry_type"], record["coordinates"])
            self.assertEqual(len(source_lines), len(output_lines))
            for source_line, output_line in zip(source_lines, output_lines):
                self.assertEqual(list(source_line[0]), list(output_line[0]))
                self.assertEqual(list(source_line[-1]), list(output_line[-1]))
        fox = self.records_by_dataset(levels["overview"], "water-fox-river")[0]
        source_polygons = WATER_LOD.geometry_polygons(*self.fox_geometries["1"])
        output_polygons = WATER_LOD.geometry_polygons(fox["geometry_type"], fox["coordinates"])
        self.assertEqual(len(source_polygons), len(output_polygons))
        for source_polygon, output_polygon in zip(source_polygons, output_polygons):
            self.assertEqual(len(source_polygon), len(output_polygon))
            for ring in output_polygon:
                self.assertEqual(ring[0], ring[-1])
                self.assertGreaterEqual(len(set(ring[:-1])), 3)

    def test_chunks_keep_whole_features_and_unique_composite_identity(self) -> None:
        self.build()
        index, levels = self.read()
        detail_index = next(level for level in index["levels"] if level["key"] == "detail")
        self.assertEqual(2, len(detail_index["chunks"]))
        self.assertEqual(256, detail_index["chunks"][0]["feature_count"])
        self.assertEqual(45, detail_index["chunks"][1]["feature_count"])
        identities = [
            (record["dataset_key"], record["source_feature_id"])
            for record in levels["detail"]
        ]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(self.CREEK_COUNT + 1, len(identities))

    def test_tampered_payload_is_rejected(self) -> None:
        self.build()
        data = bytearray(self.output.read_bytes())
        data[-1] ^= 0x01
        with self.assertRaisesRegex(RuntimeError, "payload SHA-256|compression"):
            WATER_LOD.read_container_bytes(bytes(data))

    def test_rejects_ambiguous_water_release_and_count_hash_mismatch(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "INSERT INTO source_release VALUES (3, 2, 'other-creeks', 'accepted', ?, 0)",
            ("c" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "water-creeks release count is 2"):
            WATER_LOD.build_container(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM source_release WHERE source_release_id = 3")
        connection.execute(
            "UPDATE source_release SET feature_count = feature_count - 1 WHERE source_release_id = 2"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "stored feature count"):
            WATER_LOD.build_container(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute(
            "UPDATE source_release SET feature_count = ? WHERE source_release_id = 2",
            (self.CREEK_COUNT,),
        )
        connection.execute(
            "UPDATE source_map_feature SET geometry_sha256 = ? WHERE source_map_feature_id = 1",
            ("0" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "geometry SHA-256"):
            WATER_LOD.build_container(self.database)

    def test_contract_excludes_unavailable_semantics_and_obsolete_grid_state(self) -> None:
        self.build()
        index, _levels = self.read()
        text = json.dumps(index, sort_keys=True).lower()
        self.assertEqual("kane-condo-water-lod", index["format"])
        self.assertEqual(1, index["version"])
        self.assertEqual(4326, index["srs_id"])
        self.assertEqual(
            "all-accepted-features-in-every-level",
            index["selection"]["fox_river_rule"],
        )
        self.assertEqual(
            "deterministic-coordinate-length-score",
            index["selection"]["creek_basis"],
        )
        for forbidden in (
            "void",
            "sector",
            "inspection_cell",
            "created_at",
            "timestamp",
            "stream_order",
            "hydrologic_class",
        ):
            self.assertNotIn(forbidden, text)
        document = FORMAT_DOC.read_text(encoding="utf-8")
        flattened = " ".join(document.split())
        self.assertIn("does not invent creek classes", flattened)
        self.assertIn("Features are never clipped to chunk boundaries", flattened)

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
        self.assertEqual("fox-test", inspected["source_releases"]["fox_river"])
        self.assertEqual("creeks-test", inspected["source_releases"]["creeks"])
        self.assertEqual(self.CREEK_COUNT + 1, inspected["level_feature_counts"]["detail"])


if __name__ == "__main__":
    unittest.main()
