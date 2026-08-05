# Kane Condo Database Workspace

This directory contains the authoritative SQLite/GeoPackage migration workspace, controlled database command, and database-focused tests.

## Boundaries

- The Kane Condo database is created from a new migration history.
- The donor `kane-county.gpkg` is read-only seed evidence and is not modified here.
- County Field Map classification, grid calibration, cell relations, and review tables are excluded.
- Production databases, harvests, backups, and generated packages remain outside Git.
- Workstations do not run migrations or county-wide processing.

## Layout

```text
migrations/  Ordered immutable SQL migrations
tools/       Controlled server-side database command implementations
tests/       Standard-library database tests
kane-db.sh   Database command entry point
run-tests.sh Repeatable database test entry point
```

## GeoPackage foundation

Batch 008 establishes a GeoPackage 1.4.0 foundation with:

- SQLite `application_id` `0x47504B47` (`GPKG`);
- SQLite `user_version` `10400`;
- required spatial-reference and contents metadata;
- feature geometry-column metadata for later migrations;
- the standard extension registry;
- an immutable `schema_migration` attributes table;
- SHA-256 verification of every applied migration.

Create a temporary foundation outside the repository:

```bash
bash database/kane-db.sh init /tmp/kane-condo.gpkg
bash database/kane-db.sh validate /tmp/kane-condo.gpkg
bash database/kane-db.sh info /tmp/kane-condo.gpkg
```

The command refuses to overwrite an existing file and removes a newly created file if migration or validation fails.

## Test entry point

From the repository root:

```bash
bash database/run-tests.sh
```

Administrative provenance begins in Batch 009.
