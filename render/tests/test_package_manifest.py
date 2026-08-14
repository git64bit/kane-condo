#!/usr/bin/env python3
"""Regression tests for Batch 032 render-package manifest and integrity."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "render/tools/kane_package_manifest.py"
WRAPPER = ROOT / "render/kane-package-manifest.sh"
FORMAT_DOC = ROOT / "render/PACKAGE_MANIFEST_FORMAT.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MANIFEST = load_module("_kane_package_manifest_test", MODULE_PATH)
ROAD = load_module("_kane_package_manifest_road_test", ROOT / "render/tools/kane_road_lod.py")
WATER = load_module("_kane_package_manifest_water_test", ROOT / "render/tools/kane_water_lod.py")
BUILDING = load_module("_kane_package_manifest_building_test", ROOT / "render/tools/kane_building_lod.py")
SNAPSHOT = load_module(
    "_kane_package_manifest_snapshot_test", ROOT / "render/tools/kane_classification_snapshot.py"
)
OVERVIEW = load_module(
    "_kane_package_manifest_overview_test", ROOT / "render/tools/kane_county_overview.py"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PackageManifestTests(unittest.TestCase):
    CREATED_AT = "2026-08-14T19:55:00Z"
    COUNTY = {
        "county_key": "kane-county-il",
        "fips_code": "17089",
        "name": "Kane County",
        "state_code": "IL",
    }
    RELEASES = {
        "county-boundary": ("boundary-r1", "1" * 64, 1),
        "roads": ("roads-r1", "2" * 64, 2),
        "water-fox-river": ("fox-r1", "3" * 64, 1),
        "water-creeks": ("creeks-r1", "4" * 64, 2),
        "buildings": ("buildings-r1", "5" * 64, 3),
    }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane.gpkg"
        self.package = self.root / "package"
        self.package.mkdir()
        self.manifest = self.package / "render-package-manifest.json"
        self.overview = self.package / "county-overview.json"
        self.roads = self.package / "roads-lod.krf"
        self.water = self.package / "water-lod.krf"
        self.buildings = self.package / "buildings-lod.krf"
        self.classifications = self.package / "classification-snapshot.json"
        self.building_keys = [
            "kcb-" + hashlib.sha256(f"building-{index}".encode()).hexdigest()
            for index in range(3)
        ]
        self._create_database()
        self._create_components()

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
            """
        )
        connection.execute(
            "INSERT INTO county VALUES (1, 'kane-county-il', 'Kane County', 'IL', '17089')"
        )
        for index, dataset_key in enumerate(self.RELEASES, 1):
            release_key, content_sha, feature_count = self.RELEASES[dataset_key]
            connection.execute("INSERT INTO dataset VALUES (?, ?, 1)", (index, dataset_key))
            connection.execute(
                "INSERT INTO source_release VALUES (?, ?, ?, 'accepted', ?, ?)",
                (index, index, release_key, content_sha, feature_count),
            )
        connection.commit()
        connection.close()

    def _release(self, dataset_key: str) -> dict[str, object]:
        release_key, content_sha, feature_count = self.RELEASES[dataset_key]
        return {
            "feature_count": feature_count,
            "release_content_sha256": content_sha,
            "release_key": release_key,
        }

    def _flat_container(self, module, index: dict[str, object], level_records: list[list[dict[str, object]]]) -> bytes:
        payloads: list[bytes] = []
        offset = 0
        levels = []
        for level, records in zip(index["levels"], level_records):
            raw = module.canonical_json_bytes(records)
            compressed = zlib.compress(raw, level=9)
            chunk = {
                "feature_count": len(records),
                "length": len(compressed),
                "offset": offset,
                "payload_sha256": sha256(compressed),
                "records_sha256": sha256(raw),
                "uncompressed_length": len(raw),
            }
            levels.append({**level, "chunks": [chunk], "feature_count": len(records)})
            payloads.append(compressed)
            offset += len(compressed)
        index = {**index, "levels": levels}
        index_bytes = module.canonical_json_bytes(index)
        return module.MAGIC + struct.pack(">Q", len(index_bytes)) + index_bytes + b"".join(payloads)

    def _create_components(self) -> None:
        boundary_release = self._release("county-boundary")
        overview_doc = {
            "county": self.COUNTY,
            "fit": {
                "bounds": [-88.6, 41.7, -88.2, 42.2],
                "center": [-88.4, 41.95],
                "height": 0.5,
                "width": 0.4,
            },
            "format": OVERVIEW.FORMAT,
            "outline": {
                "kind": "exterior-rings",
                "ring_count": 1,
                "rings": [[[-88.6, 41.7], [-88.2, 41.7], [-88.2, 42.2], [-88.6, 41.7]]],
                "simplification_tolerance_degrees": 0.0002,
                "source_interior_ring_count": 0,
                "source_vertex_count": 10,
                "vertex_count": 4,
            },
            "source": {
                "dataset_key": "county-boundary",
                "geometry_sha256": "6" * 64,
                "geometry_type": "Polygon",
                "release_content_sha256": boundary_release["release_content_sha256"],
                "release_key": boundary_release["release_key"],
                "source_feature_id": "1",
            },
            "srs_id": 4326,
            "version": OVERVIEW.VERSION,
        }
        self.overview.write_bytes((OVERVIEW.canonical_json(overview_doc) + "\n").encode())

        road_release = self._release("roads")
        road_index = {
            "chunk_feature_limit": 256,
            "format": ROAD.FORMAT,
            "levels": [
                {"key": "orientation", "rank": 0},
                {"key": "context", "rank": 1},
                {"key": "detail", "rank": 2},
            ],
            "road_bounds": [-88.6, 41.7, -88.2, 42.2],
            "selection": {},
            "source": {
                **road_release,
                "county": self.COUNTY,
                "dataset_key": "roads",
            },
            "srs_id": 4326,
            "version": ROAD.VERSION,
        }
        road_records = [
            [{"source_feature_id": "1"}],
            [{"source_feature_id": "1"}, {"source_feature_id": "2"}],
            [{"source_feature_id": "1"}, {"source_feature_id": "2"}],
        ]
        self.roads.write_bytes(self._flat_container(ROAD, road_index, road_records))

        water_index = {
            "chunk_feature_limit": 256,
            "format": WATER.FORMAT,
            "levels": [
                {"key": "overview", "rank": 0},
                {"key": "context", "rank": 1},
                {"key": "detail", "rank": 2},
            ],
            "selection": {},
            "source": {
                "county": self.COUNTY,
                "datasets": {
                    "fox_river": {
                        **self._release("water-fox-river"),
                        "dataset_key": "water-fox-river",
                    },
                    "creeks": {
                        **self._release("water-creeks"),
                        "dataset_key": "water-creeks",
                    },
                },
            },
            "srs_id": 4326,
            "version": WATER.VERSION,
            "water_bounds": [-88.6, 41.7, -88.2, 42.2],
        }
        water_records = [
            [{"dataset_key": "water-fox-river", "source_feature_id": "1"}],
            [
                {"dataset_key": "water-fox-river", "source_feature_id": "1"},
                {"dataset_key": "water-creeks", "source_feature_id": "1"},
            ],
            [
                {"dataset_key": "water-fox-river", "source_feature_id": "1"},
                {"dataset_key": "water-creeks", "source_feature_id": "1"},
                {"dataset_key": "water-creeks", "source_feature_id": "2"},
            ],
        ]
        self.water.write_bytes(self._flat_container(WATER, water_index, water_records))

        building_release = self._release("buildings")
        building_index = {
            "building_bounds": [-88.6, 41.7, -88.2, 42.2],
            "chunk_feature_limit": 512,
            "format": BUILDING.FORMAT,
            "identity": {"field": "building_key", "kind": "kane-condo-project-building"},
            "levels": [
                {"key": "context", "rank": 0},
                {"key": "neighborhood", "rank": 1},
                {"key": "editing", "rank": 2},
            ],
            "selection": {},
            "source": {
                **building_release,
                "county": self.COUNTY,
                "dataset_key": "buildings",
            },
            "srs_id": 4326,
            "version": BUILDING.VERSION,
        }
        building_records = [
            [{"building_key": self.building_keys[0]}],
            [{"building_key": key} for key in self.building_keys],
            [{"building_key": key} for key in self.building_keys],
        ]
        self.buildings.write_bytes(
            self._flat_container(BUILDING, building_index, building_records)
        )

        sorted_keys = sorted(self.building_keys)
        records = [[sorted_keys[0], "other"]]
        counts = {
            "apartments": 0,
            "condominium": 0,
            "other": 1,
            "unclassified": 2,
        }
        snapshot_doc = {
            "classifications": list(SNAPSHOT.CLASSIFICATIONS),
            "default_classification": "unclassified",
            "explicit": {
                "count": 1,
                "counts": counts,
                "non_rendered_explicit_count": 0,
                "records": records,
                "records_sha256": sha256(SNAPSHOT.canonical_json_bytes(records)),
            },
            "format": SNAPSHOT.FORMAT,
            "identity": {
                "field": "building_key",
                "kind": "kane-condo-project-building",
                "render_building_count": 3,
                "render_identity_sha256": sha256(SNAPSHOT.canonical_json_bytes(sorted_keys)),
            },
            "source": {
                **building_release,
                "dataset_key": "buildings",
            },
            "version": SNAPSHOT.VERSION,
        }
        self.classifications.write_bytes(SNAPSHOT.canonical_json_bytes(snapshot_doc))

    def build(self, *, created_at: str | None = None):
        return MANIFEST.write_manifest(
            self.database,
            self.manifest,
            self.overview,
            self.roads,
            self.water,
            self.buildings,
            self.classifications,
            created_at=created_at,
        )

    def validate(self):
        return MANIFEST.validate_manifest_against_inputs(
            self.database,
            self.manifest,
            self.overview,
            self.roads,
            self.water,
            self.buildings,
            self.classifications,
        )

    def test_build_and_validate_canonical_manifest(self) -> None:
        result = self.build(created_at=self.CREATED_AT)
        document = MANIFEST.read_manifest_bytes(self.manifest.read_bytes())
        self.assertEqual("kane-condo-render-package-manifest", document["format"])
        self.assertEqual(self.CREATED_AT, document["created_at"])
        self.assertEqual(5, len(document["components"]))
        self.assertEqual(result["sha256"], sha256(self.manifest.read_bytes()))
        self.assertEqual("valid", self.validate()["status"])
        text = self.manifest.read_text()
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("coordinates", text)

    def test_creation_time_is_isolated_from_content_identity(self) -> None:
        first = self.build(created_at="2026-08-14T19:55:00Z")
        first_bytes = self.manifest.read_bytes()
        second = self.build(created_at="2026-08-14T19:56:00Z")
        second_bytes = self.manifest.read_bytes()
        self.assertNotEqual(first_bytes, second_bytes)
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(first["package_content_sha256"], second["package_content_sha256"])
        self.assertEqual(first["base_geometry_sha256"], second["base_geometry_sha256"])

    def test_missing_component_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        self.water.unlink()
        with self.assertRaisesRegex(RuntimeError, "Required render component is missing: water"):
            self.validate()

    def test_altered_component_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        data = bytearray(self.roads.read_bytes())
        data[-1] ^= 0x01
        self.roads.write_bytes(bytes(data))
        with self.assertRaisesRegex(RuntimeError, "payload SHA-256|compression|record SHA-256"):
            self.validate()

    def test_swapped_component_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        self.roads.write_bytes(self.water.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "invalid magic header"):
            self.validate()

    def test_release_incompatible_component_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        # Rebuild the road component with a valid structure but another release identity.
        data = self.roads.read_bytes()
        magic = ROAD.MAGIC
        index_length = struct.unpack(">Q", data[len(magic):len(magic)+8])[0]
        start = len(magic) + 8
        end = start + index_length
        index = json.loads(data[start:end].decode())
        index["source"]["release_key"] = "roads-other"
        payload = data[end:]
        index_bytes = ROAD.canonical_json_bytes(index)
        self.roads.write_bytes(magic + struct.pack(">Q", len(index_bytes)) + index_bytes + payload)
        with self.assertRaisesRegex(RuntimeError, "Road LOD release does not match"):
            self.validate()

    def test_classification_building_identity_mismatch_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        document = SNAPSHOT.read_snapshot_bytes(self.classifications.read_bytes())
        document["identity"]["render_identity_sha256"] = "0" * 64
        self.classifications.write_bytes(SNAPSHOT.canonical_json_bytes(document))
        with self.assertRaisesRegex(RuntimeError, "Classification snapshot identity does not match"):
            self.validate()

    def test_database_change_is_rejected_after_manifest_build(self) -> None:
        self.build(created_at=self.CREATED_AT)
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE unrelated_change (value TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "authoritative database identity mismatch"):
            self.validate()

    def test_manifest_tamper_is_rejected(self) -> None:
        self.build(created_at=self.CREATED_AT)
        document = MANIFEST.read_manifest_bytes(self.manifest.read_bytes())
        document["components"][0]["byte_length"] += 1
        self.manifest.write_bytes(MANIFEST.canonical_json_bytes(document))
        with self.assertRaisesRegex(RuntimeError, "component integrity mismatch: county_overview"):
            self.validate()

    def test_shell_entry_point_build_validate_and_contract(self) -> None:
        text = WRAPPER.read_text()
        self.assertTrue(text.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("set -euo pipefail", text)
        build = subprocess.run(
            [
                "bash", str(WRAPPER), "build",
                str(self.database), str(self.overview), str(self.roads), str(self.water),
                str(self.buildings), str(self.classifications), str(self.manifest),
                "--created-at", self.CREATED_AT,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        summary = json.loads(build.stdout)
        self.assertEqual(5, summary["component_count"])
        validate = subprocess.run(
            [
                "bash", str(WRAPPER), "validate",
                str(self.database), str(self.overview), str(self.roads), str(self.water),
                str(self.buildings), str(self.classifications), str(self.manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual("valid", json.loads(validate.stdout)["status"])
        contract = FORMAT_DOC.read_text().lower()
        self.assertIn("package_content_sha256", contract)
        self.assertIn("created_at", contract)
        self.assertNotIn("void mask is approved", contract)


if __name__ == "__main__":
    unittest.main()
