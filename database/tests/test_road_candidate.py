#!/usr/bin/env python3
"""Tests for the Batch 019 official-road candidate harvest."""

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
from typing import Any, Mapping

DATABASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = DATABASE_DIR / "tools"
MODULE_PATH = TOOLS_DIR / "kane_road_candidate.py"
WRAPPER = DATABASE_DIR / "kane-road-candidate.sh"
ROOT = DATABASE_DIR.parent


def load_module():
    spec = importlib.util.spec_from_file_location("_kane_road_candidate_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load road-candidate module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CANDIDATE = load_module()
class FakeRoadArcGIS:
    def __init__(self) -> None:
        self.profile, _ = CANDIDATE.load_road_profile()
        self.object_ids: list[Any] = [3, 1, 2]
        self.max_record_count = 2
        self.null_geometry_ids: set[int] = set()
        self.feature_overrides: dict[int, dict[str, Any]] = {}
        self.metadata: dict[str, Any] = {
            "type": "Feature Layer",
            "name": "Kane County Road Centerlines",
            "geometryType": self.profile["geometry"]["arcgis_type"],
            "supportedQueryFormats": "JSON, geoJSON",
            "objectIdField": self.profile["query"]["object_id_field"],
            "fields": [{"name": name} for name in self.profile["query"]["out_fields"]],
            "maxRecordCount": self.max_record_count,
            "editingInfo": {
                "lastEditDate": 1753885668846,
                "schemaLastEditDate": 1754339853996,
                "dataLastEditDate": 1753885668846,
            },
        }
        self.calls: list[dict[str, Any]] = []

    def feature(self, object_id: int) -> dict[str, Any]:
        base_x = -88.0 + object_id * 0.01
        base_y = 41.0 + object_id * 0.01
        feature: dict[str, Any] = {
            "type": "Feature",
            "properties": {"OBJECTID": object_id},
            "geometry": None if object_id in self.null_geometry_ids else {
                "type": "LineString",
                "coordinates": [
                    [base_x, base_y],
                    [base_x + 0.002, base_y + 0.001],
                ],
            },
        }
        override = self.feature_overrides.get(object_id)
        if override:
            feature.update(override)
        return feature

    def __call__(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        timeout_seconds: float,
        byte_limit: int,
        post: bool,
    ) -> Any:
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "timeout_seconds": timeout_seconds,
                "byte_limit": byte_limit,
                "post": post,
            }
        )
        if not url.endswith("/query"):
            return self.metadata
        if params.get("returnIdsOnly") == "true":
            return {
                "objectIdFieldName": self.profile["query"]["object_id_field"],
                "objectIds": list(self.object_ids),
            }
        requested = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [self.feature(value) for value in reversed(requested)],
        }

class RoadCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.staging = self.root / "staging"
        self.fake = FakeRoadArcGIS()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def harvest(self) -> dict[str, Any]:
        return CANDIDATE.harvest_candidate(
            self.staging,
            requester=self.fake,
            started_at="2026-08-06T19:30:00.000Z",
            completed_at="2026-08-06T19:31:00.000Z",
        )

    def candidate_dir(self) -> Path:
        return Path(self.harvest()["candidate_directory"])

    def create_accepted_database(self) -> Path:
        database = self.root / "kane-condo.gpkg"
        CANDIDATE.kane_map_layers.kane_db.initialize_database(database)
        profile, _ = CANDIDATE.load_road_profile()
        accepted_geojson = self.root / "accepted-roads.geojson"
        feature = self.fake.feature(1)
        accepted_document = {
            "type": "FeatureCollection",
            "features": [feature],
        }
        accepted_raw = CANDIDATE.canonical_bytes(accepted_document)
        accepted_geojson.write_bytes(accepted_raw)
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
                "dataset_key": "roads",
                "name": "Kane County Roads",
                "description": "Official road centerline geometry",
                "data_kind": "roads",
                "source_uri": profile["source"]["layer_url"],
            },
            "harvest": {
                "harvest_key": "kane-roads-harvest-accepted-fixture",
                "started_at": "2025-07-30T12:00:00.000Z",
                "completed_at": "2025-07-30T12:01:00.000Z",
                "status": "succeeded",
                "source_metadata": {
                    "id_property": "OBJECTID",
                    "object_id_field": "OBJECTID",
                },
                "object_count": 1,
            },
            "files": [
                {
                    "file_role": "source",
                    "relative_path": "accepted/accepted-roads.geojson",
                    "byte_length": len(accepted_raw),
                    "sha256": hashlib.sha256(accepted_raw).hexdigest(),
                    "media_type": "application/geo+json",
                }
            ],
            "release": {
                "release_key": "kane-roads-accepted-fixture",
                "lifecycle_status": "accepted",
                "source_published_at": "2025-07-30T10:30:00.000Z",
                "content_sha256": hashlib.sha256(accepted_raw).hexdigest(),
                "feature_count": 1,
                "metadata": {"id_property": "OBJECTID"},
                "accepted_at": "2025-07-30T13:00:00.000Z",
            },
        }
        descriptor_path = self.root / "accepted-descriptor.json"
        descriptor_path.write_bytes(CANDIDATE.canonical_bytes(descriptor))
        CANDIDATE.kane_provenance.record_descriptor(database, descriptor_path)
        CANDIDATE.kane_map_layers.import_map_layers(
            database, [("kane-roads-accepted-fixture", accepted_geojson)]
        )
        self.assertEqual([], CANDIDATE.kane_map_layers.validate_database(database))
        return database
    def test_road_profile_is_exact_registry_profile(self) -> None:
        profile, registry_hash = CANDIDATE.load_road_profile()
        self.assertEqual("roads", profile["dataset_key"])
        self.assertEqual("OBJECTID", profile["query"]["identity_field"])
        self.assertEqual(
            "e95c9d0486f65035146cb0a2a9580e4148c853a78c4f9e44e2420f59ef654e12",
            registry_hash,
        )

    def test_complete_harvest_creates_valid_candidate(self) -> None:
        result = self.harvest()
        self.assertTrue(result["valid"])
        self.assertFalse(result["existing"])
        self.assertEqual(3, result["feature_count"])
        candidate_dir = Path(result["candidate_directory"])
        self.assertEqual(CANDIDATE.REQUIRED_CANDIDATE_FILES, {p.name for p in candidate_dir.iterdir()})
        validated = CANDIDATE.validate_candidate(candidate_dir)
        self.assertEqual(result["content_sha256"], validated["content_sha256"])

    def test_harvest_orders_inventory_and_features_by_object_id(self) -> None:
        candidate_dir = self.candidate_dir()
        inventory = json.loads((candidate_dir / "object-ids.json").read_text())
        collection = json.loads((candidate_dir / "roads.geojson").read_text())
        self.assertEqual([1, 2, 3], inventory)
        self.assertEqual([1, 2, 3], [f["properties"]["OBJECTID"] for f in collection["features"]])

    def test_harvest_respects_service_max_record_count(self) -> None:
        self.harvest()
        page_calls = [
            call for call in self.fake.calls
            if call["url"].endswith("/query") and "objectIds" in call["params"]
        ]
        self.assertEqual(2, len(page_calls))
        self.assertEqual(["1,2", "3"], [call["params"]["objectIds"] for call in page_calls])

    def test_harvest_rechecks_metadata_and_inventory_after_pages(self) -> None:
        self.harvest()
        metadata_calls = [
            call for call in self.fake.calls if not call["url"].endswith("/query")
        ]
        inventory_calls = [
            call
            for call in self.fake.calls
            if call["url"].endswith("/query")
            and call["params"].get("returnIdsOnly") == "true"
        ]
        self.assertEqual(2, len(metadata_calls))
        self.assertEqual(2, len(inventory_calls))

    def test_harvest_rejects_inventory_change_during_download(self) -> None:
        original = self.fake.__call__
        inventory_calls = 0

        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            nonlocal inventory_calls
            value = original(url, params, **kwargs)
            if params.get("returnIdsOnly") == "true":
                inventory_calls += 1
                if inventory_calls == 2:
                    value["objectIds"] = [1, 2, 3, 4]
            return value

        with self.assertRaisesRegex(
            CANDIDATE.HarvestContractError, "inventory changed during"
        ):
            CANDIDATE.harvest_candidate(
                self.staging,
                requester=requester,
                started_at="2026-08-06T19:30:00.000Z",
                completed_at="2026-08-06T19:31:00.000Z",
            )

    def test_harvest_is_deterministic_for_same_source_and_timestamps(self) -> None:
        first = self.harvest()
        second_root = self.root / "second"
        second_fake = FakeRoadArcGIS()
        second = CANDIDATE.harvest_candidate(
            second_root,
            requester=second_fake,
            started_at="2026-08-06T19:30:00.000Z",
            completed_at="2026-08-06T19:31:00.000Z",
        )
        self.assertEqual(first["release_key"], second["release_key"])
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])

    def test_repeated_identical_harvest_reuses_valid_candidate(self) -> None:
        first = self.harvest()
        second = self.harvest()
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(first["candidate_directory"], second["candidate_directory"])

    def test_harvest_rejects_reversed_timestamps_and_cleans_temporary_data(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "completed_at precedes started_at"):
            CANDIDATE.harvest_candidate(
                self.staging,
                requester=self.fake,
                started_at="2026-08-06T19:31:00.000Z",
                completed_at="2026-08-06T19:30:00.000Z",
            )
        roads_root = self.staging / "roads"
        self.assertTrue(not roads_root.exists() or list(roads_root.iterdir()) == [])

    def test_duplicate_inventory_ids_are_rejected(self) -> None:
        self.fake.object_ids = [1, 1, 2]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "duplicate"):
            self.harvest()

    def test_noninteger_inventory_id_is_rejected(self) -> None:
        self.fake.object_ids = [1, "2", 3]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "nonnegative JSON integer"):
            self.harvest()

    def test_missing_geojson_support_is_rejected(self) -> None:
        self.fake.metadata["supportedQueryFormats"] = "JSON"
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "GeoJSON"):
            self.harvest()

    def test_wrong_layer_geometry_is_rejected(self) -> None:
        self.fake.metadata["geometryType"] = "esriGeometryPoint"
        with self.assertRaises(Exception):
            self.harvest()

    def test_page_missing_requested_object_id_is_rejected(self) -> None:
        original = self.fake.__call__

        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            value = original(url, params, **kwargs)
            if url.endswith("/query") and "objectIds" in params:
                value["features"] = value["features"][:-1]
            return value

        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "object-ID mismatch"):
            CANDIDATE.harvest_candidate(
                self.staging,
                requester=requester,
                started_at="2026-08-06T19:30:00.000Z",
                completed_at="2026-08-06T19:31:00.000Z",
            )

    def test_feature_object_id_must_match_requested_id(self) -> None:
        feature = self.fake.feature(1)
        feature["properties"]["OBJECTID"] = 99
        self.fake.feature_overrides[1] = feature
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "object-ID mismatch"):
            self.harvest()

    def test_missing_requested_object_id_field_is_rejected(self) -> None:
        feature = self.fake.feature(1)
        del feature["properties"]["OBJECTID"]
        self.fake.feature_overrides[1] = feature
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "missing requested fields"):
            self.harvest()

    def test_null_geometry_is_excluded_and_preserved_as_evidence(self) -> None:
        self.fake.null_geometry_ids = {2}
        result = self.harvest()
        self.assertEqual(3, result["object_count"])
        self.assertEqual(2, result["feature_count"])
        self.assertEqual(1, result["excluded_count"])
        candidate_dir = Path(result["candidate_directory"])
        self.assertEqual([2], json.loads((candidate_dir / "excluded-object-ids.json").read_text()))
        collection = json.loads((candidate_dir / "roads.geojson").read_text())
        self.assertEqual([1, 3], [f["properties"]["OBJECTID"] for f in collection["features"]])
        validated = CANDIDATE.validate_candidate(candidate_dir)
        self.assertEqual(1, validated["excluded_count"])

    def test_invalid_linestring_is_rejected(self) -> None:
        feature = self.fake.feature(1)
        feature["geometry"]["coordinates"] = [[-88.0, 41.0]]
        self.fake.feature_overrides[1] = feature
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "at least two positions"):
            self.harvest()

    def test_polygon_geometry_is_rejected(self) -> None:
        feature = self.fake.feature(1)
        feature["geometry"] = {
            "type": "Polygon",
            "coordinates": [[
                [-88.0, 41.0],
                [-87.99, 41.0],
                [-87.99, 41.01],
                [-88.0, 41.0],
            ]],
        }
        self.fake.feature_overrides[1] = feature
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "Unsupported linear geometry"):
            self.harvest()

    def test_multilinestring_is_preserved(self) -> None:
        feature = self.fake.feature(1)
        feature["geometry"] = {
            "type": "MultiLineString",
            "coordinates": [
                [[-88.0, 41.0], [-87.99, 41.01]],
                [[-87.98, 41.02], [-87.97, 41.03]],
            ],
        }
        self.fake.feature_overrides[1] = feature
        candidate_dir = self.candidate_dir()
        collection = json.loads((candidate_dir / "roads.geojson").read_text())
        first = collection["features"][0]
        self.assertEqual("MultiLineString", first["geometry"]["type"])
        self.assertEqual([], CANDIDATE.validate_candidate(candidate_dir).get("errors", []))

    def test_excluded_candidate_registration_preserves_object_count(self) -> None:
        self.fake.null_geometry_ids = {2}
        database = self.create_accepted_database()
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        trace = result["trace"]
        self.assertEqual(3, trace["harvest"]["object_count"])
        self.assertEqual(2, trace["release"]["feature_count"])
        self.assertEqual(1, trace["release"]["metadata"]["excluded_count"])
        self.assertEqual([], CANDIDATE.kane_map_layers.validate_database(database))

    def test_manifest_exclusion_hash_mismatch_is_rejected(self) -> None:
        self.fake.null_geometry_ids = {2}
        candidate_dir = self.candidate_dir()
        manifest_path = candidate_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["exclusions"]["excluded_object_ids_sha256"] = "0" * 64
        manifest_path.write_bytes(CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "exclusion identity"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_tampered_source_file_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        source = candidate_dir / "roads.geojson"
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "canonical serialization"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_extra_candidate_file_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        (candidate_dir / "unexpected.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "file set mismatch"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_candidate_symlink_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        (candidate_dir / "link").symlink_to(candidate_dir / "manifest.json")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_candidate_directory_symlink_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        link = self.root / "candidate-link"
        link.symlink_to(candidate_dir, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "directory must not be a symlink"):
            CANDIDATE.validate_candidate(link)

    def test_response_url_requires_exact_query(self) -> None:
        expected = "https://services1.arcgis.com/path?f=pjson"
        self.assertTrue(CANDIDATE._response_url_matches(expected, expected))
        self.assertFalse(
            CANDIDATE._response_url_matches(
                "https://services1.arcgis.com/path?f=json", expected
            )
        )

    def test_tampered_exclusion_file_is_rejected(self) -> None:
        self.fake.null_geometry_ids = {2}
        candidate_dir = self.candidate_dir()
        (candidate_dir / "excluded-object-ids.json").write_bytes(CANDIDATE.canonical_bytes([1]))
        with self.assertRaises(RuntimeError):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_exclusion_inventory_cannot_name_unknown_object(self) -> None:
        candidate_dir = self.candidate_dir()
        (candidate_dir / "excluded-object-ids.json").write_bytes(CANDIDATE.canonical_bytes([999]))
        with self.assertRaisesRegex(RuntimeError, "unknown object IDs"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        manifest_path = candidate_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["output"]["sha256"] = "0" * 64
        manifest_path.write_bytes(CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "output identity"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_manifest_source_unknown_key_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        manifest_path = candidate_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["source"]["unexpected"] = "x"
        manifest_path.write_bytes(CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(RuntimeError, "source identity"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_candidate_collection_unknown_key_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        source_path = candidate_dir / "roads.geojson"
        collection = json.loads(source_path.read_text())
        collection["unexpected"] = "x"
        source_path.write_bytes(CANDIDATE.canonical_bytes(collection))
        with self.assertRaisesRegex(RuntimeError, "unexpected key set"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_release_key_is_derived_from_date_and_content_hash(self) -> None:
        result = self.harvest()
        self.assertRegex(result["release_key"], r"^kane-roads-candidate-20250730-[0-9a-f]{12}$")
        self.assertTrue(result["release_key"].endswith(result["content_sha256"][:12]))

    def test_registration_adds_candidate_without_changing_accepted_release(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        connection = sqlite3.connect(database)
        try:
            before = connection.execute(
                "SELECT release_key, content_sha256, feature_count FROM source_release "
                "WHERE lifecycle_status = 'accepted'"
            ).fetchone()
        finally:
            connection.close()
        result = CANDIDATE.register_candidate(database, candidate_dir)
        connection = sqlite3.connect(database)
        try:
            after = connection.execute(
                "SELECT release_key, content_sha256, feature_count FROM source_release "
                "WHERE lifecycle_status = 'accepted'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(before, after)
        self.assertTrue(result["accepted_release_unchanged"])
        connection = sqlite3.connect(database)
        try:
            candidate = connection.execute(
                "SELECT lifecycle_status, feature_count FROM source_release WHERE release_key = ?",
                (result["release_key"],),
            ).fetchone()
            self.assertEqual(("candidate", 3), candidate)
            self.assertEqual(1, connection.execute(
                "SELECT COUNT(*) FROM source_release WHERE lifecycle_status = 'accepted'"
            ).fetchone()[0])
            self.assertEqual(1, connection.execute(
                "SELECT COUNT(*) FROM source_release WHERE lifecycle_status = 'candidate'"
            ).fetchone()[0])
        finally:
            connection.close()
        self.assertEqual([], CANDIDATE.kane_map_layers.validate_database(database))

    def test_registration_is_idempotent_for_exact_candidate(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        first = CANDIDATE.register_candidate(database, candidate_dir)
        second = CANDIDATE.register_candidate(database, candidate_dir)
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])

    def test_existing_registration_rejects_file_provenance_mismatch(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        result = CANDIDATE.register_candidate(database, candidate_dir)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE source_file SET sha256 = ? WHERE harvest_run_id = "
                "(SELECT harvest_run_id FROM harvest_run WHERE harvest_key = ?) "
                "AND file_role = 'manifest'",
                ("0" * 64, result["trace"]["harvest"]["harvest_key"]),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "file provenance conflicts"):
            CANDIDATE.register_candidate(database, candidate_dir)

    def test_registration_preserves_accepted_road_storage(self) -> None:
        database = self.create_accepted_database()
        connection = sqlite3.connect(database)
        try:
            before = connection.execute(
                "SELECT f.source_feature_id, f.geometry_sha256, f.attributes_sha256, f.content_sha256 "
                "FROM source_map_feature f JOIN source_release sr "
                "ON sr.source_release_id = f.source_release_id "
                "WHERE sr.lifecycle_status = 'accepted' ORDER BY f.source_map_feature_id"
            ).fetchall()
        finally:
            connection.close()
        protected_before = CANDIDATE._protected_counts(database)
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        protected_after = CANDIDATE._protected_counts(database)
        connection = sqlite3.connect(database)
        try:
            after = connection.execute(
                "SELECT f.source_feature_id, f.geometry_sha256, f.attributes_sha256, f.content_sha256 "
                "FROM source_map_feature f JOIN source_release sr "
                "ON sr.source_release_id = f.source_release_id "
                "WHERE sr.lifecycle_status = 'accepted' ORDER BY f.source_map_feature_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(before, after)
        self.assertEqual(protected_before, protected_after)
        self.assertEqual(1, protected_after["source_map_feature"])
        self.assertTrue(result["protected_state_unchanged"])

    def test_invalid_candidate_is_not_registered(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        (candidate_dir / "object-ids.json").write_text("[3,2,1]\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            CANDIDATE.register_candidate(database, candidate_dir)
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM source_release WHERE lifecycle_status = 'candidate'"
            ).fetchone()[0])
        finally:
            connection.close()

    def test_registration_records_all_candidate_file_hashes(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        result = CANDIDATE.register_candidate(database, candidate_dir)
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute(
                "SELECT file_role, relative_path, byte_length, sha256 FROM source_file sf "
                "JOIN harvest_run h ON h.harvest_run_id = sf.harvest_run_id "
                "WHERE h.harvest_key = ? ORDER BY file_role",
                (result["trace"]["harvest"]["harvest_key"],),
            ).fetchall()
            self.assertEqual(5, len(rows))
            for _role, relative_path, byte_length, sha256 in rows:
                path = candidate_dir / Path(relative_path).name
                self.assertEqual(path.stat().st_size, byte_length)
                self.assertEqual(CANDIDATE.sha256_file(path), sha256)
        finally:
            connection.close()

    def test_candidate_info_requires_candidate_lifecycle(self) -> None:
        database = self.create_accepted_database()
        with self.assertRaisesRegex(RuntimeError, "not a candidate"):
            CANDIDATE.candidate_info(database, "kane-roads-accepted-fixture")

    def test_public_wrapper_help_lists_all_commands(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        for command in ("harvest", "validate", "register", "info"):
            self.assertIn(command, completed.stdout)

    def test_public_wrapper_validate_reports_json(self) -> None:
        candidate_dir = self.candidate_dir()
        completed = subprocess.run(
            ["bash", str(WRAPPER), "validate", str(candidate_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        self.assertNotIn("manifest", result)

    def test_public_wrapper_rejects_missing_candidate(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "validate", str(self.root / "missing")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("Candidate directory", completed.stderr)


if __name__ == "__main__":
    unittest.main()
