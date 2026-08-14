#!/usr/bin/env python3
"""Build, validate, and compare complete Batch 033 Kane Condo render packages."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

PACKAGE_FILES = {
    "county_overview": "county-overview.json",
    "roads": "roads-lod.krf",
    "water": "water-lod.krf",
    "buildings": "buildings-lod.krf",
    "classification_snapshot": "classification-snapshot.json",
    "manifest": "render-package-manifest.json",
}
COMPONENT_ROLES = (
    "county_overview",
    "roads",
    "water",
    "buildings",
    "classification_snapshot",
)


def load_sibling(name: str):
    module_path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_kane_condo_package_{name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load render-package support: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OVERVIEW = load_sibling("kane_county_overview")
ROAD = load_sibling("kane_road_lod")
WATER = load_sibling("kane_water_lod")
BUILDING = load_sibling("kane_building_lod")
CLASSIFICATION = load_sibling("kane_classification_snapshot")
MANIFEST = load_sibling("kane_package_manifest")


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def package_paths(package_dir: Path) -> dict[str, Path]:
    root = package_dir.resolve()
    return {role: root / filename for role, filename in PACKAGE_FILES.items()}


def _require_package_directory(package_dir: Path) -> Path:
    package_dir = package_dir.resolve()
    if package_dir.is_symlink():
        raise RuntimeError(f"Render package directory must not be a symlink: {package_dir}")
    if not package_dir.is_dir():
        raise RuntimeError(f"Render package directory does not exist: {package_dir}")
    expected = set(PACKAGE_FILES.values())
    actual = {path.name for path in package_dir.iterdir()}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing={missing!r}")
        if extra:
            details.append(f"extra={extra!r}")
        raise RuntimeError("Render package file inventory is invalid: " + ", ".join(details))
    for filename in expected:
        path = package_dir / filename
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Render package component is not a regular file: {path}")
    return package_dir


def _manifest_document(package_dir: Path) -> tuple[dict[str, object], bytes]:
    paths = package_paths(package_dir)
    data = paths["manifest"].read_bytes()
    return MANIFEST.read_manifest_bytes(data), data


def _component_hashes(document: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    components = document.get("components")
    if not isinstance(components, list):
        raise RuntimeError("Render package manifest component list is invalid")
    for item in components:
        if not isinstance(item, Mapping):
            raise RuntimeError("Render package manifest component descriptor is invalid")
        role = str(item.get("role"))
        sha = str(item.get("sha256"))
        if role not in COMPONENT_ROLES or len(sha) != 64:
            raise RuntimeError("Render package manifest component identity is invalid")
        result[role] = sha
    if set(result) != set(COMPONENT_ROLES):
        raise RuntimeError("Render package manifest component roles are invalid")
    return {role: result[role] for role in COMPONENT_ROLES}


def summarize_package(package_dir: Path) -> dict[str, object]:
    package_dir = _require_package_directory(package_dir)
    document, manifest_bytes = _manifest_document(package_dir)
    identities = document["identities"]
    return {
        "base_geometry_sha256": identities["base_geometry_sha256"],
        "component_sha256": _component_hashes(document),
        "created_at": document["created_at"],
        "manifest_sha256": MANIFEST.sha256_bytes(manifest_bytes),
        "package_content_sha256": identities["package_content_sha256"],
        "package_directory": str(package_dir),
    }


def validate_package(database: Path, package_dir: Path) -> dict[str, object]:
    database = database.resolve()
    package_dir = _require_package_directory(package_dir)
    paths = package_paths(package_dir)
    result = MANIFEST.validate_manifest_against_inputs(
        database,
        paths["manifest"],
        paths["county_overview"],
        paths["roads"],
        paths["water"],
        paths["buildings"],
        paths["classification_snapshot"],
    )
    summary = summarize_package(package_dir)
    summary["status"] = result["status"]
    return summary


def _build_staged_package(
    database: Path, stage_dir: Path, *, created_at: str | None = None
) -> dict[str, object]:
    paths = package_paths(stage_dir)
    OVERVIEW.build_overview(database, paths["county_overview"])
    ROAD.write_container(database, paths["roads"])
    WATER.write_container(database, paths["water"])
    BUILDING.write_container(database, paths["buildings"])
    CLASSIFICATION.write_snapshot(database, paths["classification_snapshot"])
    MANIFEST.write_manifest(
        database,
        paths["manifest"],
        paths["county_overview"],
        paths["roads"],
        paths["water"],
        paths["buildings"],
        paths["classification_snapshot"],
        created_at=created_at,
    )
    return validate_package(database, stage_dir)


def _staging_prefix(package_dir: Path) -> str:
    return f".{package_dir.name}.stage-"


def _backup_path(package_dir: Path) -> Path:
    return package_dir.with_name(f".{package_dir.name}.previous")


def recover_interrupted_promotion(package_dir: Path) -> None:
    package_dir = package_dir.resolve()
    parent = package_dir.parent
    backup = _backup_path(package_dir)
    if backup.exists():
        if backup.is_symlink() or not backup.is_dir():
            raise RuntimeError(f"Render package recovery path is invalid: {backup}")
        if package_dir.exists():
            shutil.rmtree(backup)
        else:
            os.replace(backup, package_dir)
    if not parent.is_dir():
        return
    prefix = _staging_prefix(package_dir)
    for path in parent.iterdir():
        if path.name.startswith(prefix):
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError(f"Render package stale staging path is invalid: {path}")
            shutil.rmtree(path)


def promote_staged_package(stage_dir: Path, package_dir: Path) -> None:
    stage_dir = stage_dir.resolve()
    package_dir = package_dir.resolve()
    if stage_dir.parent != package_dir.parent:
        raise RuntimeError("Render package staging and destination must share a parent directory")
    if package_dir.is_symlink():
        raise RuntimeError("Render package destination must not be a symlink")
    backup = _backup_path(package_dir)
    if backup.exists():
        raise RuntimeError(f"Render package promotion backup already exists: {backup}")

    moved_old = False
    if package_dir.exists():
        if not package_dir.is_dir():
            raise RuntimeError(f"Render package destination is not a directory: {package_dir}")
        os.replace(package_dir, backup)
        moved_old = True
    try:
        os.replace(stage_dir, package_dir)
    except BaseException:
        if moved_old and backup.exists() and not package_dir.exists():
            os.replace(backup, package_dir)
        raise
    if moved_old and backup.exists():
        shutil.rmtree(backup)


def build_package(
    database: Path, package_dir: Path, *, created_at: str | None = None
) -> dict[str, object]:
    database = database.resolve()
    package_dir = package_dir.resolve()
    if not database.is_file():
        raise RuntimeError(f"Authoritative database does not exist: {database}")
    if package_dir == database or package_dir in database.parents:
        raise RuntimeError("Render package destination must not replace or contain the authoritative database")
    package_dir.parent.mkdir(parents=True, exist_ok=True)
    recover_interrupted_promotion(package_dir)

    stage_dir = Path(
        tempfile.mkdtemp(prefix=_staging_prefix(package_dir), dir=str(package_dir.parent))
    ).resolve()
    promoted = False
    try:
        _build_staged_package(database, stage_dir, created_at=created_at)
        promote_staged_package(stage_dir, package_dir)
        promoted = True
    finally:
        if not promoted and stage_dir.exists():
            shutil.rmtree(stage_dir)
    result = validate_package(database, package_dir)
    result["status"] = "built"
    return result


def compare_packages(database: Path, first: Path, second: Path) -> dict[str, object]:
    first = first.resolve()
    second = second.resolve()
    first_summary = validate_package(database, first)
    second_summary = validate_package(database, second)
    first_document, first_manifest = _manifest_document(first)
    second_document, second_manifest = _manifest_document(second)

    for role in COMPONENT_ROLES:
        first_bytes = package_paths(first)[role].read_bytes()
        second_bytes = package_paths(second)[role].read_bytes()
        if first_bytes != second_bytes:
            raise RuntimeError(f"Render package reproducibility mismatch: component {role}")

    normalized_first = dict(first_document)
    normalized_second = dict(second_document)
    normalized_first.pop("created_at", None)
    normalized_second.pop("created_at", None)
    if normalized_first != normalized_second:
        raise RuntimeError("Render package reproducibility mismatch outside created_at")
    if first_summary["package_content_sha256"] != second_summary["package_content_sha256"]:
        raise RuntimeError("Render package stable content identity mismatch")

    return {
        "component_sha256": first_summary["component_sha256"],
        "created_at": [first_summary["created_at"], second_summary["created_at"]],
        "manifest_bytes_identical": first_manifest == second_manifest,
        "package_content_sha256": first_summary["package_content_sha256"],
        "status": "reproducible",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build and atomically promote a complete render package")
    build.add_argument("database", type=Path)
    build.add_argument("package_dir", type=Path)
    build.add_argument("--created-at", help="override manifest UTC creation time")

    validate = subparsers.add_parser("validate", help="validate a complete render package")
    validate.add_argument("database", type=Path)
    validate.add_argument("package_dir", type=Path)

    inspect = subparsers.add_parser("inspect", help="inspect a package manifest and exact file inventory")
    inspect.add_argument("package_dir", type=Path)

    compare = subparsers.add_parser(
        "compare", help="validate and compare two builds from the same authoritative database"
    )
    compare.add_argument("database", type=Path)
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_package(args.database, args.package_dir, created_at=args.created_at)
        elif args.command == "validate":
            result = validate_package(args.database, args.package_dir)
        elif args.command == "inspect":
            result = summarize_package(args.package_dir)
        else:
            result = compare_packages(args.database, args.first, args.second)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
