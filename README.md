# Kane Condo

Kane Condo is a private, single-user application for classifying individual Kane County building footprints as:

- Unclassified;
- Other;
- Condominium;
- Apartments.

The controlling project contracts are in [`docs/`](docs/). Implementation proceeds in bounded, explicitly authorized batches.

## Current repository structure

```text
app/            Local read-only browser application and loopback development/workstation runtime
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

## Development and workstation acceptance boundary

The development/processing orchestrator is not the Kane Condo user workstation. Normal development verification on the orchestrator is headless and must not require a desktop browser, workstation USB access, or opening the orchestrator's loopback URL from the user's workstation.

The browser application, local launcher, and USB-resident package are ultimately exercised on the target Windows and Ubuntu user workstations. Milestone 4 Batch 042 is the explicit physical workstation/USB acceptance batch for startup, county overview, navigation, dense rendering, and performance. Earlier Milestone 4 batches are accepted on the orchestrator through their bounded automated tests and source/package-contract checks unless a batch explicitly defines an earlier target-workstation test.

Do not treat lack of a browser or accessible USB ports on the orchestrator as a Kane Condo runtime failure.

## Local read-only application

Batch 034 added the first Milestone 4 browser runtime. It serves the browser application and one external Milestone 3 render package from a loopback-only local origin:

```bash
bash app/kane-local.sh /path/to/render-package
```

The browser validates the local package manifest and all required component byte lengths and SHA-256 hashes before opening the map. Batch 035 adds the fitted full-county opening outline from `county-overview.json`. Batch 036 adds continuous browser-side pan and pointer-anchored wheel/trackpad zoom plus reset-to-county behavior. Navigation changes only transient SVG viewport state and performs no network or persistence writes.

The application logic remains browser-side HTML, CSS, and JavaScript. The current Python loopback runtime is a local static-serving mechanism, not an application dependency or authoritative backend.

## Development boundary

Batches 008–015 establish the GeoPackage 1.4.0 core, immutable migration identity, administrative source provenance, county boundary, roads, water, official building releases, project-owned building identities, authoritative building classifications with append-only history, and a verified clean seed-import path from the accepted donor GeoPackage. Batches 016–024 establish refresh detection, candidate harvesting, comparison, identity reconciliation, promotion, and rollback. Batches 025–033 establish the reproducible offline render package. Batches 034–036 establish the initial offline, read-only browser application shell, county opening view, and continuous navigation while preserving the separation between local rendering and the future private authoritative server.
