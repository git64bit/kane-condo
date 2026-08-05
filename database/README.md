# Kane Condo Database Workspace

This directory contains the authoritative SQLite/GeoPackage migration workspace, controlled server-side commands, and database-focused tests.

## Boundaries

- The Kane Condo database is created from a new migration history.
- The donor `kane-county.gpkg` is read-only seed evidence and is not modified here.
- County Field Map classification, grid calibration, cell relations, and review tables are excluded.
- Production databases, harvests, backups, and generated packages remain outside Git.
- Workstations do not run migrations or county-wide processing.

## Layout

```text
migrations/          Ordered immutable SQL migrations
tools/               Controlled server-side database commands and geometry support
tests/               Standard-library database tests
kane-db.sh           GeoPackage command entry point
kane-provenance.sh   Administrative provenance entry point
kane-boundary.sh     County-boundary storage entry point
kane-map-layers.sh   Roads-and-water storage entry point
kane-buildings.sh    Official building-release storage entry point
kane-project-buildings.sh Project-owned building identity entry point
run-tests.sh         Repeatable database test entry point
```

## Current database foundation

The current migrations establish:

- GeoPackage 1.4.0 metadata and EPSG:4326;
- exact SHA-256 migration identity;
- Kane County, source-agency, dataset, harvest, source-file, and source-release provenance;
- immutable county-boundary features grouped by source release;
- immutable roads and water features grouped by source release;
- immutable official building footprints grouped by source release;
- project-owned building identities and auditable official-footprint mappings;
- authoritative current building classifications and append-only history;
- exact source-file, source-order, geometry, attributes, content, and bounds identities.

Create a temporary database outside the repository:

```bash
bash database/kane-db.sh init /tmp/kane-condo.gpkg
bash database/kane-db.sh validate /tmp/kane-condo.gpkg
bash database/kane-db.sh info /tmp/kane-condo.gpkg
```

Record a synthetic or controlled release descriptor before importing its boundary geometry:

```bash
bash database/kane-provenance.sh record /tmp/kane-condo.gpkg /path/to/release.json
bash database/kane-boundary.sh import /tmp/kane-condo.gpkg RELEASE_KEY /path/to/boundary.geojson
bash database/kane-boundary.sh validate /tmp/kane-condo.gpkg
bash database/kane-boundary.sh info /tmp/kane-condo.gpkg
```

Record road and water release descriptors, then import one or more release/file pairs atomically:

```bash
bash database/kane-provenance.sh record /tmp/kane-condo.gpkg /path/to/roads-release.json
bash database/kane-provenance.sh record /tmp/kane-condo.gpkg /path/to/river-release.json
bash database/kane-map-layers.sh import /tmp/kane-condo.gpkg \
  ROADS_RELEASE /path/to/roads.geojson \
  RIVER_RELEASE /path/to/fox-river.geojson
bash database/kane-map-layers.sh validate /tmp/kane-condo.gpkg
bash database/kane-map-layers.sh info /tmp/kane-condo.gpkg
```

Record an official building release descriptor, then import its exact preserved GeoJSON:

```bash
bash database/kane-provenance.sh record /tmp/kane-condo.gpkg /path/to/buildings-release.json
bash database/kane-buildings.sh import /tmp/kane-condo.gpkg \
  BUILDING_RELEASE /path/to/buildings.geojson
bash database/kane-buildings.sh validate /tmp/kane-condo.gpkg
bash database/kane-buildings.sh info /tmp/kane-condo.gpkg
```

Create deterministic project-owned identities from the accepted official building release:

```bash
bash database/kane-project-buildings.sh seed /tmp/kane-condo.gpkg BUILDING_RELEASE
bash database/kane-project-buildings.sh validate /tmp/kane-condo.gpkg
bash database/kane-project-buildings.sh info /tmp/kane-condo.gpkg BUILDING_RELEASE
```

Write and inspect authoritative building classifications after project identities exist:

```bash
bash database/kane-classifications.sh set /tmp/kane-condo.gpkg BUILDING_KEY other request:001
bash database/kane-classifications.sh get /tmp/kane-condo.gpkg BUILDING_KEY
bash database/kane-classifications.sh history /tmp/kane-condo.gpkg BUILDING_KEY
bash database/kane-classifications.sh undo /tmp/kane-condo.gpkg BUILDING_KEY request:002
bash database/kane-classifications.sh validate /tmp/kane-condo.gpkg
```

The commands refuse unsafe or inconsistent input and validate writes before completion. The actual accepted donor boundary remains external until the later verified seed-import batch.

## Test entry point

From the repository root:

```bash
bash database/run-tests.sh
```
