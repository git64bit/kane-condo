# Database Migrations

Kane Condo migrations are ordered, immutable SQL files.

## Filename contract

```text
NNNN_lowercase_description.sql
```

Current migrations:

```text
0001_geopackage_core.sql
0002_administrative_provenance.sql
0003_county_boundary.sql
0004_roads_water_storage.sql
0005_official_building_storage.sql
0006_project_building_identity.sql
0007_classification_history.sql
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

## Current schema boundary

`0001_geopackage_core.sql` creates the GeoPackage 1.4.0 metadata foundation and immutable migration ledger.

`0002_administrative_provenance.sql` records counties, official agencies, datasets, harvest runs, preserved source files, and source-release lineage.

`0003_county_boundary.sql` registers immutable Polygon or MultiPolygon county-boundary features in EPSG:4326 and associates each feature with one official source release and one preserved source file.

`0004_roads_water_storage.sql` registers immutable LineString, MultiLineString, Polygon, and MultiPolygon road and water features in EPSG:4326, preserving source order, release lineage, hashes, and bounds.

`0005_official_building_storage.sql` registers immutable Polygon and MultiPolygon official building footprints in EPSG:4326, preserving declared source identity, source order, release lineage, hashes, attributes, and bounds.

`0006_project_building_identity.sql` adds project-owned building identities and many-to-many official-footprint mappings while enforcing deterministic one-to-one initial origins.

`0007_classification_history.sql` adds explicit current building classifications, append-only classification events, idempotent event keys, correction chains, and undo relationships. Missing current rows mean Unclassified.

Migration files are part of the database identity. Changing an accepted migration causes validation to fail rather than silently rewriting history.
