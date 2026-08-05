"""Tests for immutable Kane Condo roads and water storage."""

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


kane_db = load_module("kane_db_batch011", DATABASE_DIR / "tools" / "kane_db.py")
provenance = load_module(
    "kane_provenance_batch011", DATABASE_DIR / "tools" / "kane_provenance.py"
)
map_layers = load_module(
    "kane_map_layers_batch011", DATABASE_DIR / "tools" / "kane_map_layers.py"
)
geometry = load_module(
    "kane_geometry_batch011", DATABASE_DIR / "tools" / "kane_geometry.py"
)


class RoadsWaterStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = self.root / "map-layers.gpkg"
        kane_db.initialize_database(self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def line_feature(object_id: int, *, vertical: bool = False) -> dict[str, object]:
        coordinates = (
            [[-88.40, 41.80], [-88.40, 41.95], [-88.40, 42.05]]
            if vertical
            else [[-88.60, 41.80], [-88.40, 41.90], [-88.20, 42.00]]
        )
        return {
            "type": "Feature",
            "properties": {"OBJECTID": object_id, "NAME": f"Road {object_id}"},
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }

    @staticmethod
    def multiline_feature(object_id: int) -> dict[str, object]:
        return {
            "type": "Feature",
            "properties": {"OBJECTID": object_id, "NAME": f"Creek {object_id}"},
            "geometry": {
                "type": "MultiLineString",
                "coordinates": [
                    [[-88.55, 41.75], [-88.45, 41.85]],
                    [[-88.45, 41.85], [-88.30, 41.92]],
                ],
            },
        }

    @staticmethod
    def polygon_feature(object_id: int, *, multipolygon: bool = False) -> dict[str, object]:
        outer = [
            [-88.50, 41.75],
            [-88.30, 41.75],
            [-88.30, 42.05],
            [-88.50, 42.05],
            [-88.50, 41.75],
        ]
        hole = [
            [-88.44, 41.84],
            [-88.40, 41.84],
            [-88.40, 41.88],
            [-88.44, 41.88],
            [-88.44, 41.84],
        ]
        geometry_value: dict[str, object]
        if multipolygon:
            geometry_value = {"type": "MultiPolygon", "coordinates": [[outer, hole]]}
        else:
            geometry_value = {"type": "Polygon", "coordinates": [outer, hole]}
        return {
            "type": "Feature",
            "properties": {"OBJECTID": object_id, "NAME": "Fox River"},
            "geometry": geometry_value,
        }

    def write_geojson(self, name: str, features: list[dict[str, object]]) -> tuple[Path, bytes]:
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
        dataset_key: str,
        data_kind: str,
        release_key: str,
        feature_count: int,
        source_hash: str | None = None,
        object_count: int | None = None,
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
                "name": dataset_key.replace("-", " ").title(),
                "description": "Synthetic roads or water fixture",
                "data_kind": data_kind,
                "source_uri": f"https://example.invalid/{dataset_key}/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": "OBJECTID"},
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
                "metadata": {"id_property": "OBJECTID"},
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
        return descriptor["release"]["release_key"]

    def prepare(
        self,
        *,
        dataset_key: str,
        data_kind: str,
        release_key: str,
        features: list[dict[str, object]],
        source_hash: str | None = None,
        feature_count: int | None = None,
    ) -> tuple[str, Path]:
        path, raw = self.write_geojson(f"{dataset_key}.geojson", features)
        count = len(features) if feature_count is None else feature_count
        descriptor = self.descriptor(
            raw,
            dataset_key=dataset_key,
            data_kind=data_kind,
            release_key=release_key,
            feature_count=count,
            source_hash=source_hash,
        )
        return self.record(descriptor), path

    def prepare_three_layers(self) -> list[tuple[str, Path]]:
        roads = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-20250730-example",
            features=[self.line_feature(1), self.line_feature(2, vertical=True)],
        )
        river = self.prepare(
            dataset_key="water-fox-river",
            data_kind="water",
            release_key="kane-water-fox-river-20250717-example",
            features=[self.polygon_feature(10, multipolygon=True)],
        )
        creeks = self.prepare(
            dataset_key="water-creeks",
            data_kind="water",
            release_key="kane-water-creeks-20250717-example",
            features=[self.multiline_feature(20)],
        )
        return [roads, river, creeks]

    def test_schema_and_geopackage_registration_exist(self) -> None:
        self.assertEqual([], map_layers.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                map_layers.MAP_COLUMNS,
                map_layers.table_columns(connection, map_layers.MAP_TABLE),
            )
            self.assertEqual(
                ("features", "Kane County roads and water", 4326),
                connection.execute(
                    "SELECT data_type, identifier, srs_id FROM gpkg_contents "
                    "WHERE table_name = 'source_map_feature'"
                ).fetchone(),
            )
            self.assertEqual(
                ("geometry", "GEOMETRY", 4326, 0, 0),
                connection.execute(
                    "SELECT column_name, geometry_type_name, srs_id, z, m "
                    "FROM gpkg_geometry_columns WHERE table_name = 'source_map_feature'"
                ).fetchone(),
            )
            self.assertEqual(
                4, connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
            )
        finally:
            connection.close()

    def test_atomic_import_preserves_all_geometry_types_and_lineage(self) -> None:
        sources = self.prepare_three_layers()
        result = map_layers.import_map_layers(self.database, sources)["layers"]
        self.assertEqual({"roads", "water-fox-river", "water-creeks"}, set(result))
        self.assertEqual(2, result["roads"]["features"]["stored_count"])
        self.assertEqual(["LineString"], result["roads"]["features"]["geometry_types"])
        self.assertEqual(
            ["MultiPolygon"], result["water-fox-river"]["features"]["geometry_types"]
        )
        self.assertEqual(
            ["MultiLineString"], result["water-creeks"]["features"]["geometry_types"]
        )
        self.assertEqual([], map_layers.validate_database(self.database))
        connection = sqlite3.connect(self.database)
        try:
            rows = connection.execute(
                "SELECT geometry, geometry_type, geometry_sha256 FROM source_map_feature "
                "ORDER BY source_map_feature_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(4, len(rows))
        for blob, geometry_type, geometry_hash in rows:
            decoded = geometry.decode_geopackage_geometry(blob)
            self.assertEqual(geometry_type, decoded.geometry_type)
            self.assertEqual(geometry_hash, hashlib.sha256(decoded.wkb).hexdigest())
        river = geometry.decode_geopackage_geometry(rows[2][0])
        self.assertEqual(2, len(river.coordinates[0]))

    def test_vertical_line_is_valid_and_retains_zero_width_bounds(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-vertical-example",
            features=[self.line_feature(1, vertical=True)],
        )
        info = map_layers.import_map_layers(self.database, [(release_key, path)])["layers"]
        bounds = info["roads"]["features"]["bounds"]
        self.assertEqual(bounds[0], bounds[2])
        self.assertLess(bounds[1], bounds[3])

    def test_polygon_is_rejected_for_roads(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-polygon-example",
            features=[self.polygon_feature(1)],
        )
        with self.assertRaisesRegex(RuntimeError, "expected LineString or MultiLineString"):
            map_layers.import_map_layers(self.database, [(release_key, path)])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0])
        finally:
            connection.close()

    def test_feature_count_is_enforced(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-count-example",
            features=[self.line_feature(1)],
            feature_count=2,
        )
        with self.assertRaisesRegex(RuntimeError, "contains 1 features; expected 2"):
            map_layers.import_map_layers(self.database, [(release_key, path)])

    def test_duplicate_source_identity_is_rejected(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-duplicate-example",
            features=[self.line_feature(1), self.line_feature(1, vertical=True)],
        )
        with self.assertRaisesRegex(RuntimeError, "Duplicate map-layer source feature id"):
            map_layers.import_map_layers(self.database, [(release_key, path)])

    def test_source_evidence_mismatch_is_rejected(self) -> None:
        release_key, path = self.prepare(
            dataset_key="water-creeks",
            data_kind="water",
            release_key="kane-water-creeks-hash-example",
            features=[self.multiline_feature(1)],
            source_hash="0" * 64,
        )
        with self.assertRaisesRegex(RuntimeError, "preserved source-file evidence"):
            map_layers.import_map_layers(self.database, [(release_key, path)])

    def test_multi_release_import_is_atomic_on_failure(self) -> None:
        roads = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-atomic-example",
            features=[self.line_feature(1)],
        )
        bad_water = self.prepare(
            dataset_key="water-creeks",
            data_kind="water",
            release_key="kane-water-creeks-atomic-example",
            features=[self.line_feature(2)],
            source_hash="0" * 64,
        )
        with self.assertRaisesRegex(RuntimeError, "preserved source-file evidence"):
            map_layers.import_map_layers(self.database, [roads, bad_water])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0])
        finally:
            connection.close()

    def test_accepted_release_without_features_is_detected(self) -> None:
        self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-missing-example",
            features=[self.line_feature(1)],
        )
        errors = map_layers.validate_database(self.database)
        self.assertTrue(any("has no stored features" in error for error in errors))

    def test_duplicate_import_is_rejected_without_extra_rows(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-repeat-example",
            features=[self.line_feature(1)],
        )
        map_layers.import_map_layers(self.database, [(release_key, path)])
        with self.assertRaisesRegex(RuntimeError, "already stored"):
            map_layers.import_map_layers(self.database, [(release_key, path)])
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0])
        finally:
            connection.close()

    def test_geometry_hash_tampering_is_detected(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-tamper-example",
            features=[self.line_feature(1)],
        )
        map_layers.import_map_layers(self.database, [(release_key, path)])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_map_feature SET geometry_sha256 = ?", ("0" * 64,)
            )
            connection.commit()
        finally:
            connection.close()
        errors = map_layers.validate_database(self.database)
        self.assertTrue(any("geometry SHA-256" in error for error in errors))

    def test_noncontiguous_ordinal_is_detected(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-ordinal-example",
            features=[self.line_feature(1), self.line_feature(2)],
        )
        map_layers.import_map_layers(self.database, [(release_key, path)])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_map_feature SET source_ordinal = 5 WHERE source_ordinal = 2"
            )
            connection.commit()
        finally:
            connection.close()
        errors = map_layers.validate_database(self.database)
        self.assertTrue(any("ordinals are not contiguous" in error for error in errors))

    def test_info_reports_all_accepted_layers_without_feature_payloads(self) -> None:
        map_layers.import_map_layers(self.database, self.prepare_three_layers())
        info = map_layers.map_layers_info(self.database)["layers"]
        self.assertEqual({"roads", "water-fox-river", "water-creeks"}, set(info))
        for layer in info.values():
            self.assertNotIn("geometry", layer["features"])
            self.assertEqual(
                layer["release"]["feature_count"], layer["features"]["stored_count"]
            )

    def test_cli_import_info_and_validate(self) -> None:
        release_key, path = self.prepare(
            dataset_key="roads",
            data_kind="roads",
            release_key="kane-roads-cli-example",
            features=[self.line_feature(1), self.line_feature(2, vertical=True)],
        )
        imported = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-map-layers.sh"),
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
                str(DATABASE_DIR / "kane-map-layers.sh"),
                "info",
                str(self.database),
                release_key,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            release_key,
            json.loads(info.stdout)["roads_and_water"]["layers"]["roads"]["release"]["release_key"],
        )
        validated = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-map-layers.sh"),
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
