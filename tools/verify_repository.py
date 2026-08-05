#!/usr/bin/env python3
"""Verify the permanent Kane Condo repository skeleton using the standard library."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

MIGRATION_PATTERN = re.compile(r"^(?P<number>[0-9]{4})_[a-z0-9]+(?:_[a-z0-9]+)*\.sql$")

REQUIRED_FILES = (
    Path("LICENSE"),
    Path("README.md"),
    Path("verify-linux.sh"),
    Path("docs/PROJECT_CHARTER.md"),
    Path("docs/USER_WORKFLOW.md"),
    Path("docs/DATA_OWNERSHIP.md"),
    Path("docs/RUNTIME_TOPOLOGY.md"),
    Path("docs/SALVAGE_MANIFEST.md"),
    Path("docs/V1_SCOPE.md"),
    Path("database/README.md"),
    Path("database/run-tests.sh"),
    Path("database/kane-db.sh"),
    Path("database/kane-provenance.sh"),
    Path("database/kane-boundary.sh"),
    Path("database/kane-map-layers.sh"),
    Path("database/kane-buildings.sh"),
    Path("database/kane-project-buildings.sh"),
    Path("database/kane-classifications.sh"),
    Path("database/kane-seed-import.sh"),
    Path("database/seed/README.md"),
    Path("database/seed/kane-offline-map-0911eeef.json"),
    Path("database/migrations/README.md"),
    Path("database/tools/README.md"),
    Path("database/tests/README.md"),
    Path("database/tests/test_repository_skeleton.py"),
    Path("database/tests/test_geopackage_core.py"),
    Path("database/tests/test_administrative_provenance.py"),
    Path("database/tests/test_county_boundary.py"),
    Path("database/tests/test_roads_water_storage.py"),
    Path("database/tests/test_official_building_storage.py"),
    Path("database/tests/test_project_building_identity.py"),
    Path("database/tests/test_classification_history.py"),
    Path("database/tests/test_seed_import.py"),
    Path("database/migrations/0001_geopackage_core.sql"),
    Path("database/migrations/0002_administrative_provenance.sql"),
    Path("database/migrations/0003_county_boundary.sql"),
    Path("database/migrations/0004_roads_water_storage.sql"),
    Path("database/migrations/0005_official_building_storage.sql"),
    Path("database/migrations/0006_project_building_identity.sql"),
    Path("database/migrations/0007_classification_history.sql"),
    Path("database/tools/kane_db.py"),
    Path("database/tools/kane_provenance.py"),
    Path("database/tools/kane_geometry.py"),
    Path("database/tools/kane_boundary.py"),
    Path("database/tools/kane_map_layers.py"),
    Path("database/tools/kane_buildings.py"),
    Path("database/tools/kane_project_buildings.py"),
    Path("database/tools/kane_classifications.py"),
    Path("database/tools/kane_seed_import.py"),
    Path("tools/verify_repository.py"),
)

PROHIBITED_SUFFIXES = (
    ".gpkg",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".db-shm",
    ".db-wal",
    ".pyc",
    ".pyo",
    ".zip",
)

PROHIBITED_DIRECTORY_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    "build",
    "dist",
    "external-data",
    "runtime-data",
    "generated",
    "artifacts",
}

SKIPPED_DIRECTORY_NAMES = {".git"}


def iter_repository_paths(root: Path):
    """Yield repository paths while excluding Git internals."""
    for path in root.rglob("*"):
        if any(part in SKIPPED_DIRECTORY_NAMES for part in path.relative_to(root).parts):
            continue
        yield path


def verify_required_files(root: Path) -> None:
    missing = [str(path) for path in REQUIRED_FILES if not (root / path).is_file()]
    if missing:
        raise ValueError("Missing required files: " + ", ".join(missing))


def verify_no_prohibited_artifacts(root: Path) -> None:
    violations: list[str] = []
    for path in iter_repository_paths(root):
        relative = path.relative_to(root)
        if path.is_dir() and path.name in PROHIBITED_DIRECTORY_NAMES:
            violations.append(str(relative) + "/")
            continue
        if path.is_file() and path.name.endswith(PROHIBITED_SUFFIXES):
            violations.append(str(relative))
    if violations:
        raise ValueError("Prohibited generated or production artifacts: " + ", ".join(violations))


def verify_migration_names(root: Path) -> int:
    migrations = sorted((root / "database/migrations").glob("*.sql"))
    seen_numbers: dict[str, str] = {}
    for migration in migrations:
        match = MIGRATION_PATTERN.fullmatch(migration.name)
        if match is None:
            raise ValueError(
                "Invalid migration filename "
                f"{migration.name!r}; expected NNNN_lowercase_description.sql"
            )
        number = match.group("number")
        if number in seen_numbers:
            raise ValueError(
                f"Duplicate migration number {number}: "
                f"{seen_numbers[number]} and {migration.name}"
            )
        seen_numbers[number] = migration.name
    return len(migrations)


def verify_python_syntax(root: Path) -> int:
    python_files = sorted(
        path for path in iter_repository_paths(root) if path.is_file() and path.suffix == ".py"
    )
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ValueError(f"Python syntax validation failed for {path}: {exc}") from exc
    return len(python_files)


def verify_shell_entry_points(root: Path) -> int:
    scripts = (
        root / "verify-linux.sh",
        root / "database/run-tests.sh",
        root / "database/kane-db.sh",
        root / "database/kane-provenance.sh",
        root / "database/kane-boundary.sh",
        root / "database/kane-map-layers.sh",
        root / "database/kane-buildings.sh",
        root / "database/kane-project-buildings.sh",
        root / "database/kane-classifications.sh",
        root / "database/kane-seed-import.sh",
    )
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        if not text.startswith("#!/usr/bin/env bash\n"):
            raise ValueError(f"Shell entry point lacks the required bash shebang: {script}")
        if "set -euo pipefail" not in text:
            raise ValueError(f"Shell entry point lacks strict mode: {script}")
    return len(scripts)


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print("Usage: verify_repository.py [repository-root]", file=sys.stderr)
        return 2

    root = Path(argv[1] if len(argv) == 2 else ".").resolve()
    if not root.is_dir():
        print(f"Repository root is not a directory: {root}", file=sys.stderr)
        return 2

    try:
        verify_required_files(root)
        verify_no_prohibited_artifacts(root)
        migration_count = verify_migration_names(root)
        python_count = verify_python_syntax(root)
        shell_count = verify_shell_entry_points(root)
    except (OSError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"Repository root: {root}")
    print(f"Required files: {len(REQUIRED_FILES)}")
    print(f"Migration files: {migration_count}")
    print(f"Python files parsed: {python_count}")
    print(f"Shell entry points checked: {shell_count}")
    print("Prohibited artifacts: none")
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
