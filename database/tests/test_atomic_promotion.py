#!/usr/bin/env python3
"""Tests for Batch 024 atomic database promotion and rollback."""

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
from typing import Any

DATABASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = DATABASE_DIR / "tools"
TESTS_DIR = DATABASE_DIR / "tests"
ROOT = DATABASE_DIR.parent
MODULE_PATH = TOOLS_DIR / "kane_promotion.py"
WRAPPER = DATABASE_DIR / "kane-promotion.sh"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROMOTION = load_module(MODULE_PATH, "_kane_promotion_test")
BUILDING_TEST = load_module(TESTS_DIR / "test_building_candidate.py", "_b024_building_test")
ROAD_TEST = load_module(TESTS_DIR / "test_road_candidate.py", "_b024_road_test")
WATER_TEST = load_module(TESTS_DIR / "test_water_candidate.py", "_b024_water_test")
BOUNDARY_TEST = load_module(TESTS_DIR / "test_boundary_candidate.py", "_b024_boundary_test")


class AtomicPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane-condo.gpkg"
        self.staging = self.root / "staging"
        self.output = self.root / "output"
        self.backups = self.root / "backups"
        self.building_fake = BUILDING_TEST.FakeArcGIS()
        self.road_fake = ROAD_TEST.FakeRoadArcGIS()
        self.water_fake = WATER_TEST.FakeWaterArcGIS()
        self.boundary_fake = BOUNDARY_TEST.FakeBoundaryArcGIS()
        self.build_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def descriptor(
        self,
        *,
        dataset_key: str,
        data_kind: str,
        source_uri: str,
        release_key: str,
        source: Path,
        object_count: int,
        id_property: str,
        published_at: str,
    ) -> Path:
        raw = source.read_bytes()
        value = {
            "county": {
                "county_key": "kane-county-il",
                "name": "Kane County",
                "state_code": "IL",
                "country_code": "US",
                "fips_code": "17089",
            },
            "agency": {
                "agency_key": "kane-county-gis",
                "name": "Kane County GIS",
                "jurisdiction": "Kane County, Illinois",
                "homepage_uri": None,
            },
            "dataset": {
                "dataset_key": dataset_key,
                "name": f"Fixture {dataset_key}",
                "description": "Atomic promotion fixture",
                "data_kind": data_kind,
                "source_uri": source_uri,
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-17T12:00:00.000Z",
                "completed_at": "2025-07-17T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {
                    "id_property": id_property,
                    "object_id_field": "OBJECTID",
                },
                "object_count": object_count,
            },
            "files": [{
                "file_role": "source",
                "relative_path": f"accepted/{source.name}",
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "media_type": "application/geo+json",
            }],
            "release": {
                "release_key": release_key,
                "lifecycle_status": "accepted",
                "source_published_at": published_at,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "feature_count": object_count,
                "metadata": {"id_property": id_property},
                "accepted_at": "2025-07-17T13:00:00.000Z",
            },
        }
        path = self.root / f"{release_key}.json"
        path.write_bytes(PROMOTION.canonical_bytes(value))
        return path

    def write_geojson(self, name: str, features: list[dict[str, Any]]) -> Path:
        path = self.root / name
        path.write_bytes(PROMOTION.canonical_bytes({"type": "FeatureCollection", "features": features}))
        return path

    def build_fixture(self) -> None:
        PROMOTION.kane_db.initialize_database(self.database)

        boundary_profile, _ = PROMOTION.kane_boundary_candidate.load_boundary_profile()
        self.boundary_fake.object_ids = [7]
        boundary_source = self.write_geojson("accepted-boundary.geojson", [self.boundary_fake.feature(7)])
        boundary_key = "boundary-accepted-b024"
        PROMOTION.kane_provenance.record_descriptor(
            self.database,
            self.descriptor(
                dataset_key="county-boundary", data_kind="boundary",
                source_uri=boundary_profile["source"]["layer_url"],
                release_key=boundary_key, source=boundary_source, object_count=1,
                id_property="OBJECTID", published_at="2023-05-09T21:08:30.769Z",
            ),
        )
        PROMOTION.kane_boundary.import_boundary(self.database, boundary_key, boundary_source)

        road_profile, _ = PROMOTION.kane_road_candidate.load_road_profile()
        road_source = self.write_geojson("accepted-roads.geojson", [self.road_fake.feature(1)])
        road_key = "roads-accepted-b024"
        PROMOTION.kane_provenance.record_descriptor(
            self.database,
            self.descriptor(
                dataset_key="roads", data_kind="roads",
                source_uri=road_profile["source"]["layer_url"],
                release_key=road_key, source=road_source, object_count=1,
                id_property="OBJECTID", published_at="2025-07-30T14:27:48.846Z",
            ),
        )
        PROMOTION.kane_map_layers.import_map_layers(self.database, [(road_key, road_source)])

        water_profiles, _ = PROMOTION.kane_water_candidate.load_water_profiles()
        water_imports: list[tuple[str, Path]] = []
        for dataset_key in PROMOTION.kane_water_candidate.DATASET_ORDER:
            slug = "creeks" if dataset_key == "water-creeks" else "fox-river"
            source = self.write_geojson(
                f"accepted-{slug}.geojson",
                [self.water_fake.feature(dataset_key, 1)],
            )
            release_key = f"{slug}-accepted-b024"
            PROMOTION.kane_provenance.record_descriptor(
                self.database,
                self.descriptor(
                    dataset_key=dataset_key, data_kind="water",
                    source_uri=water_profiles[dataset_key]["source"]["layer_url"],
                    release_key=release_key, source=source, object_count=1,
                    id_property="OBJECTID", published_at="2025-07-17T21:45:28.127Z",
                ),
            )
            water_imports.append((release_key, source))
        PROMOTION.kane_map_layers.import_map_layers(self.database, water_imports)

        building_profile, _ = PROMOTION.kane_reconcile.kane_candidate.load_building_profile()
        self.building_fake.object_ids = [1]
        building_source = self.write_geojson("accepted-buildings.geojson", [self.building_fake.feature(1)])
        building_key = "buildings-accepted-b024"
        PROMOTION.kane_provenance.record_descriptor(
            self.database,
            self.descriptor(
                dataset_key="buildings", data_kind="buildings",
                source_uri=building_profile["source"]["layer_url"],
                release_key=building_key, source=building_source, object_count=1,
                id_property="FPId", published_at="2025-07-30T15:34:54.870Z",
            ),
        )
        PROMOTION.kane_buildings.import_buildings(self.database, building_key, building_source)
        PROMOTION.kane_project.seed_project_buildings(self.database, building_key)

        # Harvest and register candidate building, then reconcile it.
        building_result = PROMOTION.kane_reconcile.kane_candidate.harvest_candidate(
            self.staging,
            requester=self.building_fake,
            started_at="2026-08-11T16:00:00.000Z",
            completed_at="2026-08-11T16:01:00.000Z",
        )
        self.building_dir = Path(building_result["candidate_directory"])
        PROMOTION.kane_reconcile.kane_candidate.register_candidate(self.database, self.building_dir)

        self.road_fake.object_ids = [2, 1]
        road_result = PROMOTION.kane_road_candidate.harvest_candidate(
            self.staging,
            requester=self.road_fake,
            started_at="2026-08-11T16:02:00.000Z",
            completed_at="2026-08-11T16:03:00.000Z",
        )
        self.road_dir = Path(road_result["candidate_directory"])
        PROMOTION.kane_road_candidate.register_candidate(self.database, self.road_dir)

        self.water_fake.object_ids = {"water-creeks": [1], "water-fox-river": [1]}
        water_result = PROMOTION.kane_water_candidate.harvest_candidate(
            self.staging,
            requester=self.water_fake,
            started_at="2026-08-11T16:04:00.000Z",
            completed_at="2026-08-11T16:05:00.000Z",
        )
        self.water_dir = Path(water_result["candidate_directory"])
        PROMOTION.kane_water_candidate.register_candidate(self.database, self.water_dir)

        self.boundary_fake.bounds = [-88.61, 41.71, -88.22, 42.16]
        boundary_result = PROMOTION.kane_boundary_candidate.harvest_candidate(
            self.staging,
            self.database,
            requester=self.boundary_fake,
            started_at="2026-08-11T16:06:00.000Z",
            completed_at="2026-08-11T16:07:00.000Z",
        )
        self.boundary_dir = Path(boundary_result["candidate_directory"])
        PROMOTION.kane_boundary_candidate.register_candidate(self.database, self.boundary_dir)

        reconciliation = PROMOTION.kane_reconcile.prepare_reconciliation(
            self.database, self.building_dir, self.staging
        )
        self.reconciliation_dir = Path(reconciliation["reconciliation_directory"])

        self.accepted_sha = PROMOTION.sha256_file(self.database)
        self.accepted_keys = PROMOTION._accepted_release_keys(self.database)


    def strip_promotion_migration(self, database: Path) -> None:
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                "DROP TRIGGER IF EXISTS tr_refresh_promotion_event_no_update;"
                "DROP TRIGGER IF EXISTS tr_refresh_promotion_event_no_delete;"
                "DROP TABLE IF EXISTS refresh_promotion_event;"
                "DELETE FROM gpkg_contents WHERE table_name = 'refresh_promotion_event';"
                "DELETE FROM schema_migration WHERE migration_id = 8;"
            )
            connection.commit()
        finally:
            connection.close()

    def rewrite_reconciliation_identity(self) -> None:
        candidate = self.reconciliation_dir / PROMOTION.kane_reconcile.DATABASE_FILENAME
        report_path = self.reconciliation_dir / PROMOTION.kane_reconcile.REPORT_FILENAME
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["accepted_database_sha256"] = PROMOTION.sha256_file(self.database)
        report["candidate_database"] = {
            "filename": PROMOTION.kane_reconcile.DATABASE_FILENAME,
            "byte_length": candidate.stat().st_size,
            "sha256": PROMOTION.sha256_file(candidate),
        }
        body = {key: value for key, value in report.items() if key != "reconciliation_sha256"}
        report["reconciliation_sha256"] = PROMOTION.kane_reconcile.sha256_value(body)
        report_path.write_bytes(PROMOTION.kane_reconcile.canonical_bytes(report) + b"\n")

    def prepare(self) -> dict[str, Any]:
        return PROMOTION.prepare_promotion(
            self.database,
            self.reconciliation_dir,
            self.road_dir,
            self.water_dir,
            self.boundary_dir,
            self.output,
        )

    def test_migration_adds_append_only_promotion_history(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            self.assertIn("refresh_promotion_event", tables)
            triggers = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )}
            self.assertIn("tr_refresh_promotion_event_no_update", triggers)
            self.assertIn("tr_refresh_promotion_event_no_delete", triggers)
        finally:
            connection.close()

    def test_prepare_builds_valid_fully_promoted_candidate(self) -> None:
        result = self.prepare()
        self.assertTrue(result["valid"])
        directory = Path(result["promotion_directory"])
        promoted = directory / PROMOTION.DATABASE_FILENAME
        info = PROMOTION.validate_promotion(directory)
        self.assertEqual(result["promoted_database_sha256"], info["promoted_database_sha256"])
        self.assertEqual(5, len(info["release_transitions"]))
        self.assertNotEqual(self.accepted_sha, PROMOTION.sha256_file(promoted))
        self.assertEqual([], PROMOTION.kane_classifications.validate_database(promoted))

    def test_prepare_is_idempotent(self) -> None:
        first = self.prepare()
        second = self.prepare()
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(first["promotion_key"], second["promotion_key"])
        self.assertEqual(first["promoted_database_sha256"], second["promoted_database_sha256"])

    def test_prepare_does_not_mutate_accepted_database(self) -> None:
        self.prepare()
        self.assertEqual(self.accepted_sha, PROMOTION.sha256_file(self.database))
        self.assertEqual(self.accepted_keys, PROMOTION._accepted_release_keys(self.database))

    def test_promote_atomically_activates_all_five_candidates(self) -> None:
        prepared = self.prepare()
        result = PROMOTION.promote_database(
            self.database, Path(prepared["promotion_directory"]), self.backups
        )
        self.assertTrue(result["promoted"])
        self.assertFalse(result["existing"])
        self.assertEqual(prepared["promoted_database_sha256"], PROMOTION.sha256_file(self.database))
        self.assertEqual(
            {key: value["candidate_release_key"] for key, value in prepared["release_transitions"].items()},
            PROMOTION._accepted_release_keys(self.database),
        )
        self.assertTrue(Path(result["backup_database"]).is_file())
        self.assertEqual(self.accepted_sha, result["backup_database_sha256"])

    def test_promote_is_idempotent_after_success(self) -> None:
        prepared = self.prepare()
        directory = Path(prepared["promotion_directory"])
        first = PROMOTION.promote_database(self.database, directory, self.backups)
        second = PROMOTION.promote_database(self.database, directory, self.backups)
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])

    def test_promotion_refuses_changed_authoritative_database(self) -> None:
        prepared = self.prepare()
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE gpkg_contents SET last_change = ? WHERE table_name = 'building_classification_current'",
                (PROMOTION.kane_db.utc_now(),),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "changed after promotion preparation"):
            PROMOTION.promote_database(
                self.database, Path(prepared["promotion_directory"]), self.backups
            )

    def test_failed_post_verification_automatically_restores_previous_releases(self) -> None:
        prepared = self.prepare()
        previous = dict(self.accepted_keys)

        def fail(_database: Path, _manifest: Any) -> None:
            raise RuntimeError("synthetic post verification failure")

        with self.assertRaisesRegex(RuntimeError, "prior accepted state was restored"):
            PROMOTION.promote_database(
                self.database,
                Path(prepared["promotion_directory"]),
                self.backups,
                post_verify=fail,
            )
        self.assertEqual(previous, PROMOTION._accepted_release_keys(self.database))
        self.assertEqual([], PROMOTION.kane_classifications.validate_database(self.database))
        history = PROMOTION.database_promotion_info(self.database)
        self.assertEqual(["promotion", "rollback"], [row["event_kind"] for row in history["promotion_events"]])

    def test_manual_rollback_restores_previous_release_set(self) -> None:
        prepared = self.prepare()
        directory = Path(prepared["promotion_directory"])
        PROMOTION.promote_database(self.database, directory, self.backups)
        promoted_sha = PROMOTION.sha256_file(self.database)
        result = PROMOTION.rollback_database(
            self.database, directory, self.backups, "operator acceptance rollback"
        )
        self.assertTrue(result["rolled_back"])
        self.assertEqual(self.accepted_keys, PROMOTION._accepted_release_keys(self.database))
        self.assertNotEqual(promoted_sha, PROMOTION.sha256_file(self.database))
        history = PROMOTION.database_promotion_info(self.database)
        self.assertEqual(["promotion", "rollback"], [row["event_kind"] for row in history["promotion_events"]])

    def test_history_rows_cannot_be_updated_or_deleted(self) -> None:
        prepared = self.prepare()
        PROMOTION.promote_database(
            self.database, Path(prepared["promotion_directory"]), self.backups
        )
        connection = sqlite3.connect(self.database)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("UPDATE refresh_promotion_event SET authorization_kind = 'x'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM refresh_promotion_event")
        finally:
            connection.close()

    def test_tampered_promotion_database_is_rejected(self) -> None:
        prepared = self.prepare()
        directory = Path(prepared["promotion_directory"])
        database = directory / PROMOTION.DATABASE_FILENAME
        with database.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(RuntimeError, "byte length|SHA-256"):
            PROMOTION.validate_promotion(directory)

    def test_unknown_artifact_file_is_rejected(self) -> None:
        prepared = self.prepare()
        directory = Path(prepared["promotion_directory"])
        (directory / "extra.txt").write_text("no", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "file set mismatch"):
            PROMOTION.validate_promotion(directory)

    def test_prepare_accepts_batch023_artifacts_one_migration_behind(self) -> None:
        candidate = self.reconciliation_dir / PROMOTION.kane_reconcile.DATABASE_FILENAME
        self.strip_promotion_migration(self.database)
        self.strip_promotion_migration(candidate)
        self.rewrite_reconciliation_identity()
        result = self.prepare()
        self.assertTrue(result["valid"])
        self.assertEqual(8, len(PROMOTION.kane_db.database_info(
            Path(result["promotion_directory"]) / PROMOTION.DATABASE_FILENAME
        )["migrations"]))

    def test_manual_rollback_refuses_new_classification_after_promotion(self) -> None:
        prepared = self.prepare()
        directory = Path(prepared["promotion_directory"])
        PROMOTION.promote_database(self.database, directory, self.backups)
        connection = sqlite3.connect(self.database)
        try:
            building_key = connection.execute(
                "SELECT building_key FROM project_building ORDER BY project_building_id LIMIT 1"
            ).fetchone()[0]
        finally:
            connection.close()
        PROMOTION.kane_classifications.set_classification(
            self.database, str(building_key), "other", "b024-after-promotion"
        )
        with self.assertRaisesRegex(RuntimeError, "classifications changed after promotion"):
            PROMOTION.rollback_database(
                self.database, directory, self.backups, "unsafe stale rollback"
            )

    def test_migrate_command_applies_pending_promotion_migration(self) -> None:
        legacy = self.root / "legacy.gpkg"
        PROMOTION._copy_file(self.database, legacy)
        self.strip_promotion_migration(legacy)
        PROMOTION.kane_db.migrate_database(legacy)
        info = PROMOTION.kane_db.database_info(legacy)
        self.assertTrue(info["valid"])
        self.assertEqual(8, len(info["migrations"]))

    def test_wrapper_help_is_available(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("rollback", completed.stdout)
        self.assertIn("promote", completed.stdout)


if __name__ == "__main__":
    unittest.main()
