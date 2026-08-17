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

Batch 034 added the local browser runtime and package validation. Batch 035 added the fitted full-county opening outline. Batch 036 added continuous browser-side pan and pointer-anchored zoom. Batch 037 added progressive browser-side road rendering from `roads-lod.krf`. Batch 038 added progressive browser-side water rendering from `water-lod.krf`. Batch 039 adds progressive neutral building rendering from `buildings-lod.krf`: large-building context at broad scale, all simplified accepted buildings at neighborhood scale, and complete exact footprints at close scale.

The application logic remains browser-side HTML, CSS, and JavaScript. The current Python loopback runtime is a local static-serving mechanism, not an application dependency or authoritative backend. Road, water, and building KRF parsing, zlib decompression, validation, LOD selection, and SVG rendering occur in the browser; the host only serves static files. Batch 039 preserves each decoded building's project-owned `building_key` but does not apply classification state or classification colors.

## Development boundary

Batches 008–015 establish the GeoPackage core and authoritative data model. Batches 016–024 establish refresh detection, candidate processing, reconciliation, promotion, and rollback. Batches 025–033 establish the reproducible offline render package. Batches 034–039 establish the initial offline, read-only browser application, full-county opening view, continuous navigation, and progressive road/water/building rendering while preserving the separation between local rendering and the future private authoritative server.
