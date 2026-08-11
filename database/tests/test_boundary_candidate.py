"""Tests for Batch 021 county-boundary candidate harvesting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

DATABASE_DIR = Path(__file__).resolve().parents[1]
ROOT = DATABASE_DIR.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CANDIDATE = load_module(
    "kane_boundary_candidate_batch021",
    DATABASE_DIR / "tools" / "kane_boundary_candidate.py",
)


class FakeBoundaryArcGIS:
    def __init__(self) -> None:
        self.object_ids = [7]
        self.metadata_calls = 0
        self.inventory_calls = 0
        self.calls: list[dict[str, Any]] = []
        self.metadata_override: dict[str, Any] = {}
        self.feature_override: dict[str, Any] = {}
        self.bounds = [-88.61, 41.71, -88.22, 42.16]
        self.multipolygon = False

    def metadata(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "type": "Feature Layer",
            "name": "County Boundary",
            "geometryType": "esriGeometryPolygon",
            "supportedQueryFormats": "JSON, geoJSON",
            "objectIdField": "OBJECTID",
            "fields": [{"name": "OBJECTID"}],
            "maxRecordCount": 2000,
            "editingInfo": {
                "lastEditDate": 1683666510769,
                "schemaLastEditDate": 1683666510769,
                "dataLastEditDate": 1683666510769,
            },
        }
        value.update(self.metadata_override)
        return value

    def feature(self, object_id: int = 7) -> dict[str, Any]:
        minx, miny, maxx, maxy = self.bounds
        outer = [
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
        ]
        geometry: dict[str, Any]
        if self.multipolygon:
            geometry = {"type": "MultiPolygon", "coordinates": [[outer]]}
        else:
            geometry = {"type": "Polygon", "coordinates": [outer]}
        value: dict[str, Any] = {
            "type": "Feature",
            "properties": {"OBJECTID": object_id},
            "geometry": geometry,
        }
        for key, item in self.feature_override.items():
            value[key] = item
        return value

    def __call__(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        timeout_seconds: float,
        byte_limit: int,
        post: bool,
    ) -> Any:
        self.calls.append({"url": url, "params": dict(params), "post": post})
        if not url.endswith("/query"):
            self.metadata_calls += 1
            return self.metadata()
        if params.get("returnIdsOnly") == "true":
            self.inventory_calls += 1
            return {"objectIdFieldName": "OBJECTID", "objectIds": list(self.object_ids)}
        requested = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [self.feature(value) for value in reversed(requested)],
        }


class BoundaryCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.staging = self.root / "staging"
        self.database = self.root / "kane-condo.gpkg"
        self.fake = FakeBoundaryArcGIS()
        self.create_accepted_database()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def accepted_feature(self, object_id: int = 7) -> dict[str, Any]:
        return self.fake.feature(object_id)

    def create_accepted_database(self, *, county_key: str = "kane-county-il") -> None:
        CANDIDATE.kane_boundary.kane_db.initialize_database(self.database)
        profile, _ = CANDIDATE.load_boundary_profile()
        source = self.root / "accepted-boundary.geojson"
        document = {"type": "FeatureCollection", "features": [self.accepted_feature()]}
        raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        source.write_bytes(raw)
        descriptor = {
            "county": {
                "county_key": county_key,
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
                "dataset_key": "county-boundary",
                "name": "Kane County Boundary",
                "description": "Fixture",
                "data_kind": "boundary",
                "source_uri": profile["source"]["layer_url"],
            },
            "harvest": {
                "harvest_key": "boundary-accepted-harvest",
                "started_at": "2023-05-09T20:14:00.000Z",
                "completed_at": "2023-05-09T20:15:00.000Z",
                "status": "succeeded",
                "source_metadata": {"id_property": "OBJECTID", "object_id_field": "OBJECTID"},
                "object_count": 1,
            },
            "files": [{
                "file_role": "source",
                "relative_path": "accepted/accepted-boundary.geojson",
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "media_type": "application/geo+json",
            }],
            "release": {
                "release_key": "kane-county-boundary-20230509-fixture",
                "lifecycle_status": "accepted",
                "source_published_at": "2023-05-09T20:15:10.769Z",
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "feature_count": 1,
                "metadata": {"id_property": "OBJECTID"},
                "accepted_at": "2023-05-09T21:00:00.000Z",
            },
        }
        descriptor_path = self.root / "accepted-boundary-descriptor.json"
        descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
        CANDIDATE.kane_provenance.record_descriptor(self.database, descriptor_path)
        CANDIDATE.kane_boundary.import_boundary(self.database, descriptor["release"]["release_key"], source)
        self.assertEqual([], CANDIDATE.kane_boundary.validate_database(self.database))

    def harvest(self, requester=None) -> dict[str, Any]:
        return CANDIDATE.harvest_candidate(
            self.staging,
            self.database,
            requester=requester or self.fake,
            started_at="2026-08-11T13:30:00.000Z",
            completed_at="2026-08-11T13:31:00.000Z",
        )

    def candidate_dir(self) -> Path:
        return Path(self.harvest()["candidate_directory"])

    def rewrite_canonical(self, path: Path, value: Any) -> None:
        path.write_bytes(CANDIDATE.canonical_bytes(value))

    def protected_counts(self) -> dict[str, int]:
        connection = sqlite3.connect(self.database)
        try:
            return {
                table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in CANDIDATE.PROTECTED_TABLES
            }
        finally:
            connection.close()

    def test_profile_is_exact_boundary_registry_member(self) -> None:
        profile, registry_hash = CANDIDATE.load_boundary_profile()
        self.assertEqual("county-boundary", profile["dataset_key"])
        self.assertEqual(1, profile["expected_feature_count"])
        self.assertEqual("OBJECTID", profile["query"]["identity_field"])
        self.assertEqual("e95c9d0486f65035146cb0a2a9580e4148c853a78c4f9e44e2420f59ef654e12", registry_hash)

    def test_complete_harvest_creates_exact_file_set(self) -> None:
        result = self.harvest()
        self.assertTrue(result["valid"])
        self.assertFalse(result["existing"])
        candidate = Path(result["candidate_directory"])
        self.assertEqual(CANDIDATE.REQUIRED_CANDIDATE_FILES, {path.name for path in candidate.iterdir()})
        self.assertEqual(1, result["feature_count"])
        self.assertEqual(1, result["object_count"])

    def test_harvest_uses_exact_object_id_query(self) -> None:
        self.harvest()
        pages = [call for call in self.fake.calls if call["url"].endswith("/query") and "objectIds" in call["params"]]
        self.assertEqual(1, len(pages))
        self.assertEqual("7", pages[0]["params"]["objectIds"])
        self.assertEqual("OBJECTID", pages[0]["params"]["outFields"])

    def test_harvest_rechecks_metadata_and_inventory(self) -> None:
        self.harvest()
        self.assertEqual(2, self.fake.metadata_calls)
        self.assertEqual(2, self.fake.inventory_calls)

    def test_inventory_change_during_harvest_is_rejected(self) -> None:
        original = self.fake.__call__
        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            value = original(url, params, **kwargs)
            if params.get("returnIdsOnly") == "true" and self.fake.inventory_calls == 2:
                return {"objectIdFieldName": "OBJECTID", "objectIds": [8]}
            return value
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "inventory changed|identity changed"):
            self.harvest(requester)

    def test_metadata_change_during_harvest_is_rejected(self) -> None:
        original = self.fake.__call__
        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            value = original(url, params, **kwargs)
            if not url.endswith("/query") and self.fake.metadata_calls == 2:
                value = dict(value)
                value["editingInfo"] = dict(value["editingInfo"])
                value["editingInfo"]["dataLastEditDate"] += 1
            return value
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "metadata changed"):
            self.harvest(requester)

    def test_inventory_must_contain_exactly_one_object(self) -> None:
        self.fake.object_ids = [7, 8]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "expected 1"):
            self.harvest()

    def test_changed_county_identity_is_rejected_from_inventory(self) -> None:
        self.fake.object_ids = [8]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "identity changed"):
            self.harvest()

    def test_changed_county_identity_is_rejected_from_feature(self) -> None:
        original = self.fake.__call__
        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            value = original(url, params, **kwargs)
            if url.endswith("/query") and "objectIds" in params:
                value["features"][0]["properties"]["OBJECTID"] = 8
            return value
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "identity changed"):
            self.harvest(requester)

    def test_unexpected_geometry_type_is_rejected(self) -> None:
        self.fake.feature_override["geometry"] = {
            "type": "LineString", "coordinates": [[-88.6, 41.7], [-88.2, 42.1]]
        }
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "invalid geometry|unsupported geometry"):
            self.harvest()

    def test_null_geometry_is_rejected(self) -> None:
        self.fake.feature_override["geometry"] = None
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "invalid geometry"):
            self.harvest()

    def test_gross_longitude_shift_is_rejected(self) -> None:
        self.fake.bounds = [-89.61, 41.71, -89.22, 42.16]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "grossly unexpected longitude|does not overlap"):
            self.harvest()

    def test_gross_latitude_span_is_rejected(self) -> None:
        self.fake.bounds = [-88.61, 41.0, -88.22, 43.0]
        with self.assertRaisesRegex(CANDIDATE.HarvestContractError, "latitude span|latitude bounds"):
            self.harvest()

    def test_modest_boundary_change_within_guard_is_allowed(self) -> None:
        self.fake.bounds = [-88.60, 41.72, -88.21, 42.15]
        result = self.harvest()
        self.assertEqual(self.fake.bounds, result["candidate_bounds"])

    def test_multipolygon_boundary_is_allowed(self) -> None:
        self.fake.multipolygon = True
        candidate = Path(self.harvest()["candidate_directory"])
        document = json.loads((candidate / "boundary.geojson").read_text())
        self.assertEqual("MultiPolygon", document["features"][0]["geometry"]["type"])

    def test_metadata_geometry_drift_is_rejected(self) -> None:
        self.fake.metadata_override["geometryType"] = "esriGeometryPolyline"
        with self.assertRaisesRegex(Exception, "geometryType changed"):
            self.harvest()

    def test_metadata_object_id_drift_is_rejected(self) -> None:
        self.fake.metadata_override["objectIdField"] = "OID"
        with self.assertRaisesRegex(Exception, "object ID field changed"):
            self.harvest()

    def test_wrong_database_county_identity_is_rejected_before_network(self) -> None:
        self.database.unlink()
        self.create_accepted_database(county_key="wrong-county")
        with self.assertRaisesRegex(RuntimeError, "Accepted county identity county_key"):
            self.harvest()
        self.assertEqual([], self.fake.calls)

    def test_offline_validation_round_trips_candidate(self) -> None:
        result = self.harvest()
        validated = CANDIDATE.validate_candidate(Path(result["candidate_directory"]))
        self.assertTrue(validated["valid"])
        self.assertEqual(result["content_sha256"], validated["content_sha256"])
        self.assertEqual(result["candidate_bounds"], validated["candidate_bounds"])

    def test_source_tamper_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        document = json.loads((candidate / "boundary.geojson").read_text())
        document["features"][0]["geometry"]["coordinates"][0][1][0] -= 0.01
        self.rewrite_canonical(candidate / "boundary.geojson", document)
        with self.assertRaisesRegex(RuntimeError, "output identity|grossly|not normalized"):
            CANDIDATE.validate_candidate(candidate)

    def test_manifest_accepted_identity_tamper_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        manifest = json.loads((candidate / "manifest.json").read_text())
        manifest["accepted_reference"]["accepted_source_feature_id"] = "8"
        self.rewrite_canonical(candidate / "manifest.json", manifest)
        with self.assertRaisesRegex(RuntimeError, "identity"):
            CANDIDATE.validate_candidate(candidate)

    def test_manifest_county_identity_tamper_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        manifest = json.loads((candidate / "manifest.json").read_text())
        manifest["accepted_reference"]["fips_code"] = "00000"
        self.rewrite_canonical(candidate / "manifest.json", manifest)
        with self.assertRaisesRegex(RuntimeError, "fips_code"):
            CANDIDATE.validate_candidate(candidate)

    def test_manifest_bounds_policy_tamper_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        manifest = json.loads((candidate / "manifest.json").read_text())
        manifest["accepted_reference"]["gross_bounds_policy"]["edge_tolerance_ratio"] = 1.0
        self.rewrite_canonical(candidate / "manifest.json", manifest)
        with self.assertRaisesRegex(RuntimeError, "gross-bounds policy"):
            CANDIDATE.validate_candidate(candidate)

    def test_unknown_candidate_file_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        (candidate / "extra.json").write_text("{}\n")
        with self.assertRaisesRegex(RuntimeError, "file set mismatch"):
            CANDIDATE.validate_candidate(candidate)

    def test_candidate_file_symlink_is_rejected(self) -> None:
        candidate = self.candidate_dir()
        original = candidate / "object-ids.json"
        copy = candidate / "inventory-copy.json"
        shutil.copy2(original, copy)
        original.unlink()
        os.symlink(copy.name, original)
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            CANDIDATE.validate_candidate(candidate)

    def test_reharvest_is_deterministic_and_returns_existing(self) -> None:
        first = self.harvest()
        second = self.harvest()
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first["release_key"], second["release_key"])

    def test_registration_records_candidate_provenance_only(self) -> None:
        result = self.harvest()
        before = self.protected_counts()
        registered = CANDIDATE.register_candidate(self.database, Path(result["candidate_directory"]))
        self.assertTrue(registered["registered"])
        self.assertFalse(registered["existing"])
        self.assertTrue(registered["accepted_release_unchanged"])
        self.assertTrue(registered["protected_state_unchanged"])
        self.assertEqual(before, self.protected_counts())
        self.assertEqual("candidate", registered["trace"]["release"]["lifecycle_status"])
        self.assertEqual("county-boundary", registered["trace"]["dataset"]["dataset_key"])

    def test_registration_leaves_accepted_boundary_unchanged(self) -> None:
        before = CANDIDATE.kane_boundary.boundary_info(self.database)
        result = self.harvest()
        CANDIDATE.register_candidate(self.database, Path(result["candidate_directory"]))
        after = CANDIDATE.kane_boundary.boundary_info(self.database)
        self.assertEqual(before, after)

    def test_registration_is_idempotent(self) -> None:
        result = self.harvest()
        candidate = Path(result["candidate_directory"])
        first = CANDIDATE.register_candidate(self.database, candidate)
        second = CANDIDATE.register_candidate(self.database, candidate)
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])
        self.assertEqual(first["release_key"], second["release_key"])

    def test_registration_rejects_stale_accepted_reference(self) -> None:
        result = self.harvest()
        candidate = Path(result["candidate_directory"])
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                "UPDATE source_release SET content_sha256 = ? WHERE lifecycle_status = 'accepted' AND source_release_id IN (SELECT source_release_id FROM source_county_boundary)",
                ("f" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "Accepted county boundary changed"):
            CANDIDATE.register_candidate(self.database, candidate)

    def test_candidate_info_traces_registered_candidate(self) -> None:
        result = self.harvest()
        CANDIDATE.register_candidate(self.database, Path(result["candidate_directory"]))
        info = CANDIDATE.candidate_info(self.database, result["release_key"])
        self.assertTrue(info["valid"])
        self.assertEqual(result["release_key"], info["candidate"]["release"]["release_key"])

    def test_public_validate_command_outputs_json(self) -> None:
        result = self.harvest()
        completed = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-boundary-candidate.sh"), "validate", result["candidate_directory"]],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(result["release_key"], payload["release_key"])

    def test_public_command_rejects_invalid_candidate(self) -> None:
        bad = self.root / "bad"
        bad.mkdir()
        completed = subprocess.run(
            ["bash", str(DATABASE_DIR / "kane-boundary-candidate.sh"), "validate", str(bad)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, completed.returncode)
        self.assertIn("ERROR:", completed.stderr)


if __name__ == "__main__":
    unittest.main()
