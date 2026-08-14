#!/usr/bin/env python3
"""Regression tests for Batch 030 building levels of detail."""

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
MODULE_PATH = ROOT / "render/tools/kane_building_lod.py"
WRAPPER = ROOT / "render/kane-building-lod.sh"
FORMAT_DOC = ROOT / "render/BUILDING_LOD_FORMAT.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDING_LOD = load_module("_kane_building_lod_test", MODULE_PATH)
GEOMETRY = load_module(
    "_kane_building_lod_geometry_test", ROOT / "database/tools/kane_geometry.py"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def as_json_coordinates(value):
    if isinstance(value, tuple):
        return [as_json_coordinates(item) for item in value]
    if isinstance(value, list):
        return [as_json_coordinates(item) for item in value]
    return value


class BuildingLodTests(unittest.TestCase):
    FEATURE_COUNT = 600

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.output = self.root / "buildings-lod.krf"
        self.source_geometries: dict[str, tuple[str, object]] = {}
        self.building_keys: dict[str, str] = {}
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
            """
        )
        connection.execute(
            "INSERT INTO county VALUES (1, 'kane-county-il', 'Kane County', 'IL', '17089')"
        )
        connection.execute("INSERT INTO dataset VALUES (1, 'buildings', 1)")
        connection.execute(
            "INSERT INTO source_release VALUES (1, 1, 'kane-buildings-test', 'accepted', ?, ?)",
            ("a" * 64, self.FEATURE_COUNT),
        )

        for index in range(self.FEATURE_COUNT):
            source_id = f"FP-{index + 1:06d}"
            col = index % 40
            row = index // 40
            x = -88.60 + col * 0.007
            y = 41.72 + row * 0.018
            width = 0.00025 + index * 0.0000012
            height = 0.00018 + index * 0.0000008
            # Mid-edge vertices make broad-level simplification observable.
            outer = [
                [x, y],
                [x + width / 2, y],
                [x + width, y],
                [x + width, y + height / 2],
                [x + width, y + height],
                [x + width / 2, y + height],
                [x, y + height],
                [x, y + height / 2],
                [x, y],
            ]
            if index % 75 == 0:
                gap = min(width, height) * 0.25
                hole = [
                    [x + gap, y + gap],
                    [x + width - gap, y + gap],
                    [x + width - gap, y + height - gap],
                    [x + gap, y + height - gap],
                    [x + gap, y + gap],
                ]
                geometry_type = "MultiPolygon" if index % 150 == 0 else "Polygon"
                if geometry_type == "MultiPolygon":
                    second_x = x + width * 1.25
                    second = [
                        [second_x, y],
                        [second_x + width * 0.25, y],
                        [second_x + width * 0.25, y + height * 0.25],
                        [second_x, y + height * 0.25],
                        [second_x, y],
                    ]
                    coordinates = [[outer, hole], [second]]
                else:
                    coordinates = [outer, hole]
            else:
                geometry_type = "Polygon"
                coordinates = [outer]
            blob, wkb, bounds = GEOMETRY.encode_geopackage_polygon(
                geometry_type, coordinates
            )
            building_key = "kcb-" + hashlib.sha256(source_id.encode("utf-8")).hexdigest()
            self.source_geometries[source_id] = (geometry_type, coordinates)
            self.building_keys[source_id] = building_key
            source_building_id = index + 1
            project_building_id = index + 1
            connection.execute(
                "INSERT INTO source_building VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_building_id,
                    source_id,
                    index + 1,
                    blob,
                    geometry_type,
                    sha256(wkb),
                    *bounds,
                ),
            )
            connection.execute(
                "INSERT INTO project_building VALUES (?, ?, 'active')",
                (project_building_id, building_key),
            )
            connection.execute(
                "INSERT INTO project_building_source_mapping VALUES (?, ?, ?, 'confirmed')",
                (index + 1, project_building_id, source_building_id),
            )
        connection.commit()
        connection.close()

    def build(self):
        return BUILDING_LOD.write_container(self.database, self.output)

    def read(self):
        return BUILDING_LOD.read_container_bytes(self.output.read_bytes())

    def test_build_is_byte_deterministic_without_sidecars(self) -> None:
        first = self.build()
        first_bytes = self.output.read_bytes()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, self.output.read_bytes())
        self.assertEqual(first["sha256"], sha256(first_bytes))
        self.assertFalse((self.root / "buildings-lod.krf.sha256").exists())

    def test_progressive_membership_and_neighborhood_is_complete(self) -> None:
        self.build()
        index, levels = self.read()
        context = {record["building_key"] for record in levels["context"]}
        neighborhood = {record["building_key"] for record in levels["neighborhood"]}
        editing = {record["building_key"] for record in levels["editing"]}
        self.assertTrue(context)
        self.assertLess(len(context), self.FEATURE_COUNT)
        self.assertEqual(self.FEATURE_COUNT, len(neighborhood))
        self.assertEqual(self.FEATURE_COUNT, len(editing))
        self.assertTrue(context.issubset(neighborhood))
        self.assertEqual(neighborhood, editing)
        self.assertEqual(self.FEATURE_COUNT, index["source"]["feature_count"])

    def test_context_selects_larger_footprints_before_smaller_ones(self) -> None:
        source, features = BUILDING_LOD.load_accepted_buildings(self.database)
        self.assertEqual(self.FEATURE_COUNT, source["feature_count"])
        selected = BUILDING_LOD.selected_features_by_fraction(features, 0.35)
        selected_keys = {feature["building_key"] for feature in selected}
        omitted = [feature for feature in features if feature["building_key"] not in selected_keys]
        self.assertTrue(omitted)
        self.assertGreaterEqual(
            min(int(feature["area_score"]) for feature in selected),
            max(int(feature["area_score"]) for feature in omitted),
        )

    def test_editing_preserves_exact_source_geometry_and_project_identity(self) -> None:
        self.build()
        index, levels = self.read()
        self.assertEqual("building_key", index["identity"]["field"])
        detail = {record["source_feature_id"]: record for record in levels["editing"]}
        for source_id, (geometry_type, coordinates) in self.source_geometries.items():
            record = detail[source_id]
            self.assertEqual(self.building_keys[source_id], record["building_key"])
            self.assertEqual(geometry_type, record["geometry_type"])
            self.assertEqual(as_json_coordinates(coordinates), record["coordinates"])

    def test_simplification_preserves_closed_rings_and_reduces_vertices(self) -> None:
        self.build()
        index, levels = self.read()
        by_level = {level["key"]: level for level in index["levels"]}
        self.assertLess(
            by_level["context"]["vertex_count"],
            by_level["context"]["source_vertex_count"],
        )
        self.assertLess(
            by_level["neighborhood"]["vertex_count"],
            by_level["neighborhood"]["source_vertex_count"],
        )
        for key in ("context", "neighborhood"):
            for record in levels[key][:50]:
                for polygon in BUILDING_LOD.geometry_polygons(
                    record["geometry_type"], record["coordinates"]
                ):
                    for ring in polygon:
                        self.assertEqual(ring[0], ring[-1])
                        self.assertGreaterEqual(len(set(ring[:-1])), 3)

    def test_chunks_keep_whole_buildings_and_unique_project_identity(self) -> None:
        self.build()
        index, levels = self.read()
        editing_index = next(level for level in index["levels"] if level["key"] == "editing")
        self.assertEqual(2, len(editing_index["chunks"]))
        self.assertEqual(512, editing_index["chunks"][0]["feature_count"])
        self.assertEqual(88, editing_index["chunks"][1]["feature_count"])
        identities = [record["building_key"] for record in levels["editing"]]
        self.assertEqual(len(identities), len(set(identities)))

    def test_rejects_missing_or_ambiguous_project_mapping(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute(
            "DELETE FROM project_building_source_mapping WHERE source_building_id = 1"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "0 confirmed project mappings"):
            BUILDING_LOD.build_container(self.database)

        self._create_database_fresh_after_delete()
        connection = sqlite3.connect(self.database)
        extra_key = "kcb-" + "f" * 64
        connection.execute("INSERT INTO project_building VALUES (9999, ?, 'active')", (extra_key,))
        connection.execute(
            "INSERT INTO project_building_source_mapping VALUES (9999, 9999, 1, 'confirmed')"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "2 confirmed project mappings"):
            BUILDING_LOD.build_container(self.database)

    def _create_database_fresh_after_delete(self) -> None:
        self.database.unlink()
        self.source_geometries.clear()
        self.building_keys.clear()
        self._create_database()

    def test_rejects_release_count_and_geometry_hash_mismatch(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE source_release SET feature_count = feature_count - 1")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "stored feature count"):
            BUILDING_LOD.build_container(self.database)

        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE source_release SET feature_count = ?", (self.FEATURE_COUNT,))
        connection.execute(
            "UPDATE source_building SET geometry_sha256 = ? WHERE source_building_id = 1",
            ("0" * 64,),
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "geometry SHA-256"):
            BUILDING_LOD.build_container(self.database)

    def test_tampered_payload_is_rejected(self) -> None:
        self.build()
        data = bytearray(self.output.read_bytes())
        data[-1] ^= 0x01
        with self.assertRaisesRegex(RuntimeError, "payload SHA-256|compression"):
            BUILDING_LOD.read_container_bytes(bytes(data))

    def test_contract_and_shell_exclude_classification_and_obsolete_grid_state(self) -> None:
        self.build()
        index, _levels = self.read()
        text = json.dumps(index, sort_keys=True).lower()
        self.assertEqual("kane-condo-building-lod", index["format"])
        self.assertEqual(1, index["version"])
        self.assertEqual(4326, index["srs_id"])
        self.assertEqual(
            "deterministic-footprint-coordinate-area-score", index["selection"]["basis"]
        )
        for forbidden in (
            "classification",
            "condominium",
            "apartments",
            "void",
            "sector",
            "inspection_cell",
            "created_at",
            "timestamp",
        ):
            self.assertNotIn(forbidden, text)
        doc = FORMAT_DOC.read_text(encoding="utf-8").lower()
        self.assertIn("building_key", doc)
        self.assertIn("exact accepted source geometry", doc)
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertTrue(wrapper.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", wrapper)
        result = subprocess.run(
            ["bash", str(WRAPPER), "build", str(self.database), str(self.output)],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(result.stdout)
        self.assertEqual(str(self.output.resolve()), summary["output_file"])


if __name__ == "__main__":
    unittest.main()
