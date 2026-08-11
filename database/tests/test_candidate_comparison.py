#!/usr/bin/env python3
"""Tests for Batch 022 deterministic candidate comparison."""

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
MODULE_PATH = TOOLS_DIR / "kane_candidate_compare.py"
WRAPPER = DATABASE_DIR / "kane-candidate-compare.sh"
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


COMPARE = load_module(MODULE_PATH, "_kane_candidate_compare_test")
BUILDING_SUPPORT = load_module(TESTS_DIR / "test_building_candidate.py", "_b022_building_support")
ROAD_SUPPORT = load_module(TESTS_DIR / "test_road_candidate.py", "_b022_road_support")
WATER_SUPPORT = load_module(TESTS_DIR / "test_water_candidate.py", "_b022_water_support")
BOUNDARY_SUPPORT = load_module(TESTS_DIR / "test_boundary_candidate.py", "_b022_boundary_support")


def start_case(module: Any, class_name: str, method: str):
    case = getattr(module, class_name)(method)
    case.setUp()
    return case


class CandidateComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.building_case = start_case(
            BUILDING_SUPPORT,
            "BuildingCandidateTests",
            "test_building_profile_is_exact_registry_profile",
        )
        cls.building_database = cls.building_case.create_accepted_database()
        cls.building_candidate = Path(cls.building_case.harvest()["candidate_directory"])
        BUILDING_SUPPORT.CANDIDATE.register_candidate(
            cls.building_database, cls.building_candidate
        )

        cls.road_case = start_case(
            ROAD_SUPPORT,
            "RoadCandidateTests",
            "test_complete_harvest_creates_valid_candidate",
        )
        cls.road_database = cls.road_case.create_accepted_database()
        cls.road_candidate = Path(cls.road_case.harvest()["candidate_directory"])
        ROAD_SUPPORT.CANDIDATE.register_candidate(cls.road_database, cls.road_candidate)

        cls.road_excluded_case = start_case(
            ROAD_SUPPORT,
            "RoadCandidateTests",
            "test_complete_harvest_creates_valid_candidate",
        )
        cls.road_excluded_database = cls.road_excluded_case.create_accepted_database()
        cls.road_excluded_case.fake.null_geometry_ids = {3}
        cls.road_excluded_candidate = Path(
            cls.road_excluded_case.harvest()["candidate_directory"]
        )
        ROAD_SUPPORT.CANDIDATE.register_candidate(
            cls.road_excluded_database, cls.road_excluded_candidate
        )

        cls.water_case = start_case(
            WATER_SUPPORT,
            "WaterCandidateTests",
            "test_complete_harvest_creates_one_coordinated_directory",
        )
        cls.water_database = cls.water_case.create_accepted_database()
        cls.water_candidate = Path(cls.water_case.harvest()["candidate_directory"])
        WATER_SUPPORT.CANDIDATE.register_candidate(cls.water_database, cls.water_candidate)

        cls.boundary_case = start_case(
            BOUNDARY_SUPPORT,
            "BoundaryCandidateTests",
            "test_profile_is_exact_boundary_registry_member",
        )
        cls.boundary_candidate = Path(cls.boundary_case.harvest()["candidate_directory"])
        BOUNDARY_SUPPORT.CANDIDATE.register_candidate(
            cls.boundary_case.database, cls.boundary_candidate
        )

    @classmethod
    def tearDownClass(cls) -> None:
        for name in (
            "boundary_case",
            "water_case",
            "road_excluded_case",
            "road_case",
            "building_case",
        ):
            getattr(cls, name).tearDown()

    def copy_database(self, source: Path) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        target = Path(temp.name) / source.name
        shutil.copy2(source, target)
        return temp, target

    def copy_candidate(self, source: Path) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        parent = Path(temp.name) / source.parent.name
        parent.mkdir()
        target = parent / source.name
        shutil.copytree(source, target)
        return temp, target

    def test_attribute_hash_normalizes_stable_identity_representation(self) -> None:
        accepted = COMPARE._comparison_attributes_hash(
            {"OBJECTID": 7, "FPId": 12345, "CommonName": "Building A"},
            "FPId",
            expected_identity="12345",
            label="accepted building",
        )
        candidate = COMPARE._comparison_attributes_hash(
            {"OBJECTID": 7, "FPId": "12345", "CommonName": "Building A"},
            "FPId",
            expected_identity="12345",
            label="candidate building",
        )
        self.assertEqual(accepted, candidate)

    def test_attribute_hash_preserves_business_attribute_changes(self) -> None:
        accepted = COMPARE._comparison_attributes_hash(
            {"OBJECTID": 7, "FPId": 12345, "CommonName": "Building A"},
            "FPId",
            expected_identity="12345",
            label="accepted building",
        )
        candidate = COMPARE._comparison_attributes_hash(
            {"OBJECTID": 7, "FPId": "12345", "CommonName": "Building B"},
            "FPId",
            expected_identity="12345",
            label="candidate building",
        )
        self.assertNotEqual(accepted, candidate)

    def test_feature_change_categories_are_exhaustive(self) -> None:
        accepted = {
            "a": ("g1", "a1"),
            "b": ("g2", "a2"),
            "c": ("g3", "a3"),
            "d": ("g4", "a4"),
            "e": ("g5", "a5"),
        }
        candidate = {
            "a": ("g1", "a1"),
            "b": ("G2", "a2"),
            "c": ("g3", "A3"),
            "d": ("G4", "A4"),
            "f": ("g6", "a6"),
        }
        result = COMPARE._feature_changes(accepted, candidate)
        self.assertEqual(["f"], result["added"]["identities"])
        self.assertEqual(["e"], result["removed"]["identities"])
        self.assertEqual(1, result["unchanged"]["count"])
        self.assertNotIn("identities", result["unchanged"])
        self.assertEqual(["b"], result["geometry_changed"]["identities"])
        self.assertEqual(["c"], result["attributes_changed"]["identities"])
        self.assertEqual(["d"], result["both_changed"]["identities"])

    def test_changed_category_identities_are_sorted(self) -> None:
        result = COMPARE._feature_changes({}, {"z": ("g", "a"), "a": ("g", "a")})
        self.assertEqual(["a", "z"], result["added"]["identities"])

    def test_identity_hash_is_independent_of_input_order(self) -> None:
        first = COMPARE._identity_bucket(["b", "a"], include_identities=True)
        second = COMPARE._identity_bucket(["a", "b"], include_identities=True)
        self.assertEqual(first, second)

    def test_empty_category_hash_is_deterministic(self) -> None:
        first = COMPARE._identity_bucket([], include_identities=True)
        second = COMPARE._identity_bucket([], include_identities=True)
        self.assertEqual(first, second)

    def test_inventory_comparison_reports_added_and_removed(self) -> None:
        accepted = {
            "count": 3,
            "object_ids_sha256": COMPARE.kane_source_status.object_id_sha256([1, 2, 4]),
            "object_ids": [1, 2, 4],
            "exact": True,
            "limitation": None,
        }
        result = COMPARE._inventory_comparison(accepted, [2, 3, 4])
        self.assertEqual([3], result["added"]["object_ids"])
        self.assertEqual([1], result["removed"]["object_ids"])
        self.assertTrue(result["exact_identity_diff_available"])

    def test_inventory_limitation_preserves_hash_and_count(self) -> None:
        accepted = {
            "count": 5,
            "object_ids_sha256": "a" * 64,
            "object_ids": None,
            "exact": False,
            "limitation": "accepted object-ID list is not reconstructable from database provenance",
        }
        result = COMPARE._inventory_comparison(accepted, [1, 2, 3])
        self.assertFalse(result["exact_identity_diff_available"])
        self.assertIsNone(result["added"])
        self.assertIsNone(result["removed"])
        self.assertEqual(5, result["accepted_count"])
        self.assertEqual("a" * 64, result["accepted_object_ids_sha256"])

    def test_building_comparison_reports_required_categories(self) -> None:
        result = COMPARE.compare_candidate(self.building_database, self.building_candidate)
        dataset = result["datasets"][0]
        self.assertEqual("buildings", dataset["dataset_key"])
        self.assertEqual("FPId", dataset["identity_field"])
        self.assertEqual(["fp-2", "fp-3"], dataset["feature_changes"]["added"]["identities"])
        self.assertEqual(1, dataset["feature_changes"]["unchanged"]["count"])
        for category in COMPARE.ALL_CATEGORIES:
            self.assertIn(category, dataset["feature_changes"])

    def test_building_source_inventory_uses_objectid(self) -> None:
        dataset = COMPARE.compare_candidate(
            self.building_database, self.building_candidate
        )["datasets"][0]
        self.assertEqual("OBJECTID", dataset["object_id_field"])
        self.assertEqual([2, 3], dataset["source_inventory"]["added"]["object_ids"])

    def test_road_comparison_reports_candidate_exclusion(self) -> None:
        dataset = COMPARE.compare_candidate(
            self.road_excluded_database, self.road_excluded_candidate
        )["datasets"][0]
        self.assertEqual([3], dataset["candidate_exclusions"]["object_ids"])
        self.assertEqual([2, 3], dataset["source_inventory"]["added"]["object_ids"])
        self.assertEqual(["2"], dataset["feature_changes"]["added"]["identities"])

    def test_road_comparison_reports_retained_additions(self) -> None:
        dataset = COMPARE.compare_candidate(self.road_database, self.road_candidate)["datasets"][0]
        self.assertEqual(["2", "3"], dataset["feature_changes"]["added"]["identities"])
        self.assertEqual(0, dataset["candidate_exclusions"]["count"])

    def test_water_comparison_contains_both_datasets_in_order(self) -> None:
        result = COMPARE.compare_candidate(self.water_database, self.water_candidate)
        self.assertEqual("official-water-context", result["candidate_kind"])
        self.assertEqual(
            ["water-creeks", "water-fox-river"],
            [item["dataset_key"] for item in result["datasets"]],
        )

    def test_water_creeks_report_added_features(self) -> None:
        result = COMPARE.compare_candidate(self.water_database, self.water_candidate)
        creeks = next(item for item in result["datasets"] if item["dataset_key"] == "water-creeks")
        self.assertEqual(["2", "3"], creeks["feature_changes"]["added"]["identities"])

    def test_water_fox_river_reports_unchanged(self) -> None:
        result = COMPARE.compare_candidate(self.water_database, self.water_candidate)
        fox = next(item for item in result["datasets"] if item["dataset_key"] == "water-fox-river")
        self.assertEqual(1, fox["feature_changes"]["unchanged"]["count"])
        self.assertEqual(0, fox["feature_changes"]["added"]["count"])

    def test_boundary_comparison_reports_unchanged(self) -> None:
        result = COMPARE.compare_candidate(
            self.boundary_case.database, self.boundary_candidate
        )
        dataset = result["datasets"][0]
        self.assertEqual("county-boundary", dataset["dataset_key"])
        self.assertEqual(1, dataset["feature_changes"]["unchanged"]["count"])
        self.assertEqual(
            0,
            sum(
                dataset["feature_changes"][key]["count"]
                for key in COMPARE.CHANGED_CATEGORIES
            ),
        )

    def test_comparison_is_repeatable(self) -> None:
        first = COMPARE.compare_candidate(self.building_database, self.building_candidate)
        second = COMPARE.compare_candidate(self.building_database, self.building_candidate)
        self.assertEqual(first, second)

    def test_comparison_hash_covers_deterministic_body(self) -> None:
        result = COMPARE.compare_candidate(self.building_database, self.building_candidate)
        body = {
            key: value
            for key, value in result.items()
            if key != "comparison_sha256"
        }
        self.assertEqual(COMPARE.sha256_value(body), result["comparison_sha256"])

    def test_report_contains_no_absolute_paths_or_timestamps(self) -> None:
        result = COMPARE.compare_candidate(self.building_database, self.building_candidate)
        text = json.dumps(result, sort_keys=True)
        self.assertNotIn(str(self.building_database), text)
        self.assertNotIn(str(self.building_candidate), text)
        self.assertNotIn("2026-", text)

    def test_compare_does_not_modify_database(self) -> None:
        before = hashlib.sha256(self.building_database.read_bytes()).hexdigest()
        COMPARE.compare_candidate(self.building_database, self.building_candidate)
        after = hashlib.sha256(self.building_database.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_unregistered_candidate_is_rejected(self) -> None:
        _, database = self.copy_database(self.building_database)
        connection = sqlite3.connect(database)
        try:
            connection.execute("DELETE FROM source_release WHERE lifecycle_status = 'candidate'")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(COMPARE.ComparisonError, "candidate release"):
            COMPARE.compare_candidate(database, self.building_candidate)

    def test_registered_content_hash_mismatch_is_rejected(self) -> None:
        _, database = self.copy_database(self.building_database)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE source_release SET content_sha256 = ? WHERE lifecycle_status = 'candidate'",
                ("0" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(COMPARE.ComparisonError, "content hash"):
            COMPARE.compare_candidate(database, self.building_candidate)

    def test_incomplete_accepted_inventory_without_hash_is_rejected(self) -> None:
        _, database = self.copy_database(self.road_database)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE harvest_run SET object_count = 2 WHERE harvest_run_id = ("
                "SELECT sr.harvest_run_id FROM source_release sr JOIN dataset d ON d.dataset_id = sr.dataset_id "
                "WHERE d.dataset_key = 'roads' AND sr.lifecycle_status = 'accepted')"
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(COMPARE.ComparisonError, "incomplete and has no preserved inventory hash"):
            COMPARE.compare_candidate(database, self.road_candidate)

    def test_tampered_candidate_is_rejected_before_comparison(self) -> None:
        _, candidate = self.copy_candidate(self.building_candidate)
        path = candidate / "buildings.geojson"
        path.write_bytes(path.read_bytes().replace(b"Building 1", b"Tampered 1"))
        with self.assertRaises(COMPARE.ComparisonError):
            COMPARE.compare_candidate(self.building_database, candidate)

    def test_candidate_symlink_is_rejected(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        link = Path(temp.name) / "candidate-link"
        link.symlink_to(self.building_candidate, target_is_directory=True)
        with self.assertRaisesRegex(COMPARE.ComparisonError, "symlink"):
            COMPARE.compare_candidate(self.building_database, link)

    def test_unknown_candidate_kind_is_rejected(self) -> None:
        _, candidate = self.copy_candidate(self.building_candidate)
        manifest_path = candidate / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["candidate_kind"] = "other"
        manifest_path.write_bytes(BUILDING_SUPPORT.CANDIDATE.canonical_bytes(manifest))
        with self.assertRaisesRegex(COMPARE.ComparisonError, "Unsupported candidate kind"):
            COMPARE.compare_candidate(self.building_database, candidate)

    def test_cli_outputs_valid_json(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                str(WRAPPER),
                "compare",
                str(self.building_database),
                str(self.building_candidate),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual("official-buildings", payload["candidate_kind"])

    def test_cli_output_is_repeatable(self) -> None:
        command = [
            "bash",
            str(WRAPPER),
            "compare",
            str(self.building_database),
            str(self.building_candidate),
        ]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_cli_failure_uses_stderr_and_exit_one(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "compare", "/missing/database.gpkg", "/missing/candidate"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(1, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("ERROR:", completed.stderr)

    def test_cli_usage_failure_is_argparse_exit_two(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), "compare"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, completed.returncode)


if __name__ == "__main__":
    unittest.main()
