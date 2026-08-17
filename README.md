# Kane Condo

Kane Condo is a private, single-user application for classifying individual Kane County building footprints as:

- Unclassified;
- Other;
- Condominium;
- Apartments.

The controlling project contracts are in [`docs/`](docs/). Implementation proceeds in bounded, explicitly authorized batches.

## Current repository structure

```text
app/            Local read-only browser shell and loopback runtime
database/
  migrations/   Ordered SQLite/GeoPackage migrations
  tools/        Controlled database, provenance, geometry, and import commands
  tests/        Database-focused standard-library tests
docs/            Approved project contracts
render/          Offline render-package generators, formats, and tests
tools/           Repository-level verification tools
verify-linux.sh  Repeatable Linux verification entry point
```

The repository contains source, migrations, tests, and documentation. Production county harvests, GeoPackages, classification databases, generated map packages, deployment archives, secrets, and backups remain outside Git.

## Verify a clean checkout

From the repository root:

```bash
bash verify-linux.sh
```

The command uses Python's standard library for repository, database, render-package, and local-runtime verification. It validates the repository skeleton, migration filename rules, source syntax, the absence of prohibited generated or production artifacts, and the bounded subsystem tests.

## Local read-only application shell

Batch 034 adds the first Milestone 4 browser runtime. It serves the browser application and one external Milestone 3 render package from a loopback-only local origin:

```bash
bash app/kane-local.sh /path/to/render-package
```

The browser validates the local package manifest and all required component byte lengths and SHA-256 hashes before declaring the package ready. Batch 034 does not render the map, contact the future private API, or permit classification writes.

## Development boundary

Batches 008–015 establish the GeoPackage 1.4.0 core, immutable migration identity, administrative source provenance, county boundary, roads, water, official building releases, project-owned building identities, authoritative building classifications with append-only history, and a verified clean seed-import path from the accepted donor GeoPackage. Batches 016–024 establish refresh detection, candidate harvesting, comparison, identity reconciliation, promotion, and rollback. Batches 025–033 establish the reproducible offline render package. Batch 034 begins the offline, read-only browser application while preserving the separation between local rendering and the future private authoritative server.
