# Kane Condo Database Workspace

This directory contains the authoritative SQLite/GeoPackage migration workspace, controlled server-side commands, and database-focused tests.

## Boundaries

- The Kane Condo database is created from a new migration history.
- The donor `kane-county.gpkg` is read-only seed evidence and is not modified here.
- County Field Map classification, grid calibration, cell relations, and review tables are excluded.
- Production databases, harvests, backups, and generated packages remain outside Git.
- Workstations do not run migrations or county-wide processing.
- Official source-profile validation is offline and makes no network requests.
- Lightweight source-status checks make bounded metadata and object-ID requests only; they never download feature geometry or write the accepted database.
- Building candidate harvests write complete validated evidence to an external staging directory before registering candidate provenance; they never replace the accepted release.
- Road candidate harvests preserve the complete object-ID inventory, retained line geometry, and any explicitly excluded null-geometry IDs before provenance-only registration; they never replace the accepted road release.
- Water candidate harvests treat Fox River and creeks as one coordinated `water-context` unit: both complete candidates must validate together and their provenance is registered atomically; neither accepted water release is replaced.
- County-boundary candidate harvests use the accepted Kane County identity and boundary envelope as guards; unexpected identity, geometry, or gross bounds are rejected before provenance-only registration.

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
kane-classifications.sh Authoritative classification history entry point
kane-seed-import.sh Verified donor seed-import entry point
kane-source-profiles.sh Official source-profile registry entry point
kane-source-status.sh Lightweight official-source status entry point
kane-building-candidate.sh Official building candidate harvest entry point
kane-road-candidate.sh Official road candidate harvest entry point
kane-water-candidate.sh Coordinated Fox River/creeks candidate harvest entry point
kane-boundary-candidate.sh County-boundary candidate harvest entry point
seed/                 Versioned external seed identity contracts
source-profiles/      Versioned official acquisition contracts
run-tests.sh         Repeatable database test entry point
```

## Official source-profile registry

Validate, inspect, or deterministically hash the five approved official acquisition contracts without contacting the network:

```bash
bash database/kane-source-profiles.sh validate
bash database/kane-source-profiles.sh info
bash database/kane-source-profiles.sh hash
```

The registry preserves donor-derived endpoints, identities, requested fields, and geometry declarations while adding Kane Condo pagination, ordering, response-validation, and coordinated water-update rules. It contains no harvested or production data.

## Lightweight source-status check

Check the five approved services against the accepted production database without downloading feature geometry:

```bash
bash database/kane-source-status.sh check \
  /root/kane-condo-data/database/kane-condo.gpkg
```

The command reads the accepted database in SQLite read-only/query-only mode. For each profile it requests only ArcGIS layer metadata and the complete object-ID inventory, then reports **Up to date**, **New source detected**, **Source unavailable**, or **Source changed unexpectedly**. It prefers the ArcGIS data-edit timestamp over schema-only edit timestamps, and Fox River plus creeks are summarized as the coordinated `water-context` group. Detection never registers a candidate, changes an accepted release, or writes harvested responses to Git or the production workspace.

## Official building candidate harvest

Harvest a complete official-building candidate into an external staging directory, validate the staged evidence offline, and register only its provenance as a `candidate` release:

```bash
bash database/kane-building-candidate.sh harvest \
  /root/kane-condo-data/staging

bash database/kane-building-candidate.sh validate \
  /root/kane-condo-data/staging/buildings/CANDIDATE_RELEASE_KEY

bash database/kane-building-candidate.sh register \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/staging/buildings/CANDIDATE_RELEASE_KEY

bash database/kane-building-candidate.sh info \
  /root/kane-condo-data/database/kane-condo.gpkg \
  CANDIDATE_RELEASE_KEY
```

The harvester retrieves the complete ascending object-ID inventory, requests exact bounded ID groups, validates all requested fields, requires unique `FPId` identities, normalizes Polygon and MultiPolygon geometry, rechecks metadata and the complete inventory after the final page, and writes canonical source, metadata, inventory, and manifest files. Registration is refused until the external candidate validates; it records provenance only and leaves the accepted building release, project identities, mappings, and classifications unchanged. Candidate directories and production databases remain outside Git.

## Official road candidate harvest

Harvest a complete road candidate into external staging, validate it offline, and register only its provenance:

```bash
bash database/kane-road-candidate.sh harvest \
  /root/kane-condo-data/staging

