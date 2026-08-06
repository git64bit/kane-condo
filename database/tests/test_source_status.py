#!/usr/bin/env python3
"""Tests for the Batch 017 lightweight official-source status check."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any

DATABASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = DATABASE_DIR / "tools"
MODULE_PATH = TOOLS_DIR / "kane_source_status.py"
WRAPPER = DATABASE_DIR / "kane-source-status.sh"
PROFILE_DIR = DATABASE_DIR / "source-profiles"


def load_module():
    spec = importlib.util.spec_from_file_location("_kane_source_status_test", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load source-status module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


STATUS = load_module()


class Fixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "kane-condo.gpkg"
        self.registry = STATUS._load_registry(PROFILE_DIR)["registry"]
        self.metadata: dict[str, dict[str, Any]] = {}
        self.inventories: dict[str, list[int]] = {}
        self._create_database()
        for profile in self.registry["profiles"]:
            key = profile["profile_key"]
            self.metadata[key] = {
                "geometryType": profile["geometry"]["arcgis_type"],
                "objectIdField": profile["query"]["object_id_field"],
                "fields": [{"name": name} for name in profile["query"]["out_fields"]],
                "maxRecordCount": 2000,
                "editingInfo": {
                    "lastEditDate": 1000,
                    "schemaLastEditDate": 1000,
                    "dataLastEditDate": 1000,
                },
            }
            self.inventories[key] = (
                [1] if profile.get("expected_feature_count") == 1 else [1, 2, 3]
            )

    def close(self) -> None:
        self.temp.cleanup()

    def _create_database(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                """
                CREATE TABLE dataset (
                    dataset_id INTEGER PRIMARY KEY,
                    dataset_key TEXT NOT NULL UNIQUE
                );
                CREATE TABLE harvest_run (
                    harvest_run_id INTEGER PRIMARY KEY,
                    object_count INTEGER
                );
                CREATE TABLE source_release (
                    source_release_id INTEGER PRIMARY KEY,
                    release_key TEXT NOT NULL,
                    dataset_id INTEGER NOT NULL,
                    harvest_run_id INTEGER NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    source_published_at TEXT,
                    feature_count INTEGER NOT NULL
                );
                CREATE TABLE source_county_boundary (
                    source_release_id INTEGER NOT NULL,
                    source_feature_id TEXT NOT NULL,
                    source_ordinal INTEGER NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE TABLE source_building (
                    source_release_id INTEGER NOT NULL,
                    source_feature_id TEXT NOT NULL,
                    source_ordinal INTEGER NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE TABLE source_map_feature (
                    source_release_id INTEGER NOT NULL,
                    source_feature_id TEXT NOT NULL,
                    source_ordinal INTEGER NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                """
            )
            for index, profile in enumerate(self.registry["profiles"], start=1):
                dataset_key = profile["dataset_key"]
                connection.execute(
                    "INSERT INTO dataset(dataset_id, dataset_key) VALUES (?, ?)",
                    (index, dataset_key),
                )
                object_ids = (
                    (1,) if profile.get("expected_feature_count") == 1 else (1, 2, 3)
                )
                connection.execute(
                    "INSERT INTO harvest_run(harvest_run_id, object_count) VALUES (?, ?)",
                    (index, len(object_ids)),
                )
                connection.execute(
                    "INSERT INTO source_release(source_release_id, release_key, dataset_id, "
                    "harvest_run_id, lifecycle_status, source_published_at, feature_count) "
                    "VALUES (?, ?, ?, ?, 'accepted', '1970-01-01T00:00:01.000Z', ?)",
                    (index, f"release-{index}", index, index, len(object_ids)),
                )
                table = STATUS.DATASET_TABLES[dataset_key]
                for object_id in object_ids:
                    source_identity = (
                        f"fp-{object_id}"
                        if profile["query"]["identity_field"] == "FPId"
                        else str(object_id)
                    )
                    attributes = {"OBJECTID": object_id}
                    if profile["query"]["identity_field"] == "FPId":
                        attributes["FPId"] = source_identity
                    connection.execute(
                        f"INSERT INTO {table}(source_release_id, source_feature_id, "
                        "source_ordinal, attributes_json) VALUES (?, ?, ?, ?)",
                        (index, source_identity, object_id, json.dumps(attributes)),
                    )
            connection.commit()
        finally:
            connection.close()

    def profile_key_for_url(self, url: str) -> tuple[str, bool]:
        for profile in self.registry["profiles"]:
            layer_url = profile["source"]["layer_url"]
            if url.startswith(layer_url):
                return profile["profile_key"], "/query?" in url
        raise AssertionError(f"Unexpected URL: {url}")

    def fetcher(self, url: str, **_: Any) -> Any:
        key, inventory = self.profile_key_for_url(url)
        if inventory:
            return {"objectIdFieldName": "OBJECTID", "objectIds": self.inventories[key]}
        return self.metadata[key]


class SourceStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def check(self):
        return STATUS.check_sources(
            self.fixture.database,
            fetcher=self.fixture.fetcher,
            checked_at="2026-08-06T12:00:00.000Z",
        )

    def test_all_profiles_up_to_date(self) -> None:
        result = self.check()
        self.assertEqual(result["overall_status"], STATUS.STATUS_UP_TO_DATE)
        self.assertEqual(len(result["profiles"]), 5)
        self.assertTrue(all(item["label"] == "Up to date" for item in result["profiles"]))

    def test_registry_hash_is_batch_016_identity(self) -> None:
        result = self.check()
        self.assertEqual(
            result["registry_sha256"],
            "e95c9d0486f65035146cb0a2a9580e4148c853a78c4f9e44e2420f59ef654e12",
        )

    def test_larger_inventory_reports_new_source(self) -> None:
        key = "kane-county-building-footprints"
        self.fixture.inventories[key] = [1, 2, 3, 4]
        result = self.check()
        profile = next(item for item in result["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_NEW)
        self.assertIn("object count changed from 3 to 4", profile["change_reasons"])

    def test_fixed_boundary_count_change_is_unexpected(self) -> None:
        key = "kane-county-boundary"
        self.fixture.inventories[key] = [1, 2]
        result = self.check()
        profile = next(item for item in result["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)
        self.assertEqual(profile["error"], "fixed feature count changed from 1 to 2")

    def test_same_count_different_inventory_reports_new_source(self) -> None:
        key = self.fixture.registry["profiles"][1]["profile_key"]
        self.fixture.inventories[key] = [1, 2, 9]
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_NEW)
        self.assertIn("object-ID inventory changed", profile["change_reasons"])

    def test_advanced_data_edit_reports_new_source(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        editing = self.fixture.metadata[key]["editingInfo"]
        editing["lastEditDate"] = 2000
        editing["dataLastEditDate"] = 2000
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_NEW)
        self.assertEqual(profile["live_comparison_edit_origin"], "dataLastEditDate")
        self.assertIn("source last-edit timestamp advanced", profile["change_reasons"])

    def test_schema_only_edit_does_not_report_new_data(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        editing = self.fixture.metadata[key]["editingInfo"]
        editing["lastEditDate"] = 2000
        editing["schemaLastEditDate"] = 2000
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UP_TO_DATE)
        self.assertEqual(profile["live_comparison_edit_ms"], 1000)
        self.assertEqual(profile["live_comparison_edit_origin"], "dataLastEditDate")

    def test_last_edit_is_used_when_data_and_schema_timestamps_are_absent(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        editing = self.fixture.metadata[key]["editingInfo"]
        editing.pop("dataLastEditDate")
        editing.pop("schemaLastEditDate")
        editing["lastEditDate"] = 2000
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_NEW)
        self.assertEqual(profile["live_comparison_edit_origin"], "lastEditDate")

    def test_backward_data_edit_is_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        editing = self.fixture.metadata[key]["editingInfo"]
        editing["lastEditDate"] = 500
        editing["dataLastEditDate"] = 500
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)

    def test_malformed_edit_timestamp_is_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        self.fixture.metadata[key]["editingInfo"]["dataLastEditDate"] = "1000"
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)
        self.assertIn("dataLastEditDate", profile["error"])

    def test_geometry_drift_is_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        self.fixture.metadata[key]["geometryType"] = "esriGeometryPoint"
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["label"], "Source changed unexpectedly")

    def test_missing_requested_field_is_unexpected(self) -> None:
        profile_contract = self.fixture.registry["profiles"][1]
        key = profile_contract["profile_key"]
        missing = profile_contract["query"]["identity_field"]
        self.fixture.metadata[key]["fields"] = [
            item for item in self.fixture.metadata[key]["fields"] if item["name"] != missing
        ]
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)
        self.assertIn(missing, profile["error"])

    def test_object_id_field_drift_is_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        self.fixture.metadata[key]["objectIdField"] = "OID"
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)

    def test_duplicate_live_ids_are_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        self.fixture.inventories[key] = [1, 1, 2]
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)

    def test_noninteger_live_ids_are_unexpected(self) -> None:
        key = self.fixture.registry["profiles"][0]["profile_key"]
        self.fixture.inventories[key] = [1, "2", 3]
        profile = next(item for item in self.check()["profiles"] if item["profile_key"] == key)
        self.assertEqual(profile["status"], STATUS.STATUS_UNEXPECTED)

    def test_source_unavailable_is_reported(self) -> None:
        first_url = self.fixture.registry["profiles"][0]["source"]["layer_url"]

        def unavailable(url: str, **kwargs: Any) -> Any:
            if url.startswith(first_url):
                raise STATUS.SourceUnavailableError("timeout")
            return self.fixture.fetcher(url, **kwargs)

        result = STATUS.check_sources(
            self.fixture.database,
            fetcher=unavailable,
            checked_at="2026-08-06T12:00:00.000Z",
        )
        self.assertEqual(result["overall_status"], STATUS.STATUS_UNAVAILABLE)
        self.assertEqual(result["profiles"][0]["error"], "timeout")

    def test_unexpected_precedes_unavailable(self) -> None:
        self.assertEqual(
            STATUS.aggregate_status(
                [STATUS.STATUS_NEW, STATUS.STATUS_UNAVAILABLE, STATUS.STATUS_UNEXPECTED]
            ),
            STATUS.STATUS_UNEXPECTED,
        )

    def test_water_group_has_exact_members(self) -> None:
        group = self.check()["update_groups"]
        self.assertEqual(len(group), 1)
        self.assertEqual(group[0]["update_group"], "water-context")
        self.assertEqual(
            group[0]["members"],
            ["kane-county-creeks", "kane-county-fox-river"],
        )

    def test_water_group_reports_new_when_one_member_changes(self) -> None:
        self.fixture.inventories["kane-county-creeks"] = [1, 2, 3, 4]
        group = self.check()["update_groups"][0]
        self.assertEqual(group["status"], STATUS.STATUS_NEW)

    def test_database_is_not_modified(self) -> None:
        before = hashlib.sha256(self.fixture.database.read_bytes()).hexdigest()
        self.check()
        after = hashlib.sha256(self.fixture.database.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_missing_accepted_release_fails_local_check(self) -> None:
        connection = sqlite3.connect(self.fixture.database)
        try:
            connection.execute("DELETE FROM source_release WHERE source_release_id = 1")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(RuntimeError, "exactly one accepted release"):
            self.check()

    def test_retained_inventory_limitation_disables_digest_only(self) -> None:
        connection = sqlite3.connect(self.fixture.database)
        try:
            connection.execute("UPDATE harvest_run SET object_count = 4 WHERE harvest_run_id = 1")
            connection.commit()
        finally:
            connection.close()
        accepted = STATUS.load_accepted_state(
            self.fixture.database, self.fixture.registry
        )
        first_key = self.fixture.registry["profiles"][0]["profile_key"]
        self.assertIsNone(accepted[first_key]["accepted_object_id_sha256"])
        self.assertIsNotNone(accepted[first_key]["accepted_inventory_limitation"])

    def test_object_id_hash_is_order_sensitive_contract_after_normalization(self) -> None:
        normalized = STATUS.normalize_object_ids([3, 1, 2], "ids")
        self.assertEqual(normalized, [1, 2, 3])
        self.assertEqual(STATUS.object_id_sha256(normalized), STATUS.object_id_sha256([1, 2, 3]))

    def test_invalid_timeout_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timeout_seconds"):
            STATUS.check_sources(
                self.fixture.database,
                timeout_seconds=0,
                fetcher=self.fixture.fetcher,
            )

    def test_public_wrapper_help(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "--help"],
            cwd=DATABASE_DIR.parent,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("check", completed.stdout)

    def test_public_wrapper_reports_missing_database(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "check", str(self.fixture.root / "missing.gpkg")],
            cwd=DATABASE_DIR.parent,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Database does not exist", completed.stderr)

    def test_fetch_json_classifies_url_error_as_unavailable(self) -> None:
        def opener(*args: Any, **kwargs: Any):
            raise urllib.error.URLError("offline")

        with self.assertRaises(STATUS.SourceUnavailableError):
            STATUS.fetch_json(
                "https://example.invalid/source?f=json",
                timeout_seconds=1,
                byte_limit=100,
                opener=opener,
            )

    def test_validation_rejects_arcgis_error_object(self) -> None:
        profile = self.fixture.registry["profiles"][0]
        with self.assertRaises(STATUS.SourceUnexpectedError):
            STATUS.validate_layer_metadata(profile, {"error": {"code": 500}})


if __name__ == "__main__":
    unittest.main()
