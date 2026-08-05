"""Permanent smoke tests for the Kane Condo repository and migration layout."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATTERN = re.compile(r"^[0-9]{4}_[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")


class RepositorySkeletonTests(unittest.TestCase):
    def test_controlling_contracts_exist(self) -> None:
        expected = {
            "PROJECT_CHARTER.md",
            "USER_WORKFLOW.md",
            "DATA_OWNERSHIP.md",
            "RUNTIME_TOPOLOGY.md",
            "SALVAGE_MANIFEST.md",
            "V1_SCOPE.md",
        }
        actual = {path.name for path in (ROOT / "docs").glob("*.md")}
        self.assertTrue(expected.issubset(actual))

    def test_database_workspace_exists(self) -> None:
        for relative in (
            "database/migrations",
            "database/tools",
            "database/tests",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_dir())

    def test_migration_filenames_are_ordered_and_unique(self) -> None:
        migrations = sorted((ROOT / "database/migrations").glob("*.sql"))
        numbers: list[int] = []
        for migration in migrations:
            self.assertRegex(migration.name, MIGRATION_PATTERN)
            numbers.append(int(migration.name[:4]))
        self.assertEqual(numbers, sorted(set(numbers)))

    def test_no_production_database_is_present(self) -> None:
        prohibited = {".gpkg", ".sqlite", ".sqlite3", ".db"}
        found = [
            str(path.relative_to(ROOT))
            for path in ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.suffix.lower() in prohibited
        ]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
