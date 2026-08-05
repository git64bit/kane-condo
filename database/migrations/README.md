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

Batch 007 contains no SQL migration. Batch 008 introduces the GeoPackage core and migration ledger.
