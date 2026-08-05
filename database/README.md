# Kane Condo Database Workspace

This directory is the future home of the authoritative SQLite/GeoPackage schema, migration tools, and database-focused tests.

## Boundaries

- The Kane Condo database will be created from a new migration history.
- The donor `kane-county.gpkg` is read-only seed evidence and is not modified here.
- County Field Map classification, grid calibration, cell relations, and review tables are excluded.
- Production databases, harvests, backups, and generated packages remain outside Git.
- Workstations do not run migrations or county-wide processing.

## Layout

```text
migrations/  Ordered immutable SQL migrations
tools/       Future migration and database command implementations
tests/       Standard-library database tests
run-tests.sh Repeatable database test entry point
```

## Test entry point

From the repository root:

```bash
bash database/run-tests.sh
```

Batch 007 establishes the structure only. The GeoPackage core begins in Batch 008.
