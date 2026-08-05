# Kane Condo

Kane Condo is a private, single-user application for classifying individual Kane County building footprints as:

- Unclassified;
- Other;
- Condominium;
- Apartments.

The controlling project contracts are in [`docs/`](docs/). Implementation proceeds in bounded, explicitly authorized batches.

## Current repository structure

```text
database/
  migrations/   Ordered SQLite/GeoPackage migrations
  tools/        Controlled database, provenance, geometry, and import commands
  tests/        Database-focused standard-library tests
docs/            Approved project contracts
tools/           Repository-level verification tools
verify-linux.sh  Repeatable Linux verification entry point
```

The repository contains source, migrations, tests, and documentation. Production county harvests, GeoPackages, classification databases, generated map packages, deployment archives, secrets, and backups remain outside Git.

## Verify a clean checkout

From the repository root:

```bash
bash verify-linux.sh
```

The command uses Python's standard library only. It validates the repository skeleton, migration filename rules, source syntax, and the absence of prohibited generated or production artifacts.

## Development boundary

Batches 008–013 establish the GeoPackage 1.4.0 core, immutable migration identity, administrative source provenance, county boundary, roads, water, official building releases, and project-owned building identities with auditable source mappings. The production seed import, classifications, private API, browser application, and offline render package remain outside the repository at this stage.
