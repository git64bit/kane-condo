# Database Tools

This directory contains controlled server-side commands for Kane Condo database work.

## Official source-profile command

`kane_source_profiles.py` supports:

```text
validate  Validate exactly five approved offline source contracts
info      Report the normalized profiles and deterministic registry identity
hash      Report the deterministic registry SHA-256
```

The command uses only version-controlled JSON contracts. It performs no network requests, downloads, update checks, or production-database changes.

Use:

```bash
bash database/kane-source-profiles.sh --help
```

## Official source-status command

`kane_source_status.py` supports:

```text
check     Compare the accepted database with live layer metadata and object-ID inventories
```

The command opens the accepted GeoPackage read-only and query-only. Network requests are limited to the five approved ArcGIS metadata and `returnIdsOnly` endpoints; no feature geometry is downloaded and no candidate or accepted release is written.

Use:

```bash
bash database/kane-source-status.sh --help
```

## Official building candidate command

`kane_building_candidate.py` supports:

```text
harvest   Harvest a complete official-building candidate into external staging
validate  Validate one staged candidate without network or database writes
register  Register validated candidate provenance without changing the accepted release
info      Trace one registered building candidate
```

The harvest uses the approved building profile, complete object-ID inventory, exact bounded ID groups, stable `FPId` identities, canonical serialization, end-of-harvest metadata and inventory verification, and immutable candidate directory identity. Registration writes only the candidate harvest, source-file identities, and candidate release provenance. It does not import candidate features, change the accepted release, or alter project identities or classifications.

Use:

```bash
bash database/kane-building-candidate.sh --help
```

## GeoPackage command

`kane_db.py` supports:

```text
init      Create a new GeoPackage and apply every migration
validate  Validate the GeoPackage header, schema, integrity, and migration identity
info      Report the database and migration identity as JSON
```

Use:

```bash
bash database/kane-db.sh --help
```

## Administrative provenance command

`kane_provenance.py` supports:

```text
record    Record one source-release descriptor and preserved source-file identities
trace     Trace one release through its dataset, agency, county, harvest, and files
validate  Validate administrative provenance
```

Use:

```bash
bash database/kane-provenance.sh --help
```

## County-boundary command

`kane_boundary.py` supports:

```text
import    Store one Polygon or MultiPolygon GeoJSON feature for an existing boundary release
info      Report the accepted or named stored boundary and its source lineage
validate  Validate boundary registration, geometry, bounds, hashes, and release association
```

Use:

```bash
bash database/kane-boundary.sh --help
```

## Roads-and-water command

`kane_map_layers.py` supports:

```text
import    Atomically store one or more RELEASE_KEY GEOJSON pairs
info      Report accepted or named stored road and water releases
validate  Validate registration, geometry, source order, hashes, bounds, and lineage
```

Use:

```bash
bash database/kane-map-layers.sh --help
```

## Official-building command

`kane_buildings.py` supports:

```text
import    Store one Polygon or MultiPolygon official building release
info      Report the accepted or named stored building release
validate  Validate registration, geometry, source order, hashes, bounds, identity, and lineage
```

Use:

```bash
bash database/kane-buildings.sh --help
```

## Project-building identity command

`kane_project_buildings.py` supports:

```text
seed      Create deterministic project identities from one accepted building release
info      Report project identities, mapping counts, and accepted-release coverage
validate  Validate deterministic keys, origins, mappings, and accepted-release coverage
```

Use:

```bash
bash database/kane-project-buildings.sh --help
```

## Building-classification command

`kane_classifications.py` supports:

```text
set       Write one deliberate classification event
undo      Reverse the latest event with a new append-only event
get       Report one current building classification
history   Report one building's ordered event history
info      Report county-wide classification and event counts
validate  Validate current state, event chains, triggers, and registrations
```

Use:

```bash
bash database/kane-classifications.sh --help
```

## Seed-import command

`kane_seed_import.py` supports:

```text
import    Build a clean Kane Condo database from an approved donor and write an audit report
validate  Validate a generated seed database and confirm it has no explicit classifications
```

The default contract is `database/seed/kane-offline-map-0911eeef.json`. The donor database is opened read-only, verified by byte length and SHA-256, and left unchanged. Output databases and audit reports must be outside Git.

Use:

```bash
bash database/kane-seed-import.sh --help
```

`kane_geometry.py` provides strict EPSG:4326 line and polygon normalization and GeoPackage binary encoding/decoding for county boundary, roads, water, official buildings, and later spatial migrations.

All commands use Python's standard library. They run on server-side Linux infrastructure, keep production data outside Git, and do not move processing onto Windows or Ubuntu user workstations.
