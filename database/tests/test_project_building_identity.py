"""Tests for Kane Condo project-owned building identities."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import shutil
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


kane_db = load_module("kane_db_batch013", DATABASE_DIR / "tools" / "kane_db.py")
provenance = load_module(
    "kane_provenance_batch013", DATABASE_DIR / "tools" / "kane_provenance.py"
)
buildings = load_module(
    "kane_buildings_batch013", DATABASE_DIR / "tools" / "kane_buildings.py"
)
project = load_module(
    "kane_project_buildings_batch013",
    DATABASE_DIR / "tools" / "kane_project_buildings.py",
)


class ProjectBuildingIdentityTests(unittest.TestCase):
    BASE_RELEASE = "kane-buildings-20250730-project-example"

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_tempdir = tempfile.TemporaryDirectory()
        fixture_root = Path(cls.fixture_tempdir.name)
        cls.empty_template = fixture_root / "empty.gpkg"
        cls.accepted_template = fixture_root / "accepted.gpkg"
        cls.seeded_template = fixture_root / "seeded.gpkg"
        kane_db.initialize_database(cls.empty_template)
        shutil.copy2(cls.empty_template, cls.accepted_template)
        features = [cls.polygon_feature("B-1"), cls.polygon_feature("B-2", 0.02)]
        raw = json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        geojson = fixture_root / "accepted.geojson"
        geojson.write_bytes(raw)
        descriptor = cls.descriptor(cls.BASE_RELEASE, raw, 2, "accepted")
        descriptor_path = fixture_root / "accepted.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        provenance.record_descriptor(cls.accepted_template, descriptor_path)
        buildings.import_buildings(cls.accepted_template, cls.BASE_RELEASE, geojson)
        shutil.copy2(cls.accepted_template, cls.seeded_template)
        project.seed_project_buildings(cls.seeded_template, cls.BASE_RELEASE)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_tempdir.cleanup()

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.database = self.root / "project-buildings.gpkg"
        shutil.copy2(self.empty_template, self.database)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def use_template(self, template: Path) -> None:
        shutil.copy2(template, self.database)

    @staticmethod
    def polygon_feature(feature_id: str, offset: float = 0.0) -> dict[str, object]:
        west = -88.50 + offset
        east = west + 0.01
        south = 41.90 + offset
        north = south + 0.01
        return {
            "type": "Feature",
            "properties": {"FPId": feature_id, "CommonName": f"Building {feature_id}"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south], [east, south], [east, north],
                    [west, north], [west, south],
                ]],
            },
        }

    def write_geojson(
        self, release_key: str, feature_ids: list[str]
    ) -> tuple[Path, bytes]:
        document = {
            "type": "FeatureCollection",
            "features": [
                self.polygon_feature(feature_id, index * 0.02)
                for index, feature_id in enumerate(feature_ids)
            ],
        }
        raw = json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        path = self.root / f"{release_key}.geojson"
        path.write_bytes(raw)
        return path, raw

    @staticmethod
    def descriptor(
        release_key: str,
        raw: bytes,
        feature_count: int,
        lifecycle_status: str,
    ) -> dict[str, object]:
        digest = hashlib.sha256(raw).hexdigest()
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
                "dataset_key": "buildings",
                "name": "Kane County Building Footprints",
                "description": "Synthetic project-identity fixture",
                "data_kind": "buildings",
                "source_uri": "https://example.invalid/buildings/FeatureServer/0",
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": "FPId"},
                "object_count": feature_count,
            },
            "files": [{
                "file_role": "source",
                "relative_path": f"buildings/{release_key}.geojson",
                "byte_length": len(raw),
                "sha256": digest,
                "media_type": "application/geo+json",
            }],
            "release": {
                "release_key": release_key,
                "lifecycle_status": lifecycle_status,
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": digest,
                "feature_count": feature_count,
                "metadata": {"id_property": "FPId"},
                "accepted_at": (
                    "2025-07-30T13:00:00.000Z"
                    if lifecycle_status == "accepted" else None
                ),
            },
        }

    def prepare_release(
        self,
        release_key: str = "kane-buildings-20250730-project-example",
        feature_ids: list[str] | None = None,
        lifecycle_status: str = "accepted",
        import_features: bool = True,
    ) -> tuple[str, Path]:
        ids = feature_ids or ["B-1", "B-2"]
        path, raw = self.write_geojson(release_key, ids)
        descriptor = self.descriptor(release_key, raw, len(ids), lifecycle_status)
        descriptor_path = self.root / f"{release_key}.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        provenance.record_descriptor(self.database, descriptor_path)
        if import_features:
            buildings.import_buildings(self.database, release_key, path)
        return release_key, path

    def seed(self, feature_ids: list[str] | None = None) -> str:
        if feature_ids is None or feature_ids == ["B-1", "B-2"]:
            self.use_template(self.seeded_template)
            return self.BASE_RELEASE
        release_key, _ = self.prepare_release(feature_ids=feature_ids)
        project.seed_project_buildings(self.database, release_key)
        return release_key

    def test_schema_registration_and_migration_exist(self) -> None:
        self.assertEqual([], project.validate_foundation(self.database))
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                project.PROJECT_COLUMNS,
                project.table_columns(connection, project.PROJECT_TABLE),
            )
            self.assertEqual(
                project.MAPPING_COLUMNS,
                project.table_columns(connection, project.MAPPING_TABLE),
            )
            rows = connection.execute(
                "SELECT table_name, data_type, identifier, srs_id FROM gpkg_contents "
                "WHERE table_name IN (?, ?) ORDER BY table_name",
                (project.PROJECT_TABLE, project.MAPPING_TABLE),
            ).fetchall()
            self.assertEqual(
                [
                    ("project_building", "attributes", "Kane Condo project buildings", None),
                    (
                        "project_building_source_mapping",
                        "attributes",
                        "Kane Condo building mappings",
                        None,
                    ),
                ],
                rows,
            )
            self.assertEqual(
                8, connection.execute("SELECT COUNT(*) FROM schema_migration").fetchone()[0]
            )
        finally:
            connection.close()

    def test_project_key_is_deterministic_and_source_specific(self) -> None:
        first = project.project_building_key("release-a", "B-1")
        self.assertEqual(first, project.project_building_key("release-a", "B-1"))
        self.assertNotEqual(first, project.project_building_key("release-a", "B-2"))
        self.assertNotEqual(first, project.project_building_key("release-b", "B-1"))
        self.assertRegex(first, project.BUILDING_KEY_PATTERN)

    def test_seed_creates_deterministic_one_to_one_mappings(self) -> None:
        release_key = self.seed(["B-2", "B-1", "B-3"])
        connection = sqlite3.connect(self.database)
        try:
            rows = connection.execute(
                "SELECT pb.building_key, sb.source_feature_id, m.relationship_type, "
                "m.decision_method, m.mapping_status "
                "FROM project_building pb "
                "JOIN project_building_source_mapping m "
                "ON m.project_building_id = pb.project_building_id "
                "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
                "ORDER BY sb.source_ordinal"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(["B-2", "B-1", "B-3"], [row[1] for row in rows])
        for building_key, source_id, relationship, method, status in rows:
            self.assertEqual(
                project.project_building_key(release_key, source_id), building_key
            )
            self.assertEqual(("initial", "deterministic-seed", "confirmed"),
                             (relationship, method, status))
        self.assertEqual([], project.validate_database(self.database))

    def test_same_release_produces_same_keys_in_another_database(self) -> None:
        self.use_template(self.accepted_template)
        release_key = self.BASE_RELEASE
        project.seed_project_buildings(self.database, release_key)
        connection = sqlite3.connect(self.database)
        try:
            first = connection.execute(
                "SELECT building_key FROM project_building ORDER BY building_key"
            ).fetchall()
        finally:
            connection.close()
        second_database = self.root / "second.gpkg"
        original_database = self.database
        self.database = second_database
        shutil.copy2(self.accepted_template, self.database)
        try:
            project.seed_project_buildings(self.database, release_key)
            connection = sqlite3.connect(self.database)
            try:
                second = connection.execute(
                    "SELECT building_key FROM project_building ORDER BY building_key"
                ).fetchall()
            finally:
                connection.close()
        finally:
            self.database = original_database
        self.assertEqual(first, second)

    def test_seed_requires_accepted_release(self) -> None:
        release_key, _ = self.prepare_release(lifecycle_status="candidate")
        with self.assertRaisesRegex(RuntimeError, "requires an accepted building release"):
            project.seed_project_buildings(self.database, release_key)

    def test_seed_requires_completely_stored_release(self) -> None:
        release_key, _ = self.prepare_release(import_features=False)
        with self.assertRaisesRegex(RuntimeError, "failed validation before"):
            project.seed_project_buildings(self.database, release_key)

    def test_duplicate_seed_is_rejected_without_extra_rows(self) -> None:
        release_key = self.seed(["B-1", "B-2"])
        with self.assertRaisesRegex(RuntimeError, "already initialized"):
            project.seed_project_buildings(self.database, release_key)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(2, connection.execute(
                "SELECT COUNT(*) FROM project_building"
            ).fetchone()[0])
            self.assertEqual(2, connection.execute(
                "SELECT COUNT(*) FROM project_building_source_mapping"
            ).fetchone()[0])
        finally:
            connection.close()

    def test_origin_source_can_create_only_one_project_identity(self) -> None:
        self.seed(["B-1"])
        connection = sqlite3.connect(self.database)
        try:
            origin = connection.execute(
                "SELECT created_from_source_building_id FROM project_building"
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO project_building (building_key, lifecycle_status, "
                    "created_from_source_building_id, identity_algorithm, created_at) "
                    "VALUES (?, 'active', ?, ?, ?)",
                    ("kcb-" + "a" * 64, origin, project.IDENTITY_ALGORITHM,
                     "2025-07-30T13:01:00.000Z"),
                )
        finally:
            connection.close()

    def test_deterministic_key_tampering_is_detected(self) -> None:
        self.seed(["B-1"])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE project_building SET building_key = ?", ("kcb-" + "0" * 64,)
            )
            connection.commit()
        finally:
            connection.close()
        errors = project.validate_database(self.database)
        self.assertTrue(any("invalid deterministic key" in error for error in errors))

    def test_missing_initial_mapping_is_detected(self) -> None:
        self.seed(["B-1"])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("DELETE FROM project_building_source_mapping")
            connection.commit()
        finally:
            connection.close()
        errors = project.validate_database(self.database)
        self.assertTrue(any("exactly one confirmed initial mapping" in error for error in errors))

    def test_accepted_release_mapping_gap_is_detected(self) -> None:
        self.seed(["B-1", "B-2"])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE project_building_source_mapping SET mapping_status = 'rejected' "
                "WHERE mapping_id = (SELECT MAX(mapping_id) FROM project_building_source_mapping)"
            )
            connection.commit()
        finally:
            connection.close()
        errors = project.validate_database(self.database)
        self.assertTrue(any("maps 1 of 2" in error for error in errors))

    def test_schema_allows_future_split_and_merge_relationships(self) -> None:
        self.seed(["B-1", "B-2"])
        candidate_key, _ = self.prepare_release(
            "kane-buildings-20260805-candidate",
            ["C-1", "C-2"],
            lifecycle_status="candidate",
        )
        self.assertEqual("kane-buildings-20260805-candidate", candidate_key)
        connection = sqlite3.connect(self.database)
        try:
            projects = [row[0] for row in connection.execute(
                "SELECT project_building_id FROM project_building ORDER BY project_building_id"
            )]
            sources = [row[0] for row in connection.execute(
                "SELECT sb.source_building_id FROM source_building sb "
                "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
                "WHERE sr.release_key = ? ORDER BY sb.source_ordinal", (candidate_key,)
            )]
            now = "2026-08-05T18:00:00.000Z"
            connection.executemany(
                "INSERT INTO project_building_source_mapping (project_building_id, "
                "source_building_id, relationship_type, decision_method, mapping_status, "
                "created_at) VALUES (?, ?, ?, 'automatic', 'proposed', ?)",
                [
                    (projects[0], sources[0], "split", now),
                    (projects[0], sources[1], "split", now),
                    (projects[1], sources[0], "merge", now),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual([], project.validate_database(self.database))

    def test_info_reports_counts_without_geometry_payloads(self) -> None:
        release_key = self.seed(["B-1", "B-2"])
        info = project.project_identity_info(self.database, release_key)
        self.assertTrue(info["valid"])
        self.assertEqual(2, info["project_buildings"]["count"])
        self.assertEqual(2, info["mappings"]["count"])
        self.assertEqual(2, info["release"]["confirmed_mapped_source_count"])
        self.assertNotIn("geometry", json.dumps(info))

    def test_cli_seed_info_and_validate(self) -> None:
        self.use_template(self.accepted_template)
        release_key = self.BASE_RELEASE
        seeded = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-project-buildings.sh"), "seed",
             str(self.database), release_key],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        self.assertTrue(json.loads(seeded.stdout)["valid"])
        info = project.project_identity_info(self.database, release_key)
        self.assertEqual(2, info["project_buildings"]["count"])
        self.assertEqual([], project.validate_database(self.database))


if __name__ == "__main__":
    unittest.main()
