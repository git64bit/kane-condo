# Database Migrations

Kane Condo migrations are ordered, immutable SQL files.

## Filename contract

```text
NNNN_lowercase_description.sql
```

Examples:

```text
0001_geopackage_core.sql
0002_administrative_provenance.sql
```

Rules:

- use exactly four decimal digits;
- use lowercase words separated by underscores;
- never reuse a migration number;
- never edit an accepted migration in place;
- record and validate migration hashes;
- apply migrations in numeric order;
- design each migration for an explicit transaction boundary;
- add no County Field Map classification, grid, cell, or review schema.

## Current migration

`0001_geopackage_core.sql` creates the GeoPackage 1.4.0 metadata foundation and registers the immutable `schema_migration` ledger as a non-spatial attributes table.

The migration file is part of the database identity. Changing an accepted migration causes validation to fail rather than silently rewriting history.
