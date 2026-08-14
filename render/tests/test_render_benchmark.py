#!/usr/bin/env python3
"""Regression tests for Batch 025 render-container benchmark."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDER_DIR = ROOT / "render"
MODULE_PATH = RENDER_DIR / "tools" / "kane_render_benchmark.py"
SEED_TEST_PATH = ROOT / "database" / "tests" / "test_seed_import.py"
WRAPPER = RENDER_DIR / "kane-render-benchmark.sh"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BENCH = load_module("_kane_render_benchmark_test", MODULE_PATH)
SEED_TEST = load_module("_kane_render_seed_fixture", SEED_TEST_PATH)


class RenderBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.seed_fixture = SEED_TEST.SeedImportTests(
            "test_import_creates_clean_valid_seed_and_audit"
        )
        self.seed_fixture.setUp()
        SEED_TEST.seed_import.import_seed(
            self.seed_fixture.donor,
            self.seed_fixture.output,
            self.seed_fixture.audit,
            self.seed_fixture.contract,
        )
        self.database = self.seed_fixture.output
        self.staging = self.root / "canonical.sqlite"
        self.output = self.root / "candidates"
        self.staging_info = BENCH.prepare_canonical_staging(self.database, self.staging)

    def tearDown(self) -> None:
        self.seed_fixture.tearDown()
        self.temp.cleanup()

    def build(self, chunk_size: int = 2):
        return BENCH.build_candidates(self.staging, self.output, chunk_size)

    def test_protocol_is_fixed_and_non_scored(self) -> None:
        protocol = BENCH.protocol_summary()
        self.assertEqual(BENCH.SSOT_COMMIT, protocol["accepted_ssot"])
        self.assertEqual([256, 512, 2048], protocol["chunk_sizes_records"])
        self.assertIn("No weighted composite score", protocol["scoring_rule"])
        self.assertEqual("warm_startup_index_open_ms", protocol["startup_metric"])

    def test_exact_five_accepted_dataset_identities(self) -> None:
        releases = BENCH.accepted_release_identity(self.database)
        self.assertEqual(
            list(BENCH.EXPECTED_DATASET_KEYS),
            [release["dataset_key"] for release in releases],
        )
        self.assertEqual(5, len(releases))

    def test_substituted_accepted_dataset_is_rejected(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("UPDATE dataset SET dataset_key = 'roads-substitute' WHERE dataset_key = 'roads'")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "Accepted dataset identity mismatch"):
            BENCH.accepted_release_identity(self.database)

    def test_established_milestone_two_validators_are_reused(self) -> None:
        result = BENCH.validate_authoritative_database(self.database)
        self.assertTrue(result["all_passed"])
        self.assertEqual(
            [
                "database",
                "provenance",
                "boundary",
                "map_layers",
                "buildings",
                "project_buildings",
                "classifications",
            ],
            result["validators"],
        )

    def test_canonical_staging_contains_complete_project_building_mapping(self) -> None:
        self.assertEqual(7, self.staging_info["record_count"])
        connection = sqlite3.connect(self.staging)
        rows = connection.execute(
            "SELECT building_key FROM record WHERE dataset_key = 'buildings' ORDER BY record_id"
        ).fetchall()
        connection.close()
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row[0].startswith("kcb-") for row in rows))

    def test_canonical_staging_generation_is_deterministic(self) -> None:
        second = self.root / "canonical-second.sqlite"
        second_info = BENCH.prepare_canonical_staging(self.database, second)
        self.assertEqual(self.staging_info["record_count"], second_info["record_count"])
        self.assertEqual(BENCH.sha256_file(self.staging), BENCH.sha256_file(second))

    def test_all_three_candidates_use_complete_record_count(self) -> None:
        paths = self.build()
        for name, path in paths.items():
            reader = BENCH.open_reader(name, path)
            try:
                self.assertEqual(7, reader.record_count)
                self.assertEqual(7, sum(chunk.record_count for chunk in reader.chunks))
            finally:
                reader.close()

    def test_chunk_payloads_are_identical_across_candidates(self) -> None:
        paths = self.build()
        readers = {name: BENCH.open_reader(name, path) for name, path in paths.items()}
        try:
            for chunk_index in range(len(readers["directory"].chunks)):
                payloads = []
                for name in BENCH.CANDIDATE_FORMATS:
                    chunk = readers[name].chunks[chunk_index]
                    payloads.append(readers[name].read_payload(chunk))
                self.assertEqual(payloads[0], payloads[1])
                self.assertEqual(payloads[1], payloads[2])
        finally:
            for reader in readers.values():
                reader.close()

    def test_complete_viewport_retrieval_matches_canonical_staging(self) -> None:
        paths = self.build()
        bounds = [-88.51, 41.89, -88.46, 41.92]
        expected = BENCH.canonical_viewport_ids(self.staging, bounds)
        self.assertGreater(len(expected), 0)
        for name, path in paths.items():
            reader = BENCH.open_reader(name, path)
            try:
                records, stats = reader.viewport(bounds)
                self.assertEqual(expected, [record["record_id"] for record in records])
                self.assertGreater(stats["chunks_read"], 0)
            finally:
                reader.close()

    def test_viewport_reads_have_no_chunk_cap(self) -> None:
        paths = self.build(chunk_size=2)
        bounds = self.staging_info["county_bounds"]
        expected = BENCH.canonical_viewport_ids(self.staging, bounds)
        reader = BENCH.open_reader("directory", paths["directory"])
        try:
            records, stats = reader.viewport(bounds)
            self.assertEqual(expected, [record["record_id"] for record in records])
            self.assertEqual(len(reader.chunks), stats["chunks_read"])
            self.assertGreater(stats["chunks_read"], 1)
        finally:
            reader.close()

    def test_cross_candidate_viewport_result_sets_are_exactly_equal(self) -> None:
        paths = self.build()
        probes = BENCH.derive_viewports(self.staging, self.staging_info["county_bounds"])
        results = BENCH.benchmark_viewports(self.staging, paths, probes)
        for probe_index in range(len(probes)):
            hashes = {
                results[name][probe_index]["result_sha256"]
                for name in BENCH.CANDIDATE_FORMATS
            }
            self.assertEqual(1, len(hashes))

    def test_chunk_size_sensitivity_preserves_viewport_results(self) -> None:
        bounds = self.staging_info["county_bounds"]
        expected = BENCH.canonical_viewport_ids(self.staging, bounds)
        for chunk_size in (2, 3, 5):
            paths = BENCH.build_candidates(self.staging, self.root / f"out-{chunk_size}", chunk_size)
            for name, path in paths.items():
                reader = BENCH.open_reader(name, path)
                try:
                    records, _ = reader.viewport(bounds)
                    self.assertEqual(expected, [record["record_id"] for record in records])
                finally:
                    reader.close()

    def test_directory_payload_tamper_is_rejected(self) -> None:
        paths = self.build()
        chunk = sorted((paths["directory"] / "chunks").glob("*.bin"))[0]
        data = bytearray(chunk.read_bytes())
        data[-1] ^= 0x01
        chunk.write_bytes(data)
        reader = BENCH.open_reader("directory", paths["directory"])
        try:
            with self.assertRaisesRegex(RuntimeError, "payload integrity failure"):
                reader.viewport(self.staging_info["county_bounds"])
        finally:
            reader.close()

    def test_sqlite_payload_tamper_is_rejected(self) -> None:
        paths = self.build()
        connection = sqlite3.connect(paths["sqlite"])
        payload = bytearray(connection.execute("SELECT payload FROM chunk WHERE chunk_id = 0").fetchone()[0])
        payload[-1] ^= 0x01
        connection.execute("UPDATE chunk SET payload = ? WHERE chunk_id = 0", (bytes(payload),))
        connection.commit()
        connection.close()
        reader = BENCH.open_reader("sqlite", paths["sqlite"])
        try:
            with self.assertRaisesRegex(RuntimeError, "payload integrity failure"):
                reader.viewport(self.staging_info["county_bounds"])
        finally:
            reader.close()

    def test_flat_payload_tamper_is_rejected(self) -> None:
        paths = self.build()
        data = bytearray(paths["flat"].read_bytes())
        data[-1] ^= 0x01
        paths["flat"].write_bytes(data)
        reader = BENCH.open_reader("flat", paths["flat"])
        try:
            with self.assertRaisesRegex(RuntimeError, "payload integrity failure"):
                reader.viewport(self.staging_info["county_bounds"])
        finally:
            reader.close()

    def test_truncated_flat_index_is_rejected(self) -> None:
        paths = self.build()
        data = paths["flat"].read_bytes()
        truncated = self.root / "truncated.krf"
        truncated.write_bytes(data[: len(BENCH.FLAT_MAGIC) + 10])
        with self.assertRaisesRegex(RuntimeError, "index is truncated|payload is truncated|index length"):
            BENCH.FlatReader(truncated)

    def test_malformed_flat_offsets_are_rejected(self) -> None:
        paths = self.build(chunk_size=2)
        data = paths["flat"].read_bytes()
        prefix = len(BENCH.FLAT_MAGIC)
        index_length = struct.unpack(">Q", data[prefix:prefix + 8])[0]
        index_start = prefix + 8
        index = json.loads(data[index_start:index_start + index_length])
        self.assertGreater(len(index["chunks"]), 1)
        index["chunks"][1]["flat_offset"] += 1
        new_index = BENCH.canonical_bytes(index)
        payload = data[index_start + index_length:]
        broken = self.root / "malformed.krf"
        broken.write_bytes(BENCH.FLAT_MAGIC + struct.pack(">Q", len(new_index)) + new_index + payload)
        with self.assertRaisesRegex(RuntimeError, "offsets are malformed"):
            BENCH.FlatReader(broken)

    def test_candidate_generation_is_byte_deterministic(self) -> None:
        first = BENCH.build_candidates(self.staging, self.root / "first", 2)
        second = BENCH.build_candidates(self.staging, self.root / "second", 2)
        for name in BENCH.CANDIDATE_FORMATS:
            self.assertEqual(
                BENCH.artifact_sha256(first[name]),
                BENCH.artifact_sha256(second[name]),
                name,
            )

    def test_point_in_polygon_handles_inside_outside_and_hole(self) -> None:
        polygon = [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
        ]
        self.assertTrue(BENCH.point_in_polygon((1, 1), polygon))
        self.assertFalse(BENCH.point_in_polygon((5, 5), polygon))
        self.assertFalse(BENCH.point_in_polygon((20, 20), polygon))
        self.assertTrue(BENCH.point_in_polygon((0, 0), polygon))

    def test_exact_hit_test_identity_matches_all_candidates(self) -> None:
        paths = self.build()
        samples = BENCH.sample_hit_points(self.staging, 2)
        for sample in samples:
            point = tuple(sample["point"])
            expected = BENCH.canonical_hit_test(self.staging, point)
            self.assertIn(sample["building_key"], expected)
            for name, path in paths.items():
                reader = BENCH.open_reader(name, path)
                try:
                    keys, _ = reader.hit_test(point)
                    self.assertEqual(expected, keys)
                finally:
                    reader.close()

    def test_hit_test_benchmark_records_functional_probe_semantics(self) -> None:
        paths = self.build()
        samples = BENCH.sample_hit_points(self.staging, 2)
        result = BENCH.benchmark_hit_tests(self.staging, paths, samples)
        self.assertEqual(2, result["sample_count"])
        self.assertIn("descriptive only", result["interpretation"])
        self.assertEqual(set(BENCH.CANDIDATE_FORMATS), set(result["summary"]))

    def test_classification_overlay_changes_colors_not_base_artifacts(self) -> None:
        paths = self.build()
        samples = BENCH.sample_hit_points(self.staging, 2)
        result = BENCH.classification_independence(paths, samples)
        self.assertFalse(result["classification_values_embedded_in_base"])
        for name in BENCH.CANDIDATE_FORMATS:
            evidence = result["format_results"][name]
            self.assertTrue(evidence["unchanged"])
            self.assertTrue(evidence["resolved_outputs_differ"])
            self.assertEqual(
                evidence["base_artifact_sha256_before"],
                evidence["base_artifact_sha256_after"],
            )

    def test_viewport_protocol_covers_seven_deterministic_regimes(self) -> None:
        first = BENCH.derive_viewports(self.staging, self.staging_info["county_bounds"])
        second = BENCH.derive_viewports(self.staging, self.staging_info["county_bounds"])
        self.assertEqual(first, second)
        self.assertEqual(
            [
                "county-overview",
                "dense-buildings",
                "medium-buildings",
                "sparse-buildings",
                "road-heavy",
                "water-heavy",
                "editing-scale-building",
            ],
            [probe["name"] for probe in first],
        )

    def test_hit_test_sampling_is_deterministic_and_bounded(self) -> None:
        first = BENCH.sample_hit_points(self.staging, 128)
        second = BENCH.sample_hit_points(self.staging, 128)
        self.assertEqual(first, second)
        self.assertEqual(2, len(first))
        self.assertEqual(2, len({sample["building_key"] for sample in first}))

    def test_artifact_replacement_evidence_is_objective(self) -> None:
        paths = self.build(chunk_size=2)
        evidence = BENCH.candidate_evidence(paths)
        self.assertGreater(evidence["directory"]["artifact_file_count"], 1)
        self.assertEqual(1, evidence["sqlite"]["artifact_file_count"])
        self.assertEqual(1, evidence["flat"]["artifact_file_count"])
        for name in BENCH.CANDIDATE_FORMATS:
            self.assertEqual(
                evidence[name]["artifact_file_count"],
                evidence[name]["replacement_unit_count"],
            )

    def test_compatibility_matrix_is_non_scored(self) -> None:
        matrix = BENCH.compatibility_matrix()
        self.assertEqual(set(BENCH.CANDIDATE_FORMATS), set(matrix))
        for row in matrix.values():
            self.assertIn("windows", row)
            self.assertIn("ubuntu", row)
            self.assertIn("runtime_dependency", row)
            self.assertNotIn("score", row)

    def test_storage_environment_records_development_context_filesystem_and_device(self) -> None:
        environment = BENCH.storage_environment(self.root / "workspace")
        self.assertEqual("development-orchestrator", environment["measurement_context"])
        self.assertEqual(
            "deferred-until-application-complete",
            environment["deployment_validation_status"],
        )
        self.assertIn(":", environment["device_major_minor"])
        self.assertFalse(environment["cold_start_measured"])
        self.assertIn("warm-cache", environment["cache_policy"])

    def test_warm_startup_benchmark_is_interleaved_for_all_candidates(self) -> None:
        paths = self.build()
        result = BENCH.benchmark_startup(paths)
        for name in BENCH.CANDIDATE_FORMATS:
            self.assertEqual(BENCH.STARTUP_REPETITIONS, len(result[name]["samples_ms"]))
            self.assertGreaterEqual(result[name]["median_ms"], 0.0)

    def test_full_measurement_writes_one_canonical_report_and_external_checksum(self) -> None:
        workspace = self.root / "measurement"
        result = BENCH.run_measurement(self.database, workspace)
        report_path = Path(result["report_file"])
        checksum_path = Path(result["checksum_file"])
        self.assertTrue(report_path.is_file())
        self.assertTrue(checksum_path.is_file())
        self.assertEqual(BENCH.sha256_file(report_path), result["report_sha256"])
        self.assertEqual(
            f"{result['report_sha256']}  benchmark-report.json\n",
            checksum_path.read_text(encoding="utf-8"),
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual("not-selected", report["selection_status"])
        self.assertEqual(
            "development-orchestrator",
            report["storage_environment"]["measurement_context"],
        )
        self.assertEqual(
            "deferred-until-application-complete",
            report["storage_environment"]["deployment_validation_status"],
        )
        self.assertEqual({"256", "512", "2048"}, set(report["chunk_size_results"]))
        self.assertNotIn("report_sha256", report)

    def test_protocol_defers_physical_deployment_until_application_complete(self) -> None:
        protocol = BENCH.protocol_summary()
        self.assertIn("Physical deployment validation is deferred", protocol["scoring_rule"])
        parser_help = subprocess.run(
            [sys.executable, str(MODULE_PATH), "measure", "--help"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("storage-role", parser_help)
        self.assertNotIn("intended-usb", parser_help)

    def test_written_decision_selects_flat_container_without_freezing_chunk_size(self) -> None:
        decision = (ROOT / "docs" / "RENDER_FORMAT_DECISION.md").read_text(encoding="utf-8")
        self.assertIn("single flat-file render container", decision)
        self.assertIn("cf1f07a1972c2bcdb750d306a98b567f2cd3483144cded8e60e630eca1c16817", decision)
        self.assertIn("does not freeze a production chunk size", decision)
        self.assertIn("deferred until application completion", decision)

    def test_protocol_cli_prints_fixed_protocol(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "protocol"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(BENCH.PROTOCOL_VERSION, payload["protocol_version"])

    def test_shell_entry_point_runs_protocol_command(self) -> None:
        completed = subprocess.run(
            [str(WRAPPER), "protocol"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(BENCH.SSOT_COMMIT, payload["accepted_ssot"])


if __name__ == "__main__":
    unittest.main()
