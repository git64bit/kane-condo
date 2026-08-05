"""Tests for immutable Kane Condo official building-release storage."""

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


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


kane_db = load_module("kane_db_batch012", DATABASE_DIR / "tools" / "kane_db.py")
provenance = load_module(
    "kane_provenance_batch012", DATABASE_DIR / "tools" / "kane_provenance.py"
)
buildings = load_module(
    "kane_buildings_batch012", DATABASE_DIR / "tools" / "kane_buildings.py"
)
geometry = load_module(
    "kane_geometry_batch012", DATABASE_DIR / "tools" / "kane_geometry.py"
)


class OfficialBuildingStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = self.root / "buildings.gpkg"
        kane_db.initialize_database(self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def polygon_feature(feature_id: str, *, offset: float = 0.0) -> dict[str, object]:
        west = -88.50 + offset
        east = -88.49 + offset
        south = 41.90 + offset
        north = 41.91 + offset
        return {
            "type": "Feature",
            "properties": {
                "FPId": feature_id,
                "CommonName": f"Building {feature_id}",
                "YearBuilt": 1990,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]],
            },
        }

    @staticmethod
    def multipolygon_feature(feature_id: str) -> dict[str, object]:
        outer = [
            [-88.40, 41.80],
            [-88.37, 41.80],
            [-88.37, 41.84],
            [-88.40, 41.84],
            [-88.40, 41.80],
        ]
        hole = [
            [-88.395, 41.81],
            [-88.385, 41.81],
            [-88.385, 41.82],
            [-88.395, 41.82],
            [-88.395, 41.81],
        ]
        second = [
            [-88.36, 41.80],
            [-88.35, 41.80],
            [-88.35, 41.81],
            [-88.36, 41.81],
            [-88.36, 41.80],
        ]
        return {
            "type": "Feature",
            "properties": {"FPId": feature_id, "CommonName": "Building complex"},
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[outer, hole], [second]],
            },
        }

    @staticmethod
    def line_feature(feature_id: str) -> dict[str, object]:
        return {
            "type": "Feature",
            "properties": {"FPId": feature_id},
            "geometry": {
                "type": "LineString",
                "coordinates": [[-88.50, 41.90], [-88.40, 42.00]],
            },
        }

    def write_geojson(
        self, name: str, features: list[dict[str, object]]
    ) -> tuple[Path, bytes]:
        path = self.root / name
        document = {"type": "FeatureCollection", "features": features}
        raw = json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        path.write_bytes(raw)
        return path, raw

    def descriptor(
        self,
        raw: bytes,
        *,
        release_key: str,
        feature_count: int,
        dataset_key: str = "buildings",
        data_kind: str = "buildings",
        source_hash: str | None = None,
        object_count: int | None = None,
        id_property: str = "FPId",
        lifecycle_status: str = "accepted",
    ) -> dict[str, object]:
        digest = hashlib.sha256(raw).hexdigest() if source_hash is None else source_hash
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
                "dataset_key": dataset_key,
                "name": "Kane County Building Footprints",
                "description": "Synthetic official-building fixture",
                "data_kind": data_kind,
                "source_uri": "https://example.invalid/buildings/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": id_property},
                "object_count": feature_count if object_count is None else object_count,
            },
            "files": [
                {
                    "file_role": "source",
                    "relative_path": f"{dataset_key}/{dataset_key}.geojson",
                    "byte_length": len(raw),
                    "sha256": digest,
                    "media_type": "application/geo+json",
                }
            ],
            "release": {
                "release_key": release_key,
                "lifecycle_status": lifecycle_status,
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": digest,
                "feature_count": feature_count,
                "metadata": {"id_property": id_property},
                "accepted_at": (
                    "2025-07-30T13:00:00.000Z"
                    if lifecycle_status == "accepted"
                    else None
                ),
            },
        }

    def record(self, descriptor: dict[str, object]) -> str:
        path = self.root / f"{descriptor['release']['release_key']}.json"
        path.write_text(json.dumps(descriptor), encoding="utf-8")
        provenance.record_descriptor(self.database, path)
        return str(descriptor["release"]["release_key"])

    def prepare(
        self,
        *,
        release_key: str = "kane-buildings-20250730-example",
        features: list[dict[str, object]] | None = None,
        dataset_key: str = "buildings",
        data_kind: str = "buildings",
        source_hash: str | None = None,
        feature_count: int | None = None,
        id_property: str = "FPId",
        lifecycle_status: str = "accepted",
    ) -> tuple[str, Path]:
        actual_features = features or [self.polygon_feature("B-1")]
        path, raw = self.write_geojson(f"{release_key}.geojson", actual_features)
        count = len(actual_features) if feature_count is None else feature_count
        descriptor = self.descriptor(
            raw,
            release_key=release_key,
            feature_count=count,
            dataset_key=dataset_key,
            data_kind=data_kind,
            source_hash=source_hash,
            id_property=id_property,
            lifecycle_status=lifecycle_status,
        )
        return self.record(descriptor), path

    def test_schema_and_geopackage_registration_exist(self) -> None:
        self.assertEqual([], buildings.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                buildings.BUILDING_COLUMNS,
                buildings.table_columns(connection, buildings.BUILDING_TABLE),
            )
            self.assertEqual(
                ("features", "Kane County official buildings", 4326),
                connection.execute(
                    "SELECT data_type, identifier, srs_id FROM gpkg_contents "
                    "WHERE table_name = 'source_building'"
                ).fetchone(),
            )
            self.assertEqual(
                ("geometry", "GEOMETRY", 4326, 0, 0),
                connection.execute(
                    "SELECT column_name, geometry_type_name, srs_id, z, m "
                    "FROM gpkg_geometry_columns WHERE table_name = 'source_building'"
                ).fetchone(),
            )
            self.assertEqual(
                6, connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
            )
        finally:
            connection.close()

    def test_import_preserves_polygon_multipolygon_hole_attributes_and_lineage(self) -> None:
        release_key, path = self.prepare(
            features=[self.polygon_feature("B-1"), self.multipolygon_feature("B-2")]
        )
        result = buildings.import_buildings(self.database, release_key, path)
        self.assertEqual(2, result["features"]["stored_count"])
        self.assertEqual(
            ["MultiPolygon", "Polygon"], result["features"]["geometry_types"]
        )
        self.assertEqual([], buildings.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            rows = connection.execute(
                "SELECT source_feature_id, source_ordinal, geometry, geometry_type, "
                "geometry_sha256, attributes_json FROM source_building "
                "ORDER BY source_ordinal"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(["B-1", "B-2"], [row[0] for row in rows])
        self.assertEqual([1, 2], [row[1] for row in rows])
        for row in rows:
            decoded = geometry.decode_geopackage_polygon(row[2])
            self.assertEqual(row[3], decoded.geometry_type)
            self.assertEqual(row[4], hashlib.sha256(decoded.wkb).hexdigest())
            self.assertEqual(row[0], str(json.loads(row[5])["FPId"]))
        multipolygon = geometry.decode_geopackage_polygon(rows[1][2])
        self.assertEqual(2, len(multipolygon.coordinates))
        self.assertEqual(2, len(multipolygon.coordinates[0]))

    def test_non_building_release_is_rejected(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-building-import-example",
        )
        with self.assertRaisesRegex(RuntimeError, "not a building dataset"):
            buildings.import_buildings(self.database, release_key, path)

    def test_linear_geometry_is_rejected(self) -> None:
        release_key, path = self.prepare(features=[self.line_feature("B-1")])
        with self.assertRaisesRegex(RuntimeError, "Unsupported polygon geometry type"):
            buildings.import_buildings(self.database, release_key, path)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                0, connection.execute("SELECT COUNT(*) FROM source_building").fetchone()[0]
            )
        finally:
            connection.close()

    def test_feature_count_is_enforced(self) -> None:
        release_key, path = self.prepare(feature_count=2)
        with self.assertRaisesRegex(RuntimeError, "contains 1 features; expected 2"):
            buildings.import_buildings(self.database, release_key, path)

    def test_duplicate_source_identity_is_rejected(self) -> None:
        release_key, path = self.prepare(
            features=[self.polygon_feature("B-1"), self.polygon_feature("B-1", offset=0.02)]
        )
        with self.assertRaisesRegex(RuntimeError, "Duplicate building source feature id"):
            buildings.import_buildings(self.database, release_key, path)

    def test_missing_source_identity_is_rejected(self) -> None:
        feature = self.polygon_feature("B-1")
        feature["properties"].pop("FPId")
        release_key, path = self.prepare(features=[feature])
        with self.assertRaisesRegex(RuntimeError, "missing source identity property 'FPId'"):
            buildings.import_buildings(self.database, release_key, path)

    def test_source_evidence_mismatch_is_rejected(self) -> None:
        release_key, path = self.prepare(source_hash="0" * 64)
        with self.assertRaisesRegex(RuntimeError, "preserved source-file evidence"):
            buildings.import_buildings(self.database, release_key, path)

    def test_accepted_release_without_features_is_detected(self) -> None:
        self.prepare()
        errors = buildings.validate_database(self.database)
        self.assertTrue(any("has no stored features" in error for error in errors))

    def test_candidate_release_may_exist_without_stored_features(self) -> None:
        self.prepare(lifecycle_status="candidate")
        self.assertEqual([], buildings.validate_database(self.database))

    def test_duplicate_import_is_rejected_without_extra_rows(self) -> None:
        release_key, path = self.prepare()
        buildings.import_buildings(self.database, release_key, path)
        with self.assertRaisesRegex(RuntimeError, "already stored"):
            buildings.import_buildings(self.database, release_key, path)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                1, connection.execute("SELECT COUNT(*) FROM source_building").fetchone()[0]
            )
        finally:
            connection.close()

    def test_geometry_hash_tampering_is_detected(self) -> None:
        release_key, path = self.prepare()
        buildings.import_buildings(self.database, release_key, path)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_building SET geometry_sha256 = ?", ("0" * 64,)
            )
            connection.commit()
        finally:
            connection.close()
        errors = buildings.validate_database(self.database)
        self.assertTrue(any("geometry SHA-256" in error for error in errors))

    def test_source_identity_attribute_mismatch_is_detected(self) -> None:
        release_key, path = self.prepare()
        buildings.import_buildings(self.database, release_key, path)
        attributes_json = buildings.canonical_json(
            {"FPId": "B-X", "CommonName": "Building B-1", "YearBuilt": 1990}
        )
        attributes_hash = hashlib.sha256(attributes_json.encode("utf-8")).hexdigest()
        connection = sqlite3.connect(self.database)
        try:
            geometry_hash, source_feature_id = connection.execute(
                "SELECT geometry_sha256, source_feature_id FROM source_building"
            ).fetchone()
            content_hash = hashlib.sha256(
                buildings.canonical_json(
                    {
                        "source_feature_id": source_feature_id,
                        "geometry_sha256": geometry_hash,
                        "attributes_sha256": attributes_hash,
                    }
                ).encode("utf-8")
            ).hexdigest()
            connection.execute(
                "UPDATE source_building SET attributes_json = ?, attributes_sha256 = ?, "
                "content_sha256 = ?",
                (attributes_json, attributes_hash, content_hash),
            )
            connection.commit()
        finally:
            connection.close()
        errors = buildings.validate_database(self.database)
        self.assertTrue(any("source identity does not match" in error for error in errors))

    def test_noncontiguous_ordinal_is_detected(self) -> None:
        release_key, path = self.prepare(
            features=[self.polygon_feature("B-1"), self.polygon_feature("B-2", offset=0.02)]
        )
        buildings.import_buildings(self.database, release_key, path)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_building SET source_ordinal = 5 WHERE source_ordinal = 2"
            )
            connection.commit()
        finally:
            connection.close()
        errors = buildings.validate_database(self.database)
        self.assertTrue(any("ordinals are not contiguous" in error for error in errors))

    def test_info_omits_geometry_payloads(self) -> None:
        release_key, path = self.prepare(
            features=[self.polygon_feature("B-1"), self.multipolygon_feature("B-2")]
        )
        buildings.import_buildings(self.database, release_key, path)
        info = buildings.building_info(self.database)
        self.assertEqual(release_key, info["release"]["release_key"])
        self.assertEqual(2, info["features"]["stored_count"])
        self.assertNotIn("geometry", info["features"])

    def test_cli_import_info_and_validate(self) -> None:
        release_key, path = self.prepare(
            release_key="kane-buildings-cli-example",
            features=[self.polygon_feature("B-1"), self.multipolygon_feature("B-2")],
        )
        imported = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-buildings.sh"),
                "import",
                str(self.database),
                release_key,
                str(path),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(json.loads(imported.stdout)["valid"])
        info = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-buildings.sh"),
                "info",
                str(self.database),
                release_key,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(info.stdout)["official_buildings"]
        self.assertEqual(release_key, payload["release"]["release_key"])
        validated = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-buildings.sh"),
                "validate",
                str(self.database),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual([], json.loads(validated.stdout)["errors"])


if __name__ == "__main__":
    unittest.main()
