"""Tests for immutable Kane Condo county-boundary storage."""

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


kane_db = load_module("kane_db_batch010", DATABASE_DIR / "tools" / "kane_db.py")
provenance = load_module(
    "kane_provenance_batch010", DATABASE_DIR / "tools" / "kane_provenance.py"
)
boundary = load_module("kane_boundary_batch010", DATABASE_DIR / "tools" / "kane_boundary.py")
geometry = load_module("kane_geometry_batch010", DATABASE_DIR / "tools" / "kane_geometry.py")


class CountyBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = self.root / "boundary.gpkg"
        self.geojson = self.root / "kane-boundary.geojson"
        self.descriptor_path = self.root / "boundary-release.json"
        kane_db.initialize_database(self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def feature(self, *, east: float = -88.22, multipolygon: bool = False) -> dict[str, object]:
        outer = [
            [-88.61, 41.71],
            [east, 41.71],
            [east, 42.16],
            [-88.61, 42.16],
            [-88.61, 41.71],
        ]
        hole = [
            [-88.50, 41.80],
            [-88.45, 41.80],
            [-88.45, 41.85],
            [-88.50, 41.85],
            [-88.50, 41.80],
        ]
        geometry_value: dict[str, object]
        if multipolygon:
            geometry_value = {"type": "MultiPolygon", "coordinates": [[outer, hole]]}
        else:
            geometry_value = {"type": "Polygon", "coordinates": [outer]}
        return {
            "type": "Feature",
            "properties": {"OBJECTID": 7, "NAME": "Kane County"},
            "geometry": geometry_value,
        }

    def write_geojson(self, features: list[dict[str, object]] | None = None) -> bytes:
        document = {
            "type": "FeatureCollection",
            "features": features if features is not None else [self.feature()],
        }
        raw = json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        self.geojson.write_bytes(raw)
        return raw

    def descriptor(
        self,
        raw: bytes,
        *,
        release_key: str = "kane-county-boundary-20230509-example",
        data_kind: str = "boundary",
        lifecycle_status: str = "accepted",
        feature_count: int = 1,
        source_hash: str | None = None,
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
                "dataset_key": "county-boundary",
                "name": "Kane County Boundary",
                "description": "Official county boundary geometry",
                "data_kind": data_kind,
                "source_uri": "https://example.invalid/arcgis/rest/services/boundary/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": "OBJECTID"},
                "object_count": feature_count,
            },
            "files": [
                {
                    "file_role": "source",
                    "relative_path": "boundary/kane-boundary.geojson",
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
                "metadata": {"id_property": "OBJECTID"},
                "accepted_at": (
                    "2025-07-30T13:00:00.000Z"
                    if lifecycle_status == "accepted"
                    else None
                ),
            },
        }

    def record_release(self, descriptor: dict[str, object]) -> None:
        self.descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        provenance.record_descriptor(self.database, self.descriptor_path)

    def prepare_release(self, **descriptor_options) -> str:
        raw = self.write_geojson()
        descriptor = self.descriptor(raw, **descriptor_options)
        self.record_release(descriptor)
        return descriptor["release"]["release_key"]

    def test_schema_and_geopackage_registration_exist(self) -> None:
        self.assertEqual([], boundary.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(boundary.BOUNDARY_COLUMNS, boundary.table_columns(connection, boundary.BOUNDARY_TABLE))
            self.assertEqual(
                ("features", "Kane County boundary", 4326),
                connection.execute(
                    "SELECT data_type, identifier, srs_id FROM gpkg_contents "
                    "WHERE table_name = 'source_county_boundary'"
                ).fetchone(),
            )
            self.assertEqual(
                ("geometry", "GEOMETRY", 4326, 0, 0),
                connection.execute(
                    "SELECT column_name, geometry_type_name, srs_id, z, m "
                    "FROM gpkg_geometry_columns WHERE table_name = 'source_county_boundary'"
                ).fetchone(),
            )
        finally:
            connection.close()

    def test_import_preserves_feature_bounds_hashes_and_source_lineage(self) -> None:
        release_key = self.prepare_release()
        result = boundary.import_boundary(self.database, release_key, self.geojson)
        stored = result["boundary"]
        self.assertEqual("7", stored["source_feature_id"])
        self.assertEqual("Polygon", stored["geometry_type"])
        self.assertEqual([-88.61, 41.71, -88.22, 42.16], stored["bounds"])
        self.assertEqual(hashlib.sha256(self.geojson.read_bytes()).hexdigest(), result["source_file"]["sha256"])
        self.assertEqual([], boundary.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            blob = connection.execute("SELECT geometry FROM source_county_boundary").fetchone()[0]
        finally:
            connection.close()
        decoded = geometry.decode_geopackage_polygon(blob)
        self.assertEqual("Polygon", decoded.geometry_type)
        self.assertEqual(tuple(stored["bounds"]), decoded.envelope)
        self.assertEqual(stored["geometry_sha256"], hashlib.sha256(decoded.wkb).hexdigest())

    def test_multipolygon_and_hole_are_preserved(self) -> None:
        raw = self.write_geojson([self.feature(multipolygon=True)])
        descriptor = self.descriptor(raw)
        self.record_release(descriptor)
        boundary.import_boundary(self.database, descriptor["release"]["release_key"], self.geojson)
        connection = sqlite3.connect(self.database)
        try:
            blob, geometry_type = connection.execute(
                "SELECT geometry, geometry_type FROM source_county_boundary"
            ).fetchone()
        finally:
            connection.close()
        decoded = geometry.decode_geopackage_polygon(blob)
        self.assertEqual("MultiPolygon", geometry_type)
        self.assertEqual("MultiPolygon", decoded.geometry_type)
        self.assertEqual(2, len(decoded.coordinates[0]))

    def test_source_evidence_hash_mismatch_is_rejected(self) -> None:
        raw = self.write_geojson()
        self.record_release(self.descriptor(raw, source_hash="0" * 64))
        with self.assertRaisesRegex(RuntimeError, "preserved source-file evidence"):
            boundary.import_boundary(
                self.database, "kane-county-boundary-20230509-example", self.geojson
            )
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM source_county_boundary").fetchone()[0])
        finally:
            connection.close()

    def test_non_boundary_release_is_rejected(self) -> None:
        release_key = self.prepare_release(data_kind="other")
        with self.assertRaisesRegex(RuntimeError, "not a boundary dataset"):
            boundary.import_boundary(self.database, release_key, self.geojson)

    def test_feature_count_and_geojson_count_are_enforced(self) -> None:
        release_key = self.prepare_release(feature_count=2)
        with self.assertRaisesRegex(RuntimeError, "feature_count must be 1"):
            boundary.import_boundary(self.database, release_key, self.geojson)
        self.database.unlink()
        kane_db.initialize_database(self.database)
        raw = self.write_geojson([self.feature(), self.feature(east=-88.20)])
        descriptor = self.descriptor(raw, feature_count=1)
        self.record_release(descriptor)
        with self.assertRaisesRegex(RuntimeError, "contains 2 features; expected 1"):
            boundary.import_boundary(self.database, descriptor["release"]["release_key"], self.geojson)

    def test_unclosed_ring_is_rejected(self) -> None:
        feature = self.feature()
        feature["geometry"]["coordinates"][0].pop()
        raw = self.write_geojson([feature])
        descriptor = self.descriptor(raw)
        self.record_release(descriptor)
        with self.assertRaisesRegex(RuntimeError, "ring is not closed"):
            boundary.import_boundary(self.database, descriptor["release"]["release_key"], self.geojson)

    def test_duplicate_import_is_rejected_without_extra_row(self) -> None:
        release_key = self.prepare_release()
        boundary.import_boundary(self.database, release_key, self.geojson)
        with self.assertRaisesRegex(RuntimeError, "already stored"):
            boundary.import_boundary(self.database, release_key, self.geojson)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM source_county_boundary").fetchone()[0])
        finally:
            connection.close()

    def test_accepted_release_without_feature_is_detected(self) -> None:
        self.prepare_release()
        errors = boundary.validate_database(self.database)
        self.assertTrue(any("has no stored feature" in error for error in errors))

    def test_geometry_hash_tampering_is_detected(self) -> None:
        release_key = self.prepare_release()
        boundary.import_boundary(self.database, release_key, self.geojson)
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_county_boundary SET geometry_sha256 = ?", ("0" * 64,)
            )
            connection.commit()
        finally:
            connection.close()
        errors = boundary.validate_database(self.database)
        self.assertTrue(any("geometry SHA-256" in error for error in errors))

    def test_cli_import_info_and_validate(self) -> None:
        release_key = self.prepare_release()
        imported = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-boundary.sh"),
                "import",
                str(self.database),
                release_key,
                str(self.geojson),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(json.loads(imported.stdout)["valid"])
        info = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-boundary.sh"), "info", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(release_key, json.loads(info.stdout)["county_boundary"]["release"]["release_key"])
        validated = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-boundary.sh"), "validate", str(self.database)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual([], json.loads(validated.stdout)["errors"])


if __name__ == "__main__":
    unittest.main()
