#!/usr/bin/env python3
"""Tests for the offline Kane Condo official source-profile registry."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

DATABASE_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = DATABASE_DIR / "tools" / "kane_source_profiles.py"
PROFILE_DIR = DATABASE_DIR / "source-profiles"
WRAPPER = DATABASE_DIR / "kane-source-profiles.sh"

SPEC = importlib.util.spec_from_file_location("kane_source_profiles", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SOURCE_PROFILES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_PROFILES)

EXPECTED_HASH = "e95c9d0486f65035146cb0a2a9580e4148c853a78c4f9e44e2420f59ef654e12"


class SourceProfileRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = self.root / "source-profiles"
        shutil.copytree(PROFILE_DIR, self.registry)

    def load(self, filename: str) -> dict:
        return json.loads((self.registry / filename).read_text(encoding="utf-8"))

    def write(self, filename: str, value: dict) -> None:
        (self.registry / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def inspect(self) -> dict:
        return SOURCE_PROFILES.inspect_registry(self.registry)

    def errors(self) -> str:
        result = self.inspect()
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"], sorted(result["errors"]))
        return "\n".join(result["errors"])

    def run_cli(self, command: str, directory: Path | None = None) -> subprocess.CompletedProcess[str]:
        selected = directory or self.registry
        return subprocess.run(
            ["bash", str(WRAPPER), "--directory", str(selected), command],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_01_committed_registry_validates_with_expected_identity(self) -> None:
        result = SOURCE_PROFILES.inspect_registry(PROFILE_DIR)
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["profile_count"], 5)
        self.assertEqual(result["registry_sha256"], EXPECTED_HASH)

    def test_02_registry_identity_ignores_creation_and_enumeration_order(self) -> None:
        first = self.inspect()
        rebuilt = self.root / "rebuilt"
        rebuilt.mkdir()
        names = sorted((item.name for item in self.registry.iterdir()), reverse=True)
        for name in names:
            shutil.copy2(self.registry / name, rebuilt / name)
        real_iterdir = Path.iterdir

        def reversed_iterdir(path: Path):
            return iter(reversed(list(real_iterdir(path))))

        with mock.patch.object(Path, "iterdir", reversed_iterdir):
            second = SOURCE_PROFILES.inspect_registry(rebuilt)
        self.assertTrue(first["valid"] and second["valid"])
        self.assertEqual(first["registry_sha256"], second["registry_sha256"])
        self.assertEqual(first["registry"], second["registry"])

    def test_03_canonical_bytes_are_compact_utf8_without_newline(self) -> None:
        result = self.inspect()
        canonical = SOURCE_PROFILES.canonical_registry_bytes(result["registry"])
        self.assertTrue(canonical.startswith(b"{"))
        self.assertTrue(canonical.endswith(b"}"))
        self.assertFalse(canonical.endswith(b"}\n"))
        self.assertNotIn(b": ", canonical)
        self.assertEqual(canonical.decode("utf-8").encode("utf-8"), canonical)

    def test_04_validate_command_emits_structured_success(self) -> None:
        completed = self.run_cli("validate")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "errors": [],
                "profile_count": 5,
                "registry_sha256": EXPECTED_HASH,
                "valid": True,
            },
        )

    def test_05_info_command_reports_normalized_profile_order(self) -> None:
        completed = self.run_cli("info")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["registry_sha256"], EXPECTED_HASH)
        self.assertEqual(
            [profile["profile_key"] for profile in result["profiles"]],
            [
                "kane-county-boundary",
                "kane-county-building-footprints",
                "kane-county-creeks",
                "kane-county-fox-river",
                "kane-county-road-centerlines",
            ],
        )
        self.assertEqual(
            [profile["registry_filename"] for profile in result["profiles"]],
            [
                "kane-county-boundary.json",
                "kane-county-buildings.json",
                "kane-county-creeks.json",
                "kane-county-fox-river.json",
                "kane-county-roads.json",
            ],
        )

    def test_06_hash_command_emits_json_identity(self) -> None:
        completed = self.run_cli("hash")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {"registry_sha256": EXPECTED_HASH, "valid": True},
        )

    def test_07_malformed_json_returns_structured_validation_failure(self) -> None:
        (self.registry / "kane-county-roads.json").write_text("{", encoding="utf-8")
        completed = self.run_cli("validate")
        self.assertEqual(completed.returncode, 1)
        result = json.loads(completed.stdout)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["registry_sha256"])
        self.assertTrue(any("invalid JSON" in error for error in result["errors"]))

    def test_08_duplicate_object_keys_are_rejected_at_any_level(self) -> None:
        path = self.registry / "kane-county-boundary.json"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            '    "repository": "https://github.com/git64bit/kane-offline-map",',
            '    "repository": "https://github.com/git64bit/kane-offline-map",\n'
            '    "repository": "https://github.com/git64bit/kane-offline-map",',
        )
        path.write_text(text, encoding="utf-8")
        self.assertIn("duplicate object key", self.errors())

    def test_09_bom_invalid_utf8_empty_and_nonobject_documents_are_rejected(self) -> None:
        cases = (
            (b"\xef\xbb\xbf{}", "UTF-8 BOM"),
            (b"\xff", "invalid UTF-8"),
            (b"", "empty profile file"),
            (b"[]\n", "top-level JSON value must be an object"),
        )
        for index, (payload, expected) in enumerate(cases):
            with self.subTest(case=index):
                path = self.registry / "kane-county-roads.json"
                original = path.read_bytes()
                path.write_bytes(payload)
                self.assertIn(expected, self.errors())
                path.write_bytes(original)

    def test_10_null_nonfinite_and_wrong_primitive_types_are_rejected(self) -> None:
        filename = "kane-county-roads.json"
        original = (self.registry / filename).read_text(encoding="utf-8")
        cases = (
            (original.replace('"dataset_key": "roads"', '"dataset_key": null'), "null is not permitted"),
            (original.replace('"page_size": 2000', '"page_size": NaN'), "non-finite JSON number"),
            (original.replace('"out_srs": 4326', '"out_srs": true'), "must be an integer"),
        )
        for text, expected in cases:
            with self.subTest(expected=expected):
                (self.registry / filename).write_text(text, encoding="utf-8")
                self.assertIn(expected, self.errors())
                (self.registry / filename).write_text(original, encoding="utf-8")

    def test_11_empty_trimmed_strings_and_duplicate_array_entries_are_rejected(self) -> None:
        filename = "kane-county-buildings.json"
        profile = self.load(filename)
        profile["dataset_key"] = " buildings "
        profile["query"]["out_fields"].append("OBJECTID")
        self.write(filename, profile)
        errors = self.errors()
        self.assertIn("leading or trailing whitespace", errors)
        self.assertIn("duplicate array entry", errors)

    def test_12_unknown_keys_are_rejected_at_top_and_nested_levels(self) -> None:
        filename = "kane-county-boundary.json"
        profile = self.load(filename)
        profile["unknown"] = "value"
        profile["source"]["unknown"] = "value"
        self.write(filename, profile)
        errors = self.errors()
        self.assertIn("unknown key 'unknown'", errors)
        self.assertIn(f"{filename}.source", errors)

    def test_13_missing_and_additional_registry_files_are_rejected(self) -> None:
        (self.registry / "kane-county-roads.json").unlink()
        (self.registry / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        errors = self.errors()
        self.assertIn("missing required file: kane-county-roads.json", errors)
        self.assertIn("additional file: unexpected.txt", errors)

    def test_14_symlinks_and_subdirectories_are_rejected(self) -> None:
        target = self.registry / "kane-county-roads.json"
        target.unlink()
        os.symlink("kane-county-boundary.json", target)
        (self.registry / "nested").mkdir()
        errors = self.errors()
        self.assertIn("contains a symlink: kane-county-roads.json", errors)
        self.assertIn("contains a subdirectory: nested", errors)

    def test_15_duplicate_profile_dataset_donor_and_source_identities_are_rejected(self) -> None:
        roads = self.load("kane-county-roads.json")
        boundary = self.load("kane-county-boundary.json")
        roads["profile_key"] = boundary["profile_key"]
        roads["dataset_key"] = boundary["dataset_key"]
        roads["donor"]["path"] = boundary["donor"]["path"]
        roads["source"] = boundary["source"]
        self.write("kane-county-roads.json", roads)
        errors = self.errors()
        self.assertIn("duplicate profile_key", errors)
        self.assertIn("duplicate dataset_key", errors)
        self.assertIn("duplicate donor path", errors)
        self.assertIn("duplicate stable source-layer identifiers", errors)

    def test_16_insecure_or_malformed_endpoints_are_rejected(self) -> None:
        filename = "kane-county-boundary.json"
        original = self.load(filename)
        cases = (
            ("http://services1.arcgis.com/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/County_Boundary/FeatureServer/0", "must use HTTPS"),
            ("https://services1.arcgis.com:443/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/County_Boundary/FeatureServer/0", "must not declare a port"),
            ("https://services1.arcgis.com/oRKmdBXD6EbdmVgJ/ArcGIS/rest/services/County_Boundary/FeatureServer/0?x=1", "query or fragment"),
        )
        for url, expected in cases:
            with self.subTest(expected=expected):
                profile = json.loads(json.dumps(original))
                profile["source"]["layer_url"] = url
                self.write(filename, profile)
                self.assertIn(expected, self.errors())

    def test_17_endpoint_service_and_layer_must_roundtrip_exactly(self) -> None:
        filename = "kane-county-boundary.json"
        profile = self.load(filename)
        profile["source"]["service_name"] = "County%5FBoundary"
        profile["source"]["layer_id"] = True
        self.write(filename, profile)
        errors = self.errors()
        self.assertIn("must not be percent encoded", errors)
        self.assertIn("must be a nonnegative integer", errors)

    def test_18_wildcards_combined_fields_and_missing_identity_are_rejected(self) -> None:
        filename = "kane-county-buildings.json"
        profile = self.load(filename)
        profile["query"]["out_fields"] = ["OBJECTID,FPId", "*"]
        self.write(filename, profile)
        errors = self.errors()
        self.assertIn("wildcard field requests", errors)
        self.assertIn("comma-combined requested fields", errors)
        self.assertIn("identity_field is absent", errors)

    def test_19_geometry_and_donor_identity_must_match_approved_manifest(self) -> None:
        filename = "kane-county-roads.json"
        profile = self.load(filename)
        profile["geometry"]["arcgis_type"] = "esriGeometryPoint"
        profile["geometry"]["geojson_types"] = ["Point"]
        profile["donor"]["file_sha256"] = "0" * 64
        self.write(filename, profile)
        errors = self.errors()
        self.assertIn(f"{filename}.geometry", errors)
        self.assertIn(f"{filename}.donor", errors)

    def test_20_pagination_validation_and_optional_keys_are_exact(self) -> None:
        boundary = self.load("kane-county-boundary.json")
        boundary["pagination"]["ordering"] = "filesystem"
        boundary["validation"]["response"] = "anything"
        boundary["update_group"] = "water-context"
        self.write("kane-county-boundary.json", boundary)
        errors = self.errors()
        self.assertIn("pagination", errors)
        self.assertIn("validation", errors)
        self.assertIn("unapproved optional key 'update_group'", errors)

    def test_21_fox_river_and_creeks_require_one_coordinated_group(self) -> None:
        creeks = self.load("kane-county-creeks.json")
        creeks["update_group"] = "creeks-only"
        self.write("kane-county-creeks.json", creeks)
        errors = self.errors()
        self.assertIn(
            "Fox River and creeks must be the only water-context update-group members",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
