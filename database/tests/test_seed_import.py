"""Tests for the verified donor seed import and audit report."""

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

DATABASE_DIR = Path(__file__).resolve().parents[1]
ROOT = DATABASE_DIR.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


seed_import = load_module(
    "kane_seed_import_batch015", DATABASE_DIR / "tools" / "kane_seed_import.py"
)
geometry = load_module("kane_geometry_batch015", DATABASE_DIR / "tools" / "kane_geometry.py")


DONOR_SCHEMA = """
CREATE TABLE county (
    county_id INTEGER PRIMARY KEY,
    county_name TEXT NOT NULL,
    state_name TEXT NOT NULL,
    state_code TEXT NOT NULL,
    fips_code TEXT NOT NULL,
    canonical_srs_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE source_agency (
    agency_id INTEGER PRIMARY KEY,
    agency_key TEXT NOT NULL,
    agency_name TEXT NOT NULL,
    jurisdiction TEXT,
    homepage_uri TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE dataset (
    dataset_id INTEGER PRIMARY KEY,
    county_id INTEGER NOT NULL,
    agency_id INTEGER,
    dataset_key TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    feature_class TEXT NOT NULL,
    source_id_policy TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE source_release (
    release_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    release_key TEXT NOT NULL,
    source_version TEXT,
    source_published_at TEXT,
    harvested_at TEXT NOT NULL,
    accepted_at TEXT,
    source_uri TEXT,
    content_sha256 TEXT,
    status TEXT NOT NULL,
    notes TEXT NOT NULL
);
CREATE TABLE source_file (
    source_file_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    media_type TEXT,
    byte_length INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    preserved_at TEXT NOT NULL
);
CREATE TABLE harvest_run (
    run_id INTEGER PRIMARY KEY,
    dataset_id INTEGER NOT NULL,
    previous_release_id INTEGER,
    candidate_release_id INTEGER,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    error_message TEXT
);
CREATE TABLE source_county_boundary (
    source_boundary_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
    source_feature_id TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL,
    geometry BLOB NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_sha256 TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    attributes_sha256 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    min_x REAL NOT NULL,
    min_y REAL NOT NULL,
    max_x REAL NOT NULL,
    max_y REAL NOT NULL
);
CREATE TABLE source_map_feature (
    source_map_feature_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
    source_feature_id TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL,
    geometry BLOB NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_sha256 TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    attributes_sha256 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    min_x REAL NOT NULL,
    min_y REAL NOT NULL,
    max_x REAL NOT NULL,
    max_y REAL NOT NULL
);
CREATE TABLE source_building (
    source_building_id INTEGER PRIMARY KEY,
    release_id INTEGER NOT NULL,
    source_feature_id TEXT NOT NULL,
    source_ordinal INTEGER NOT NULL,
    geometry BLOB NOT NULL,
    geometry_type TEXT NOT NULL,
    geometry_sha256 TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    attributes_sha256 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    min_x REAL NOT NULL,
    min_y REAL NOT NULL,
    max_x REAL NOT NULL,
    max_y REAL NOT NULL
);
CREATE TABLE classification_release (id INTEGER);
CREATE TABLE classification_sector (id INTEGER);
CREATE TABLE classification_cell (id INTEGER);
CREATE TABLE classification_grid_calibration (id INTEGER);
CREATE TABLE building_cell_relation (id INTEGER);
CREATE TABLE classification_review (id INTEGER);
"""


class SeedImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.donor = self.root / "donor.gpkg"
        self.output = self.root / "kane-condo.gpkg"
        self.audit = self.root / "seed-audit.json"
        self.contract = self.root / "seed-contract.json"
        self.release_specs = self.create_donor()
        self.write_contract()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def canonical(value: object) -> str:
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    @staticmethod
    def digest(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def feature_values(
        self,
        source_id: str,
        id_property: str,
        geometry_type: str,
        coordinates,
        ordinal: int,
    ) -> tuple[object, ...]:
        blob, wkb, bounds = geometry.encode_geopackage_geometry(
            geometry_type, coordinates
        )
        attributes = self.canonical(
            {id_property: source_id, "NAME": f"Synthetic {source_id}"}
        )
        geometry_hash = self.digest(wkb)
        attributes_hash = self.digest(attributes.encode("utf-8"))
        content_hash = self.digest(
            self.canonical(
                {
                    "attributes_sha256": attributes_hash,
                    "geometry_sha256": geometry_hash,
                    "source_feature_id": source_id,
                }
            ).encode("utf-8")
        )
        return (
            source_id,
            ordinal,
            blob,
            geometry_type,
            geometry_hash,
            attributes,
            attributes_hash,
            content_hash,
            *bounds,
        )

    def create_donor(self) -> list[dict[str, object]]:
        connection = sqlite3.connect(self.donor)
        connection.executescript(DONOR_SCHEMA)
        timestamp = "2025-07-30T12:00:00.000Z"
        connection.execute(
            "INSERT INTO county VALUES (1, 'Kane County', 'Illinois', 'IL', '17089', 4326, ?)",
            (timestamp,),
        )
        connection.execute(
            "INSERT INTO source_agency VALUES "
            "(1, 'kane-county-gis', 'Kane County GIS', 'Kane County, Illinois', "
            "'https://www.kanecountyil.gov/', ?)",
            (timestamp,),
        )
        specs: list[dict[str, object]] = [
            {
                "dataset_key": "county-boundary",
                "release_key": "boundary-release-test",
                "data_kind": "boundary",
                "id_property": "OBJECTID",
                "content_sha256": "1" * 64,
                "features": [
                    self.feature_values(
                        "1",
                        "OBJECTID",
                        "Polygon",
                        [[
                            [-88.6, 41.7],
                            [-88.2, 41.7],
                            [-88.2, 42.2],
                            [-88.6, 42.2],
                            [-88.6, 41.7],
                        ]],
                        1,
                    )
                ],
            },
            {
                "dataset_key": "roads",
                "release_key": "roads-release-test",
                "data_kind": "roads",
                "id_property": "OBJECTID",
                "content_sha256": "2" * 64,
                "features": [
                    self.feature_values(
                        "10",
                        "OBJECTID",
                        "LineString",
                        [[-88.5, 41.8], [-88.3, 41.9]],
                        1,
                    ),
                    self.feature_values(
                        "11",
                        "OBJECTID",
                        "MultiLineString",
                        [[[-88.5, 42.0], [-88.4, 42.1]]],
                        2,
                    ),
                ],
            },
            {
                "dataset_key": "water-fox-river",
                "release_key": "river-release-test",
                "data_kind": "water",
                "id_property": "OBJECTID",
                "content_sha256": "3" * 64,
                "features": [
                    self.feature_values(
                        "20",
                        "OBJECTID",
                        "Polygon",
                        [[
                            [-88.4, 41.8],
                            [-88.39, 41.8],
                            [-88.39, 42.1],
                            [-88.4, 42.1],
                            [-88.4, 41.8],
                        ]],
                        1,
                    )
                ],
            },
            {
                "dataset_key": "water-creeks",
                "release_key": "creeks-release-test",
                "data_kind": "water",
                "id_property": "OBJECTID",
                "content_sha256": "4" * 64,
                "features": [
                    self.feature_values(
                        "30",
                        "OBJECTID",
                        "LineString",
                        [[-88.55, 41.85], [-88.35, 41.95]],
                        1,
                    )
                ],
            },
            {
                "dataset_key": "buildings",
                "release_key": "buildings-release-test",
                "data_kind": "buildings",
                "id_property": "FPId",
                "content_sha256": "5" * 64,
                "features": [
                    self.feature_values(
                        "B-1",
                        "FPId",
                        "Polygon",
                        [[
                            [-88.50, 41.90],
                            [-88.49, 41.90],
                            [-88.49, 41.91],
                            [-88.50, 41.91],
                            [-88.50, 41.90],
                        ]],
                        1,
                    ),
                    self.feature_values(
                        "B-2",
                        "FPId",
                        "Polygon",
                        [[
                            [-88.48, 41.90],
                            [-88.47, 41.90],
                            [-88.47, 41.91],
                            [-88.48, 41.91],
                            [-88.48, 41.90],
                        ]],
                        2,
                    ),
                ],
            },
        ]
        for dataset_id, spec in enumerate(specs, start=1):
            connection.execute(
                "INSERT INTO dataset VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    spec["dataset_key"],
                    str(spec["dataset_key"]).replace("-", " ").title(),
                    spec["data_kind"],
                    f"GeoJSON property {spec['id_property']}",
                    "Synthetic accepted seed data",
                    timestamp,
                ),
            )
            release_id = dataset_id
            connection.execute(
                "INSERT INTO source_release VALUES (?, ?, ?, 'v1', ?, ?, ?, ?, ?, "
                "'accepted', 'synthetic')",
                (
                    release_id,
                    dataset_id,
                    spec["release_key"],
                    timestamp,
                    timestamp,
                    timestamp,
                    f"https://example.invalid/{spec['dataset_key']}",
                    spec["content_sha256"],
                ),
            )
            source_hash = self.digest(str(spec["dataset_key"]).encode("utf-8"))
            connection.execute(
                "INSERT INTO source_file VALUES (?, ?, ?, 'application/geo+json', ?, ?, ?)",
                (
                    dataset_id * 10,
                    release_id,
                    f"{spec['dataset_key']}.geojson",
                    100 + dataset_id,
                    source_hash,
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO source_file VALUES (?, ?, ?, 'application/json', ?, ?, ?)",
                (
                    dataset_id * 10 + 1,
                    release_id,
                    f"{spec['dataset_key']}.geojson.manifest.json",
                    50 + dataset_id,
                    self.digest(f"manifest-{dataset_id}".encode("utf-8")),
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO harvest_run VALUES (?, ?, NULL, ?, ?, ?, 'accepted', "
                "'synthetic', NULL)",
                (dataset_id, dataset_id, release_id, timestamp, timestamp),
            )
            table = (
                "source_county_boundary"
                if spec["data_kind"] == "boundary"
                else "source_building"
                if spec["data_kind"] == "buildings"
                else "source_map_feature"
            )
            for values in spec["features"]:
                connection.execute(
                    f"INSERT INTO {table} (release_id, source_feature_id, source_ordinal, "
                    "geometry, geometry_type, geometry_sha256, attributes_json, "
                    "attributes_sha256, content_sha256, min_x, min_y, max_x, max_y) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (release_id, *values),
                )
        connection.commit()
        connection.close()
        return specs

    def write_contract(self) -> None:
        totals = {"boundary": 0, "roads": 0, "water": 0, "buildings": 0}
        releases = []
        for spec in self.release_specs:
            totals[str(spec["data_kind"])] += len(spec["features"])
            releases.append(
                {
                    key: spec[key]
                    for key in (
                        "dataset_key",
                        "release_key",
                        "data_kind",
                        "id_property",
                        "content_sha256",
                    )
                }
            )
        contract = {
            "contract_key": "synthetic-seed-test",
            "donor": {
                "byte_length": self.donor.stat().st_size,
                "sha256": self.digest(self.donor.read_bytes()),
                "source_commit": "synthetic-test",
            },
            "expected_releases": releases,
            "expected_totals": totals,
            "excluded_donor_tables": [
                "building_cell_relation",
                "classification_cell",
                "classification_grid_calibration",
                "classification_release",
                "classification_review",
                "classification_sector",
            ],
        }
        self.contract.write_text(json.dumps(contract), encoding="utf-8")

    def test_versioned_production_contract_matches_approved_seed_identity(self) -> None:
        contract = seed_import.validate_contract(
            seed_import.load_json_object(seed_import.DEFAULT_CONTRACT, "seed contract")
        )
        self.assertEqual("kane-offline-map-0911eeef", contract["contract_key"])
        self.assertEqual(324886528, contract["donor"]["byte_length"])
        self.assertEqual(
            "7fe2198b00b2d0dee9470eda3864b43b6f7b3b0ff3b236ce7c579ddc077f389a",
            contract["donor"]["sha256"],
        )
        self.assertEqual(
            {"boundary": 1, "roads": 27675, "water": 556, "buildings": 208324},
            contract["expected_totals"],
        )

    def test_import_creates_clean_valid_seed_and_audit(self) -> None:
        donor_before = self.digest(self.donor.read_bytes())
        result = seed_import.import_seed(
            self.donor, self.output, self.audit, self.contract
        )
        self.assertTrue(result["valid"])
        self.assertEqual(donor_before, self.digest(self.donor.read_bytes()))
        self.assertEqual([], seed_import.validate_target(self.output))
        self.assertTrue(self.audit.is_file())
        audit = json.loads(self.audit.read_text(encoding="utf-8"))
        self.assertEqual(2, audit["project_buildings"]["count"])
        self.assertEqual(2, audit["classifications"]["implicit_unclassified"])
        self.assertEqual(0, audit["classifications"]["current_rows"])
        self.assertEqual(0, audit["classifications"]["history_events"])
        self.assertEqual(
            self.digest(self.output.read_bytes()), audit["target_database"]["sha256"]
        )

    def test_import_preserves_geometry_counts_and_release_identity(self) -> None:
        seed_import.import_seed(self.donor, self.output, self.audit, self.contract)
        connection = sqlite3.connect(self.output)
        try:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM source_county_boundary").fetchone()[0])
            self.assertEqual(4, connection.execute("SELECT COUNT(*) FROM source_map_feature").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM source_building").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM project_building").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM project_building_source_mapping").fetchone()[0])
            self.assertEqual(
                sorted(spec["release_key"] for spec in self.release_specs),
                [row[0] for row in connection.execute("SELECT release_key FROM source_release ORDER BY release_key")],
            )
        finally:
            connection.close()

    def test_rejected_donor_tables_are_not_imported(self) -> None:
        seed_import.import_seed(self.donor, self.output, self.audit, self.contract)
        connection = sqlite3.connect(self.output)
        try:
            target_tables = seed_import.table_names(connection)
        finally:
            connection.close()
        for table in json.loads(self.contract.read_text())["excluded_donor_tables"]:
            self.assertNotIn(table, target_tables)

    def test_donor_identity_mismatch_is_rejected_without_outputs(self) -> None:
        contract = json.loads(self.contract.read_text())
        contract["donor"]["sha256"] = "0" * 64
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Donor SHA-256"):
            seed_import.import_seed(self.donor, self.output, self.audit, self.contract)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.audit.exists())

    def test_release_mismatch_is_rejected_without_outputs(self) -> None:
        contract = json.loads(self.contract.read_text())
        contract["expected_releases"][0]["release_key"] = "wrong-release"
        self.contract.write_text(json.dumps(contract), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Donor release mismatch"):
            seed_import.import_seed(self.donor, self.output, self.audit, self.contract)
        self.assertFalse(self.output.exists())

    def test_missing_source_geojson_is_rejected(self) -> None:
        connection = sqlite3.connect(self.donor)
        connection.execute(
            "UPDATE source_file SET media_type = 'application/octet-stream', "
            "relative_path = 'source.bin' WHERE source_file_id = 10"
        )
        connection.commit()
        connection.close()
        self.write_contract()
        with self.assertRaisesRegex(RuntimeError, "exactly one source GeoJSON"):
            seed_import.import_seed(self.donor, self.output, self.audit, self.contract)

    def test_refuses_existing_output_or_audit(self) -> None:
        self.output.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Output already exists"):
            seed_import.import_seed(self.donor, self.output, self.audit, self.contract)
        self.output.unlink()
        self.audit.write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Audit report already exists"):
            seed_import.import_seed(self.donor, self.output, self.audit, self.contract)

    def test_cli_import_and_validate(self) -> None:
        completed = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-seed-import.sh"),
                "import",
                str(self.donor),
                str(self.output),
                str(self.audit),
                "--contract",
                str(self.contract),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["valid"])
        validated = subprocess.run(
            [
                "bash",
                str(DATABASE_DIR / "kane-seed-import.sh"),
                "validate",
                str(self.output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validated.returncode, validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
