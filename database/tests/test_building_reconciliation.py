#!/usr/bin/env python3
"""Tests for Batch 023 project-identity reconciliation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

DATABASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = DATABASE_DIR / "tools"
MODULE_PATH = TOOLS_DIR / "kane_building_reconcile.py"
WRAPPER = DATABASE_DIR / "kane-building-reconcile.sh"
ROOT = DATABASE_DIR.parent
TESTS_DIR = DATABASE_DIR / "tests"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RECONCILE = load_module(MODULE_PATH, "_kane_building_reconcile_test")
BUILDING_SUPPORT = load_module(
    TESTS_DIR / "test_building_candidate.py", "_b023_building_support"
)


class BuildingReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.staging = self.root / "staging"
        self.output = self.root / "output"
        self.fake = BUILDING_SUPPORT.FakeArcGIS()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def polygon(west: float, south: float, east: float, north: float) -> dict[str, Any]:
        return {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        }

    def feature(
        self,
        object_id: int,
        fpid: str,
        geometry: dict[str, Any],
        *,
        common_name: str | None = None,
    ) -> dict[str, Any]:
        feature = self.fake.feature(object_id)
        feature["properties"]["FPId"] = fpid
        feature["properties"]["CommonName"] = common_name or f"Building {fpid}"
        feature["geometry"] = geometry
        return feature

    def create_accepted_database(self, features: list[dict[str, Any]]) -> Path:
        database = self.root / "kane-condo.gpkg"
        RECONCILE.kane_db.initialize_database(database)
        profile, _ = RECONCILE.kane_candidate.load_building_profile()
        accepted_geojson = self.root / "accepted-buildings.geojson"
        document = {"type": "FeatureCollection", "features": features}
        raw = RECONCILE.canonical_bytes(document)
        accepted_geojson.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        release_key = "kane-buildings-accepted-reconcile-fixture"
        descriptor = {
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
                "description": "Synthetic reconciliation fixture",
                "data_kind": "buildings",
                "source_uri": profile["source"]["layer_url"],
            },
            "harvest": {
                "harvest_key": release_key + "-harvest",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {
                    "id_property": "FPId",
                    "object_id_field": "OBJECTID",
                },
                "object_count": len(features),
            },
            "files": [{
                "file_role": "source",
                "relative_path": "accepted/accepted-buildings.geojson",
                "byte_length": len(raw),
                "sha256": digest,
                "media_type": "application/geo+json",
            }],
            "release": {
                "release_key": release_key,
                "lifecycle_status": "accepted",
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": digest,
                "feature_count": len(features),
                "metadata": {"id_property": "FPId"},
                "accepted_at": "2025-07-30T13:00:00.000Z",
            },
        }
        descriptor_path = self.root / "accepted-descriptor.json"
        descriptor_path.write_bytes(RECONCILE.canonical_bytes(descriptor))
        RECONCILE.kane_candidate.kane_provenance.record_descriptor(
            database, descriptor_path
        )
        RECONCILE.kane_buildings.import_buildings(
            database, release_key, accepted_geojson
        )
        RECONCILE.kane_project.seed_project_buildings(database, release_key)
        self.assertEqual([], RECONCILE.kane_classifications.validate_database(database))
        return database

    def harvest_candidate(self, features: list[dict[str, Any]]) -> Path:
        object_ids = [int(item["properties"]["OBJECTID"]) for item in features]
        self.fake.object_ids = list(reversed(object_ids))
        self.fake.feature_overrides = {
            int(item["properties"]["OBJECTID"]): item for item in features
        }
        result = RECONCILE.kane_candidate.harvest_candidate(
            self.staging,
            requester=self.fake,
            started_at="2026-08-11T16:00:00.000Z",
            completed_at="2026-08-11T16:01:00.000Z",
        )
        return Path(result["candidate_directory"])

    def register_candidate(self, database: Path, candidate: Path) -> None:
        result = RECONCILE.kane_candidate.register_candidate(database, candidate)
        self.assertTrue(result["registered"])

    def project_for_identity(self, database: Path, identity: str) -> sqlite3.Row:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT pb.project_building_id, pb.building_key, pb.lifecycle_status "
                "FROM project_building pb "
                "JOIN project_building_source_mapping m "
                "ON m.project_building_id = pb.project_building_id "
                "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
                "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
                "WHERE sr.lifecycle_status = 'accepted' AND sb.source_feature_id = ? "
                "AND m.mapping_status = 'confirmed'",
                (identity,),
            ).fetchone()
            if row is None:
                raise AssertionError(f"Missing project mapping for {identity}")
            return row
        finally:
            connection.close()

    def prepare(
        self,
        accepted: list[dict[str, Any]],
        candidate_features: list[dict[str, Any]],
    ) -> tuple[Path, Path, dict[str, Any]]:
        database = self.create_accepted_database(accepted)
        candidate = self.harvest_candidate(candidate_features)
        self.register_candidate(database, candidate)
        result = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        return database, candidate, result

    def read_report(self, result: dict[str, Any]) -> dict[str, Any]:
        path = Path(result["reconciliation_directory"]) / RECONCILE.REPORT_FILENAME
        return json.loads(path.read_text(encoding="utf-8"))

    def test_common_identity_continues_existing_project(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        accepted = [self.feature(1, "fp-1", geom)]
        candidate = [self.feature(1, "fp-1", geom)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertTrue(report["ready_for_promotion"])
        self.assertEqual(1, report["automatic_summary"]["continuation_mapping_count"])
        self.assertEqual(0, report["automatic_summary"]["addition_count"])
        self.assertEqual(0, report["ambiguity_count"])
        self.assertEqual(1, report["candidate_mapping"]["mapped_source_count"])

    def test_same_identity_geometry_redraw_is_automatic(self) -> None:
        accepted_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        candidate_geom = self.polygon(-88.50, 41.90, -88.488, 41.91)
        accepted = [self.feature(1, "fp-1", accepted_geom)]
        candidate = [self.feature(1, "fp-1", candidate_geom)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertTrue(report["ready_for_promotion"])
        self.assertEqual(1, report["automatic_summary"]["geometry_redraw_mapping_count"])

    def test_exact_geometry_renumber_is_replacement(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        accepted = [self.feature(1, "old-id", geom)]
        candidate = [self.feature(2, "new-id", geom)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertTrue(report["ready_for_promotion"])
        self.assertEqual(1, report["automatic_summary"]["replacement_mapping_count"])
        self.assertEqual(0, report["automatic_summary"]["addition_count"])
        self.assertEqual(0, report["automatic_summary"]["disappearance_count"])

    def test_classification_stays_on_project_across_replacement(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "old-id", geom)])
        project = self.project_for_identity(database, "old-id")
        RECONCILE.kane_classifications.set_classification(
            database, str(project["building_key"]), "condominium", "test:b023:replacement"
        )
        candidate = self.harvest_candidate([self.feature(2, "new-id", geom)])
        self.register_candidate(database, candidate)
        result = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        report = self.read_report(result)
        self.assertTrue(report["classification_preservation"]["unchanged"])
        candidate_db = Path(result["reconciliation_directory"]) / RECONCILE.DATABASE_FILENAME
        info = RECONCILE.kane_classifications.classification_get(
            candidate_db, str(project["building_key"])
        )
        self.assertEqual("condominium", info["classification"])
        connection = sqlite3.connect(candidate_db)
        try:
            rows = connection.execute(
                "SELECT sb.source_feature_id, m.relationship_type "
                "FROM project_building_source_mapping m "
                "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
                "WHERE m.project_building_id = ? AND m.mapping_status = 'confirmed' "
                "ORDER BY m.mapping_id",
                (project["project_building_id"],),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(("new-id", "replacement"), rows[-1])

    def test_clear_addition_creates_new_project_identity(self) -> None:
        old_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        new_geom = self.polygon(-88.40, 41.80, -88.39, 41.81)
        accepted = [self.feature(1, "fp-1", old_geom)]
        candidate = [
            self.feature(1, "fp-1", old_geom),
            self.feature(2, "fp-2", new_geom),
        ]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertTrue(report["ready_for_promotion"])
        self.assertEqual(1, report["automatic_summary"]["addition_count"])
        self.assertEqual(2, report["project_state"]["after"]["count"])
        self.assertEqual(1, report["project_state"]["new_project_building_count"])
        self.assertEqual(2, report["candidate_mapping"]["mapped_source_count"])

    def test_clear_disappearance_marks_project_inactive_and_keeps_classification(self) -> None:
        old_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        far_geom = self.polygon(-88.30, 41.70, -88.29, 41.71)
        database = self.create_accepted_database([self.feature(1, "old-id", old_geom)])
        project = self.project_for_identity(database, "old-id")
        RECONCILE.kane_classifications.set_classification(
            database, str(project["building_key"]), "apartments", "test:b023:disappear"
        )
        candidate = self.harvest_candidate([self.feature(2, "new-id", far_geom)])
        self.register_candidate(database, candidate)
        result = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        report = self.read_report(result)
        self.assertTrue(report["ready_for_promotion"])
        self.assertEqual(1, report["automatic_summary"]["disappearance_count"])
        candidate_db = Path(result["reconciliation_directory"]) / RECONCILE.DATABASE_FILENAME
        connection = sqlite3.connect(candidate_db)
        try:
            state = connection.execute(
                "SELECT lifecycle_status FROM project_building WHERE project_building_id = ?",
                (project["project_building_id"],),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("inactive", state)
        info = RECONCILE.kane_classifications.classification_get(
            candidate_db, str(project["building_key"])
        )
        self.assertEqual("apartments", info["classification"])

    def test_inactive_project_reappears_on_same_identity(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        project = self.project_for_identity(database, "fp-1")
        RECONCILE.kane_classifications.set_classification(
            database,
            str(project["building_key"]),
            "condominium",
            "test:b023:reappearance",
        )
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE project_building SET lifecycle_status = 'inactive' "
                "WHERE project_building_id = ?",
                (project["project_building_id"],),
            )
            connection.commit()
        finally:
            connection.close()
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        result = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        report = self.read_report(result)
        self.assertEqual(1, report["automatic_summary"]["continuation_mapping_count"])
        candidate_db = Path(result["reconciliation_directory"]) / RECONCILE.DATABASE_FILENAME
        connection = sqlite3.connect(candidate_db)
        try:
            state = connection.execute(
                "SELECT lifecycle_status FROM project_building WHERE project_building_id = ?",
                (project["project_building_id"],),
            ).fetchone()[0]
            relationship = connection.execute(
                "SELECT m.relationship_type FROM project_building_source_mapping m "
                "JOIN source_building sb ON sb.source_building_id = m.source_building_id "
                "JOIN source_release sr ON sr.source_release_id = sb.source_release_id "
                "WHERE m.project_building_id = ? AND sr.lifecycle_status = 'candidate'",
                (project["project_building_id"],),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual("active", state)
        self.assertEqual("reappearance", relationship)
        classification = RECONCILE.kane_classifications.classification_get(
            candidate_db, str(project["building_key"])
        )
        self.assertEqual("condominium", classification["classification"])

    def test_retired_project_in_accepted_mapping_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        project = self.project_for_identity(database, "fp-1")
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE project_building SET lifecycle_status = 'retired', "
                "retired_at = '2026-08-11T16:00:00.000Z' WHERE project_building_id = ?",
                (project["project_building_id"],),
            )
            connection.commit()
        finally:
            connection.close()
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        with self.assertRaisesRegex(RuntimeError, "Retired project building"):
            RECONCILE.build_plan(database, candidate)

    def test_uncertain_one_to_one_replacement_is_ambiguity(self) -> None:
        accepted_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        candidate_geom = self.polygon(-88.499, 41.901, -88.4895, 41.9095)
        accepted = [self.feature(1, "old-id", accepted_geom)]
        candidate = [self.feature(2, "new-id", candidate_geom)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertFalse(report["ready_for_promotion"])
        self.assertEqual(1, report["ambiguity_count"])
        self.assertEqual("uncertain_replacement", report["ambiguities"][0]["kind"])
        self.assertEqual(1, report["candidate_mapping"]["unmapped_source_count"])

    def test_split_isolated_as_ambiguity(self) -> None:
        accepted_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        left = self.polygon(-88.50, 41.90, -88.495, 41.91)
        right = self.polygon(-88.495, 41.90, -88.49, 41.91)
        accepted = [self.feature(1, "old-id", accepted_geom)]
        candidate = [
            self.feature(2, "new-a", left),
            self.feature(3, "new-b", right),
        ]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertFalse(report["ready_for_promotion"])
        self.assertEqual("split", report["ambiguities"][0]["kind"])
        self.assertEqual(["new-a", "new-b"], report["candidate_mapping"]["unmapped_identities"])

    def test_merge_isolated_as_ambiguity(self) -> None:
        left = self.polygon(-88.50, 41.90, -88.495, 41.91)
        right = self.polygon(-88.495, 41.90, -88.49, 41.91)
        merged = self.polygon(-88.499, 41.90, -88.491, 41.91)
        accepted = [
            self.feature(1, "old-a", left),
            self.feature(2, "old-b", right),
        ]
        candidate = [self.feature(3, "new-merged", merged)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertFalse(report["ready_for_promotion"])
        self.assertEqual("merge", report["ambiguities"][0]["kind"])
        self.assertEqual(1, report["candidate_mapping"]["unmapped_source_count"])

    def test_complex_overlap_isolated_as_ambiguity(self) -> None:
        old_a = self.polygon(-88.50, 41.90, -88.494, 41.91)
        old_b = self.polygon(-88.496, 41.90, -88.49, 41.91)
        new_a = self.polygon(-88.499, 41.90, -88.493, 41.91)
        new_b = self.polygon(-88.497, 41.90, -88.491, 41.91)
        accepted = [self.feature(1, "old-a", old_a), self.feature(2, "old-b", old_b)]
        candidate = [self.feature(3, "new-a", new_a), self.feature(4, "new-b", new_b)]
        _database, _candidate, result = self.prepare(accepted, candidate)
        report = self.read_report(result)
        self.assertFalse(report["ready_for_promotion"])
        self.assertEqual("complex", report["ambiguities"][0]["kind"])

    def test_ambiguity_reports_affected_classification(self) -> None:
        accepted_geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        candidate_geom = self.polygon(-88.499, 41.901, -88.4895, 41.9095)
        database = self.create_accepted_database([self.feature(1, "old-id", accepted_geom)])
        project = self.project_for_identity(database, "old-id")
        RECONCILE.kane_classifications.set_classification(
            database, str(project["building_key"]), "other", "test:b023:ambiguity"
        )
        candidate = self.harvest_candidate([self.feature(2, "new-id", candidate_geom)])
        self.register_candidate(database, candidate)
        result = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        report = self.read_report(result)
        affected = report["ambiguities"][0]["affected_project_buildings"]
        self.assertEqual(
            [{"building_key": str(project["building_key"]), "classification": "other"}],
            affected,
        )

    def test_overlap_grid_limits_candidates_without_missing_overlap(self) -> None:
        accepted_sources = {
            "old-a": {"bounds": [-88.50, 41.90, -88.49, 41.91]},
            "old-b": {"bounds": [-88.20, 42.00, -88.19, 42.01]},
        }
        candidate_sources = {
            "new-a": {"bounds": [-88.495, 41.905, -88.485, 41.915]},
            "new-far": {"bounds": [-87.90, 41.50, -87.89, 41.51]},
        }
        old_edges, new_edges = RECONCILE._overlap_edges(
            accepted_sources,
            candidate_sources,
            set(accepted_sources),
            set(candidate_sources),
        )
        self.assertEqual({"new-a"}, old_edges["old-a"])
        self.assertEqual(set(), old_edges["old-b"])
        self.assertEqual({"old-a"}, new_edges["new-a"])
        self.assertEqual(set(), new_edges["new-far"])

    def test_plan_is_deterministic(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        first = RECONCILE.build_plan(database, candidate)
        second = RECONCILE.build_plan(database, candidate)
        self.assertEqual(first, second)

    def test_prepare_does_not_modify_accepted_database(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        before = RECONCILE.sha256_file(database)
        RECONCILE.prepare_reconciliation(database, candidate, self.output)
        after = RECONCILE.sha256_file(database)
        self.assertEqual(before, after)

    def test_prepare_is_idempotent_for_existing_artifact(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        first = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        second = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(first["reconciliation_key"], second["reconciliation_key"])

    def test_authoritative_database_change_creates_new_reconciliation_identity(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        project = self.project_for_identity(database, "fp-1")
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        first = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        RECONCILE.kane_classifications.set_classification(
            database,
            str(project["building_key"]),
            "other",
            "test:b023:database-state",
        )
        second = RECONCILE.prepare_reconciliation(database, candidate, self.output)
        self.assertNotEqual(first["reconciliation_key"], second["reconciliation_key"])
        self.assertFalse(second["existing"])
        second_database = (
            Path(second["reconciliation_directory"]) / RECONCILE.DATABASE_FILENAME
        )
        info = RECONCILE.kane_classifications.classification_get(
            second_database, str(project["building_key"])
        )
        self.assertEqual("other", info["classification"])

    def test_reconciliation_artifact_validates_offline(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        validation = RECONCILE.validate_reconciliation(
            Path(result["reconciliation_directory"])
        )
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["ready_for_promotion"])

    def test_tampered_report_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        directory = Path(result["reconciliation_directory"])
        path = directory / RECONCILE.REPORT_FILENAME
        report = json.loads(path.read_text())
        report["ready_for_promotion"] = False
        path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            RECONCILE.validate_reconciliation(directory)

    def test_tampered_candidate_database_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        directory = Path(result["reconciliation_directory"])
        path = directory / RECONCILE.DATABASE_FILENAME
        path.write_bytes(path.read_bytes() + b"x")
        with self.assertRaisesRegex(RuntimeError, "file identity"):
            RECONCILE.validate_reconciliation(directory)

    def test_extra_artifact_file_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        directory = Path(result["reconciliation_directory"])
        (directory / "extra.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "files are invalid"):
            RECONCILE.validate_reconciliation(directory)

    def test_artifact_symlink_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        directory = Path(result["reconciliation_directory"])
        report_path = directory / RECONCILE.REPORT_FILENAME
        report_copy = directory.parent / "report-copy.json"
        shutil.copy2(report_path, report_copy)
        report_path.unlink()
        report_path.symlink_to(report_copy)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            RECONCILE.validate_reconciliation(directory)

    def test_unregistered_candidate_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        with self.assertRaisesRegex(RuntimeError, "candidate release|found 0"):
            RECONCILE.build_plan(database, candidate)

    def test_candidate_registration_content_mismatch_is_rejected(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE source_release SET content_sha256 = ? WHERE lifecycle_status = 'candidate'",
                ("0" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RuntimeError):
            RECONCILE.build_plan(database, candidate)

    def test_reconciliation_info_reports_summary_without_machine_paths(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        _database, _candidate, result = self.prepare(
            [self.feature(1, "fp-1", geom)],
            [self.feature(1, "fp-1", geom)],
        )
        info = RECONCILE.reconciliation_info(Path(result["reconciliation_directory"]))
        self.assertTrue(info["valid"])
        encoded = json.dumps(info, sort_keys=True)
        self.assertNotIn(str(self.root), encoded)
        self.assertIn("automatic_summary", info)
        self.assertIn("classification_preservation", info)

    def test_public_wrapper_help_lists_commands(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        for command in ("prepare", "validate", "info"):
            self.assertIn(command, completed.stdout)

    def test_public_wrapper_prepare_and_validate(self) -> None:
        geom = self.polygon(-88.50, 41.90, -88.49, 41.91)
        database = self.create_accepted_database([self.feature(1, "fp-1", geom)])
        candidate = self.harvest_candidate([self.feature(1, "fp-1", geom)])
        self.register_candidate(database, candidate)
        completed = subprocess.run(
            [
                "bash",
                str(WRAPPER),
                "prepare",
                str(database),
                str(candidate),
                str(self.output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        validation = subprocess.run(
            [
                "bash",
                str(WRAPPER),
                "validate",
                result["reconciliation_directory"],
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validation.returncode, validation.stderr)
        self.assertTrue(json.loads(validation.stdout)["valid"])

    def test_public_wrapper_rejects_missing_artifact(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "validate", str(self.root / "missing")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("ERROR:", completed.stderr)


if __name__ == "__main__":
    unittest.main()