bash database/kane-road-candidate.sh validate \
  /root/kane-condo-data/staging/roads/CANDIDATE_RELEASE_KEY

bash database/kane-road-candidate.sh register \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/staging/roads/CANDIDATE_RELEASE_KEY

bash database/kane-road-candidate.sh info \
  /root/kane-condo-data/database/kane-condo.gpkg \
  CANDIDATE_RELEASE_KEY
```

The road harvester uses the approved road profile, retrieves the complete ascending object-ID inventory, requests exact bounded ID groups, validates LineString and MultiLineString geometry, and rechecks metadata plus the complete inventory after the final page. Because the approved road profile explicitly excludes missing geometry, null-geometry object IDs are preserved separately in `excluded-object-ids.json`; retained features and exclusions must together cover the complete inventory. Registration records provenance only and leaves the accepted road release and stored map features unchanged.

## Coordinated water candidate harvest

Harvest Fox River and creeks together into one external `water-context` candidate, validate both components offline, and register both candidate provenances atomically:

```bash
bash database/kane-water-candidate.sh harvest \
  /root/kane-condo-data/staging

bash database/kane-water-candidate.sh validate \
  /root/kane-condo-data/staging/water/GROUP_KEY

bash database/kane-water-candidate.sh register \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/staging/water/GROUP_KEY

bash database/kane-water-candidate.sh info \
  /root/kane-condo-data/database/kane-condo.gpkg \
  GROUP_KEY
```

The harvester retrieves and rechecks complete object-ID inventories for both approved water profiles, validates creek line geometry and Fox River polygon geometry, rejects missing geometry, and writes one canonical group manifest linking both candidate releases. Registration is all-or-nothing: a partial `water-context` registration is rejected, accepted Fox River and creek releases remain unchanged, and no candidate geometry is imported during Batch 020.

## County-boundary candidate harvest

Harvest one complete boundary candidate using the accepted county boundary as the identity and gross-bounds reference, validate the staged evidence offline, and register provenance only:

```bash
bash database/kane-boundary-candidate.sh harvest \
  /root/kane-condo-data/staging \
  /root/kane-condo-data/database/kane-condo.gpkg

bash database/kane-boundary-candidate.sh validate \
  /root/kane-condo-data/staging/boundary/RELEASE_KEY

bash database/kane-boundary-candidate.sh register \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/staging/boundary/RELEASE_KEY
```

The harvester requires exactly one live object ID and the same source identity as the accepted Kane County boundary, validates Polygon or MultiPolygon geometry, and rejects gross envelope changes relative to the accepted boundary. Metadata and inventory are rechecked after the feature download. The staged manifest freezes the accepted county key, FIPS identity, accepted release hash, source identity, accepted bounds, and the deterministic gross-bounds policy so offline validation remains meaningful. Registration rechecks that accepted reference and writes only candidate provenance; it does not import candidate geometry or replace the accepted boundary.

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
- exact source-file, source-order, geometry, attributes, content, and bounds identities;
- verified clean seed import from the accepted donor GeoPackage, with an external audit report.

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

Build the first production seed database from the exact accepted donor GeoPackage. Both the donor and generated database remain outside Git:

```bash
mkdir -p /root/kane-condo-data/database /root/kane-condo-data/audit

bash database/kane-seed-import.sh import \
  /root/kane-offline-data/database/kane-county.gpkg \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/audit/seed-import.json

bash database/kane-seed-import.sh validate \
  /root/kane-condo-data/database/kane-condo.gpkg
```

The seed command verifies the donor byte length, SHA-256, source commit, accepted release keys, release content hashes, and canonical feature totals before creating a new Kane Condo database. It imports no County Field Map classification, calibration, cell-relation, or review tables. The donor is opened read-only and verified unchanged after import.

All commands refuse unsafe or inconsistent input and validate writes before completion.

## Test entry point

From the repository root:

```bash
bash database/run-tests.sh
```
