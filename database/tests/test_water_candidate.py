#!/usr/bin/env python3
"""Tests for the Batch 020 coordinated water candidate harvest."""

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
MODULE_PATH = TOOLS_DIR / "kane_water_candidate.py"
WRAPPER = DATABASE_DIR / "kane-water-candidate.sh"
ROOT = DATABASE_DIR.parent


def load_module():
    spec = importlib.util.spec_from_file_location("_kane_water_candidate_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load water-candidate module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CANDIDATE = load_module()


class FakeWaterArcGIS:
    def __init__(self) -> None:
        self.profiles, _ = CANDIDATE.load_water_profiles()
        self.object_ids = {
            "water-creeks": [3, 1, 2],
            "water-fox-river": [1],
        }
        self.max_record_count = 2
        self.metadata_overrides: dict[str, dict[str, Any]] = {}
        self.feature_overrides: dict[tuple[str, int], dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.inventory_call_count: dict[str, int] = {key: 0 for key in CANDIDATE.DATASET_ORDER}

    def dataset_for_url(self, url: str) -> str:
        for key, profile in self.profiles.items():
            if url.startswith(profile["source"]["layer_url"]):
                return key
        raise AssertionError(f"Unexpected URL {url}")

    def metadata(self, dataset_key: str) -> dict[str, Any]:
        profile = self.profiles[dataset_key]
        edit_ms = 1752788728127 if dataset_key == "water-creeks" else 1752785113777
        value: dict[str, Any] = {
            "type": "Feature Layer",
            "name": dataset_key,
            "geometryType": profile["geometry"]["arcgis_type"],
            "supportedQueryFormats": "JSON, geoJSON",
            "objectIdField": "OBJECTID",
            "fields": [{"name": name} for name in profile["query"]["out_fields"]],
            "maxRecordCount": self.max_record_count,
            "editingInfo": {
                "lastEditDate": edit_ms,
                "schemaLastEditDate": edit_ms,
                "dataLastEditDate": edit_ms,
            },
        }
        value.update(self.metadata_overrides.get(dataset_key, {}))
        return value

    def feature(self, dataset_key: str, object_id: int) -> dict[str, Any]:
        if dataset_key == "water-creeks":
            x = -88.0 + object_id * 0.01
            y = 41.0 + object_id * 0.01
            geometry: dict[str, Any] | None = {
                "type": "LineString",
                "coordinates": [[x, y], [x + 0.002, y + 0.001]],
            }
        else:
            geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [-88.0, 41.0], [-87.9, 41.0], [-87.9, 41.1], [-88.0, 41.0]
                ]],
            }
        feature: dict[str, Any] = {
            "type": "Feature",
            "properties": {"OBJECTID": object_id},
            "geometry": geometry,
        }
        override = self.feature_overrides.get((dataset_key, object_id))
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
        dataset_key = self.dataset_for_url(url)
        self.calls.append({"dataset_key": dataset_key, "url": url, "params": dict(params), "post": post})
        if not url.endswith("/query"):
            return self.metadata(dataset_key)
        if params.get("returnIdsOnly") == "true":
            self.inventory_call_count[dataset_key] += 1
            return {"objectIdFieldName": "OBJECTID", "objectIds": list(self.object_ids[dataset_key])}
        requested = [int(value) for value in params["objectIds"].split(",")]
        return {
            "type": "FeatureCollection",
            "features": [self.feature(dataset_key, value) for value in reversed(requested)],
        }


class WaterCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.staging = self.root / "staging"
        self.fake = FakeWaterArcGIS()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def harvest(self, requester=None) -> dict[str, Any]:
        return CANDIDATE.harvest_candidate(
            self.staging,
            requester=requester or self.fake,
            started_at="2026-08-11T13:00:00.000Z",
            completed_at="2026-08-11T13:01:00.000Z",
        )

    def candidate_dir(self) -> Path:
        return Path(self.harvest()["candidate_directory"])

    def create_accepted_database(self) -> Path:
        database = self.root / "kane-condo.gpkg"
        CANDIDATE.kane_map_layers.kane_db.initialize_database(database)
        profiles, _ = CANDIDATE.load_water_profiles()
        for dataset_key in CANDIDATE.DATASET_ORDER:
            slug = "creeks" if dataset_key == "water-creeks" else "fox-river"
            source = self.root / f"accepted-{slug}.geojson"
            feature = self.fake.feature(dataset_key, 1)
            document = {"type": "FeatureCollection", "features": [feature]}
            raw = CANDIDATE.canonical_bytes(document)
            source.write_bytes(raw)
            descriptor = {
                "county": {
                    "county_key": "kane-county-il", "name": "Kane County", "state_code": "IL",
                    "country_code": "US", "fips_code": "17089",
                },
                "agency": {
                    "agency_key": "kane-county-gis", "name": "Kane County GIS",
                    "jurisdiction": "Kane County, Illinois", "homepage_uri": None,
                },
                "dataset": {
                    "dataset_key": dataset_key, "name": f"Fixture {dataset_key}",
                    "description": "Fixture", "data_kind": "water",
                    "source_uri": profiles[dataset_key]["source"]["layer_url"],
                },
                "harvest": {
                    "harvest_key": f"{slug}-accepted-harvest", "started_at": "2025-07-17T12:00:00.000Z",
                    "completed_at": "2025-07-17T12:01:00.000Z", "status": "succeeded",
                    "source_metadata": {"id_property": "OBJECTID", "object_id_field": "OBJECTID"}, "object_count": 1,
                },
                "files": [{
                    "file_role": "source", "relative_path": f"accepted/{source.name}",
                    "byte_length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "media_type": "application/geo+json",
                }],
                "release": {
                    "release_key": f"{slug}-accepted-release", "lifecycle_status": "accepted",
                    "source_published_at": "2025-07-17T12:00:00.000Z",
                    "content_sha256": hashlib.sha256(raw).hexdigest(), "feature_count": 1,
                    "metadata": {"id_property": "OBJECTID"}, "accepted_at": "2025-07-17T13:00:00.000Z",
                },
            }
            path = self.root / f"{slug}-descriptor.json"
            path.write_bytes(CANDIDATE.canonical_bytes(descriptor))
            CANDIDATE.kane_provenance.record_descriptor(database, path)
            CANDIDATE.kane_map_layers.import_map_layers(database, [(descriptor["release"]["release_key"], source)])
        self.assertEqual([], CANDIDATE.kane_map_layers.validate_database(database))
        return database

    def test_profiles_are_exact_coordinated_registry_members(self) -> None:
        profiles, registry_hash = CANDIDATE.load_water_profiles()
        self.assertEqual(set(CANDIDATE.DATASET_ORDER), set(profiles))
        self.assertTrue(all(p["update_group"] == "water-context" for p in profiles.values()))
        self.assertEqual("e95c9d0486f65035146cb0a2a9580e4148c853a78c4f9e44e2420f59ef654e12", registry_hash)

    def test_complete_harvest_creates_one_coordinated_directory(self) -> None:
        result = self.harvest()
        self.assertTrue(result["valid"])
        self.assertFalse(result["existing"])
        self.assertEqual("water-context", result["update_group"])
        candidate_dir = Path(result["candidate_directory"])
        self.assertEqual(CANDIDATE.REQUIRED_CANDIDATE_FILES, {p.name for p in candidate_dir.iterdir()})
        self.assertEqual(set(CANDIDATE.DATASET_ORDER), set(result["components"]))

    def test_harvest_orders_both_component_inventories(self) -> None:
        candidate_dir = self.candidate_dir()
        self.assertEqual([1, 2, 3], json.loads((candidate_dir / "creeks-object-ids.json").read_text()))
        self.assertEqual([1], json.loads((candidate_dir / "fox-river-object-ids.json").read_text()))

    def test_harvest_orders_creek_features_by_object_id(self) -> None:
        candidate_dir = self.candidate_dir()
        collection = json.loads((candidate_dir / "creeks.geojson").read_text())
        self.assertEqual([1, 2, 3], [f["properties"]["OBJECTID"] for f in collection["features"]])

    def test_harvest_preserves_polygonal_fox_river(self) -> None:
        candidate_dir = self.candidate_dir()
        collection = json.loads((candidate_dir / "fox-river.geojson").read_text())
        self.assertEqual("Polygon", collection["features"][0]["geometry"]["type"])

    def test_harvest_respects_service_max_record_count(self) -> None:
        self.harvest()
        creek_pages = [call for call in self.fake.calls if call["dataset_key"] == "water-creeks" and "objectIds" in call["params"]]
        self.assertEqual(["1,2", "3"], [call["params"]["objectIds"] for call in creek_pages])

    def test_harvest_rechecks_both_metadata_and_inventories(self) -> None:
        self.harvest()
        for key in CANDIDATE.DATASET_ORDER:
            metadata_calls = [call for call in self.fake.calls if call["dataset_key"] == key and not call["url"].endswith("/query")]
            self.assertEqual(2, len(metadata_calls))
            self.assertEqual(2, self.fake.inventory_call_count[key])

    def test_inventory_change_in_either_component_rejects_whole_group(self) -> None:
        original = self.fake.__call__
        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            dataset = self.fake.dataset_for_url(url)
            value = original(url, params, **kwargs)
            if dataset == "water-creeks" and params.get("returnIdsOnly") == "true" and self.fake.inventory_call_count[dataset] == 2:
                value["objectIds"] = [1, 2, 3, 4]
            return value
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "inventory changed"):
            self.harvest(requester)

    def test_metadata_change_in_either_component_rejects_whole_group(self) -> None:
        original = self.fake.__call__
        metadata_calls = 0
        def requester(url: str, params: Mapping[str, str], **kwargs: Any) -> Any:
            nonlocal metadata_calls
            dataset = self.fake.dataset_for_url(url)
            value = original(url, params, **kwargs)
            if dataset == "water-fox-river" and not url.endswith("/query"):
                metadata_calls += 1
                if metadata_calls == 2:
                    value = dict(value)
                    value["editingInfo"] = dict(value["editingInfo"])
                    value["editingInfo"]["dataLastEditDate"] += 1
            return value
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "metadata changed"):
            self.harvest(requester)

    def test_missing_geometry_in_creeks_rejects_group(self) -> None:
        feature = self.fake.feature("water-creeks", 1)
        feature["geometry"] = None
        self.fake.feature_overrides[("water-creeks", 1)] = feature
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "missing geometry"):
            self.harvest()

    def test_missing_geometry_in_fox_river_rejects_group(self) -> None:
        feature = self.fake.feature("water-fox-river", 1)
        feature["geometry"] = None
        self.fake.feature_overrides[("water-fox-river", 1)] = feature
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "missing geometry"):
            self.harvest()

    def test_polygon_creek_geometry_is_rejected(self) -> None:
        feature = self.fake.feature("water-creeks", 1)
        feature["geometry"] = self.fake.feature("water-fox-river", 1)["geometry"]
        self.fake.feature_overrides[("water-creeks", 1)] = feature
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "unsupported geometry"):
            self.harvest()

    def test_linestring_fox_geometry_is_rejected(self) -> None:
        feature = self.fake.feature("water-fox-river", 1)
        feature["geometry"] = self.fake.feature("water-creeks", 1)["geometry"]
        self.fake.feature_overrides[("water-fox-river", 1)] = feature
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "unsupported geometry"):
            self.harvest()

    def test_multiline_creek_geometry_is_preserved(self) -> None:
        feature = self.fake.feature("water-creeks", 1)
        feature["geometry"] = {"type": "MultiLineString", "coordinates": [[[-88,41],[-87.9,41.1]],[[-87.8,41.2],[-87.7,41.3]]]}
        self.fake.feature_overrides[("water-creeks", 1)] = feature
        collection = json.loads((self.candidate_dir() / "creeks.geojson").read_text())
        self.assertEqual("MultiLineString", collection["features"][0]["geometry"]["type"])

    def test_multipolygon_fox_geometry_is_preserved(self) -> None:
        feature = self.fake.feature("water-fox-river", 1)
        ring = [[-88,41],[-87.9,41],[-87.9,41.1],[-88,41]]
        feature["geometry"] = {"type": "MultiPolygon", "coordinates": [[ring]]}
        self.fake.feature_overrides[("water-fox-river", 1)] = feature
        collection = json.loads((self.candidate_dir() / "fox-river.geojson").read_text())
        self.assertEqual("MultiPolygon", collection["features"][0]["geometry"]["type"])

    def test_second_harvest_is_idempotent(self) -> None:
        first = self.harvest()
        second = self.harvest()
        self.assertTrue(second["existing"])
        self.assertEqual(first["group_key"], second["group_key"])

    def test_manifest_requires_both_components(self) -> None:
        candidate_dir = self.candidate_dir()
        path = candidate_dir / "manifest.json"
        manifest = json.loads(path.read_text())
        del manifest["components"]["water-creeks"]
        path.write_bytes(CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "both coordinated components"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_manifest_group_hash_tamper_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        path = candidate_dir / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["group_sha256"] = "0" * 64
        path.write_bytes(CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "group identity"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_component_source_tamper_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        path = candidate_dir / "creeks.geojson"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(RuntimeError, "canonical serialization"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_extra_candidate_file_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        (candidate_dir / "extra.txt").write_text("x")
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "file set mismatch"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_candidate_symlink_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        (candidate_dir / "link").symlink_to(candidate_dir / "manifest.json")
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "symlink"):
            CANDIDATE.validate_candidate(candidate_dir)

    def test_candidate_directory_symlink_is_rejected(self) -> None:
        candidate_dir = self.candidate_dir()
        link = self.root / "candidate-link"
        link.symlink_to(candidate_dir, target_is_directory=True)
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "must not be a symlink"):
            CANDIDATE.validate_candidate(link)

    def test_group_key_is_deterministic(self) -> None:
        first = self.harvest()
        second = CANDIDATE.validate_candidate(Path(first["candidate_directory"]))
        self.assertEqual(first["group_key"], second["group_key"])
        self.assertRegex(first["group_key"], r"^kane-water-context-candidate-20250717-[0-9a-f]{12}$")

    def test_registration_adds_both_candidates_atomically(self) -> None:
        database = self.create_accepted_database()
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        self.assertTrue(result["registered"])
        self.assertFalse(result["existing"])
        self.assertEqual(set(CANDIDATE.DATASET_ORDER), set(result["traces"]))
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute(
                "SELECT d.dataset_key, sr.lifecycle_status FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id WHERE d.dataset_key LIKE 'water-%' ORDER BY d.dataset_key, sr.lifecycle_status"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(4, len(rows))
        self.assertEqual(2, sum(1 for _, status in rows if status == "candidate"))
        self.assertEqual([], CANDIDATE.kane_map_layers.validate_database(database))

    def test_registration_preserves_accepted_water_releases_and_features(self) -> None:
        database = self.create_accepted_database()
        connection = sqlite3.connect(database)
        try:
            before_accepted = connection.execute(
                "SELECT d.dataset_key, sr.release_key, sr.content_sha256, sr.feature_count FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id WHERE d.dataset_key LIKE 'water-%' AND sr.lifecycle_status='accepted' ORDER BY d.dataset_key"
            ).fetchall()
            before_features = connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0]
        finally:
            connection.close()
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        self.assertTrue(result["accepted_releases_unchanged"])
        connection = sqlite3.connect(database)
        try:
            after_accepted = connection.execute(
                "SELECT d.dataset_key, sr.release_key, sr.content_sha256, sr.feature_count FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id WHERE d.dataset_key LIKE 'water-%' AND sr.lifecycle_status='accepted' ORDER BY d.dataset_key"
            ).fetchall()
            after_features = connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(before_accepted, after_accepted)
        self.assertEqual(before_features, after_features)

    def test_registration_metadata_links_companion_releases(self) -> None:
        database = self.create_accepted_database()
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        creek = result["traces"]["water-creeks"]["release"]
        fox = result["traces"]["water-fox-river"]["release"]
        self.assertEqual(fox["release_key"], creek["metadata"]["companion_release_key"])
        self.assertEqual(creek["release_key"], fox["metadata"]["companion_release_key"])
        self.assertEqual(result["group_key"], creek["metadata"]["water_group_key"])
        self.assertEqual(result["group_key"], fox["metadata"]["water_group_key"])

    def test_registration_is_idempotent_only_for_complete_group(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        first = CANDIDATE.register_candidate(database, candidate_dir)
        second = CANDIDATE.register_candidate(database, candidate_dir)
        self.assertFalse(first["existing"])
        self.assertTrue(second["existing"])

    def test_partial_existing_group_is_rejected(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        validated = CANDIDATE.validate_candidate(candidate_dir)
        profiles, _ = CANDIDATE.load_water_profiles()
        contexts = CANDIDATE._database_context(database, profiles)
        releases = {key: validated["components"][key]["release_key"] for key in CANDIDATE.DATASET_ORDER}
        descriptor = CANDIDATE._descriptor(candidate_dir, validated, contexts["water-creeks"], profiles["water-creeks"], releases["water-fox-river"])
        path = self.root / "partial.json"
        path.write_bytes(CANDIDATE.canonical_bytes(descriptor))
        CANDIDATE.kane_provenance.record_descriptor(database, path)
        with self.assertRaisesRegex(CANDIDATE.WaterCandidateError, "Partial or conflicting"):
            CANDIDATE.register_candidate(database, candidate_dir)

    def test_atomic_registration_rolls_back_when_second_release_conflicts(self) -> None:
        database = self.create_accepted_database()
        candidate_dir = self.candidate_dir()
        validated = CANDIDATE.validate_candidate(candidate_dir)
        # Pre-create only the Fox release key under unrelated provenance so the atomic insert fails.
        profiles, _ = CANDIDATE.load_water_profiles()
        contexts = CANDIDATE._database_context(database, profiles)
        releases = {key: validated["components"][key]["release_key"] for key in CANDIDATE.DATASET_ORDER}
        descriptor = CANDIDATE._descriptor(candidate_dir, validated, contexts["water-fox-river"], profiles["water-fox-river"], releases["water-creeks"])
        descriptor["release"]["metadata"]["water_group_key"] = "other-water-group"
        descriptor["harvest"]["source_metadata"]["water_group_key"] = "other-water-group"
        path = self.root / "conflict.json"
        path.write_bytes(CANDIDATE.canonical_bytes(descriptor))
        CANDIDATE.kane_provenance.record_descriptor(database, path)
        connection = sqlite3.connect(database)
        try:
            before = connection.execute(
                "SELECT COUNT(*) FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id WHERE d.dataset_key='water-creeks' AND sr.lifecycle_status='candidate'"
            ).fetchone()[0]
        finally:
            connection.close()
        with self.assertRaises((CANDIDATE.WaterCandidateError, RuntimeError)):
            CANDIDATE.register_candidate(database, candidate_dir)
        connection = sqlite3.connect(database)
        try:
            after = connection.execute(
                "SELECT COUNT(*) FROM source_release sr JOIN dataset d ON d.dataset_id=sr.dataset_id WHERE d.dataset_key='water-creeks' AND sr.lifecycle_status='candidate'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(before, after)

    def test_info_requires_complete_coordinated_group(self) -> None:
        database = self.create_accepted_database()
        result = CANDIDATE.register_candidate(database, self.candidate_dir())
        info = CANDIDATE.candidate_info(database, result["group_key"])
        self.assertEqual(set(CANDIDATE.DATASET_ORDER), set(info["candidates"]))

    def test_validate_cli_returns_json(self) -> None:
        candidate_dir = self.candidate_dir()
        completed = subprocess.run(
            ["bash", str(WRAPPER), "validate", str(candidate_dir)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["valid"])
        self.assertEqual("water-context", result["update_group"])

    def test_info_cli_returns_both_candidates(self) -> None:
        database = self.create_accepted_database()
        registered = CANDIDATE.register_candidate(database, self.candidate_dir())
        completed = subprocess.run(
            ["bash", str(WRAPPER), "info", str(database), registered["group_key"]],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(set(CANDIDATE.DATASET_ORDER), set(result["candidates"]))


if __name__ == "__main__":
    unittest.main()
