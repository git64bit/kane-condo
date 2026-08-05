# Kane Condo Salvage Manifest

**Document status:** Proposed Batch 005 donor-asset disposition  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `d4b166b`  
**Donor project:** `git64bit/kane-offline-map`  
**Donor source snapshot:** `0911eeefeafbb18c58af0618200ba9edead29bdc`  
**Depends on:** `docs/PROJECT_CHARTER.md`, `docs/USER_WORKFLOW.md`, `docs/DATA_OWNERSHIP.md`, `docs/RUNTIME_TOPOLOGY.md`  
**Implementation authorization:** None. This document approves or rejects donor assets conceptually. It does not authorize copying, renaming, editing, importing, migrating, or executing donor code.

## 1. Purpose

Kane Offline Map contains valuable county-data work and an application layer that pursued the wrong operational object.

Kane Condo must recover the valuable work without inheriting the failed architecture.

This manifest assigns every important donor asset to one of four dispositions:

1. **Preserve unchanged**
2. **Adapt into Kane Condo**
3. **Preserve as external seed or historical evidence only**
4. **Reject from Kane Condo**

The controlling rule is:

> Salvage the county-data acquisition, provenance, geometry, validation, and release-management work. Do not salvage the cell-classification application.

## 2. Donor snapshot boundary

All salvage decisions in this document refer to the exact donor commit:

```text
0911eeefeafbb18c58af0618200ba9edead29bdc
```

No later unreviewed `kane-offline-map` commit, patch, prototype, or generated archive is automatically included.

The failed Batch 024 prototype is excluded from the donor boundary.

The source snapshot must remain available as read-only reference material outside the `kane-condo` working tree.

## 3. Current external seed inventory

The completed donor pipeline produced an accepted GeoPackage with the following known identity:

```text
Path:
  /root/kane-offline-data/database/kane-county.gpkg

Byte length:
  324,886,528

SHA-256:
  7fe2198b00b2d0dee9470eda3864b43b6f7b3b0ff3b236ce7c579ddc077f389a
```

Known accepted browser-export counts from that database:

| Dataset | Feature count | Export byte length | Export SHA-256 |
|---|---:|---:|---|
| County boundary | 1 | 14,524 | `c2ad82a91d5e99423560d8b0d2bc6ade418d85a8c28fd97bf94617d5dd94963c` |
| Roads | 27,675 | 15,183,443 | `ff7a5a64647ba7e381ffdbe26c97e96ca17de2633a598ccf44b81b3554dc2ee1` |
| Water | 556 | 8,538,859 | `45e364bf95a79dcc385dba48bc2a7401498f5198313c52b3ff9b849d23ce3e8e` |
| Buildings | 208,324 | 104,302,521 | `e33ab35105526c2675456ed3a2feda80a8d5b8f2264b9ea174b9d4198eb933e6` |

Known accepted source-release identities:

```text
County boundary:
  kane-county-boundary-20230509-73cb32426b22

Roads:
  kane-roads-20250730-028e3c1dc7a6

Fox River:
  kane-water-fox-river-20250717-905d93f928d2

Creeks:
  kane-water-creeks-20250717-249c70f01dbc

Buildings:
  kane-buildings-20250730-086f09eba5ad
```

These identities are evidence of the accepted donor state. They do not establish the future Kane Condo schema or package format.

## 4. Disposition meanings

### 4.1 Preserve unchanged

The asset is valid as an immutable contract, evidence record, or historical file.

Preserve unchanged does not necessarily mean commit the asset to `kane-condo`. Its destination is stated explicitly.

### 4.2 Adapt into Kane Condo

The asset contains valuable logic or structure but cannot be copied wholesale.

Adaptation requires:

- a separately authorized implementation batch;
- a stated destination path;
- removal of donor-project coupling;
- new tests;
- review against the Kane Condo contracts;
- commit reconciliation before further work.

### 4.3 Preserve as external seed or historical evidence only

The asset is useful as input, evidence, comparison material, or recovery material, but it must not become active Kane Condo source or live runtime state.

### 4.4 Reject from Kane Condo

The asset encodes the wrong application purpose, unsafe coupling, obsolete workflow, or unsuitable runtime format.

Rejected assets remain in donor history. They are not deleted from the donor repository, but they are not copied into Kane Condo.

## 5. Preserve unchanged

### 5.1 Donor commit identity

Preserve unchanged:

```text
0911eeefeafbb18c58af0618200ba9edead29bdc
```

Purpose:

- fixes the exact source review boundary;
- permits later file-level comparison;
- prevents accidental salvage from an unreviewed donor state.

Destination:

- record in Kane Condo documentation and transfer logs;
- do not copy the donor Git history into Kane Condo.

### 5.2 Official endpoint identities

Preserve unchanged as historical source-contract evidence:

```text
database/sources/kane-county-boundary.json
database/sources/kane-county-buildings.json
database/sources/kane-county-roads.json
database/sources/kane-county-fox-river.json
database/sources/kane-county-creeks.json
```

The exact endpoint URLs, geometry types, identity fields, coordinate system, page size, and copyright text produced the accepted seed releases.

Disposition detail:

- preserve the exact five donor profile files with their original hashes in the external source-evidence area;
- do not silently edit them in place;
- any active Kane Condo profile change creates a new versioned profile;
- the active profile registry is implemented later under Batch 016.

Important limitation:

- the road, Fox River, creek, and boundary profiles collect only `OBJECTID`;
- the road profile therefore does not provide road class, route type, or road name for semantic overview styling;
- a future expanded road profile must be a new profile version, not an edit that changes the identity of the historical accepted contract.

### 5.3 Preserved harvest pairs

Preserve unchanged outside Git:

```text
<dataset>.geojson
<dataset>.geojson.manifest.json
```

for each accepted source release.

Purpose:

- immutable source evidence;
- exact source-file byte identity;
- future acceptance verification;
- audit of exclusions and retrieval completeness.

Rule:

- do not reconstruct these files from the GeoPackage and claim they are original harvest evidence;
- do not overwrite them with a newer harvest;
- newer source retrieval creates a new pair.

### 5.4 Accepted release identities and hashes

Preserve unchanged:

- release keys;
- source profile hashes;
- source-file hashes;
- source content hashes;
- harvest timestamps;
- source publication timestamps;
- accepted timestamps;
- source URIs;
- audited road missing-geometry exclusion inventory.

These values become seed-import provenance in the new database.

### 5.5 License history

The donor license and attribution history remain preserved in the donor repository.

The new repository already has its own license. Any future copied donor source must retain legally required notices.

No license file transfer is required in Batch 005.

## 6. Adapt into Kane Condo — ArcGIS acquisition

### 6.1 `database/tools/county_arcgis.py`

**Disposition:** Adapt.

Valuable capabilities:

- standard-library HTTP retrieval;
- profile validation;
- layer metadata validation;
- complete object-ID inventory retrieval;
- bounded object-ID group requests;
- exact page-to-request identity checking;
- stable source identity validation;
- canonical JSON serialization;
- adjacent manifest generation;
- missing-geometry exclusion policy;
- candidate-file promotion;
- failure isolation.

Required adaptation:

- move into a Kane Condo acquisition namespace;
- remove donor command and path assumptions;
- version its manifest contract explicitly;
- expose lightweight source-status metadata for the application update service;
- distinguish update detection from full harvest;
- integrate with the new server job and provenance models;
- retain network access only on server-side infrastructure.

Do not copy before:

- Batch 007 repository skeleton;
- Batch 009 administrative provenance;
- Batch 016 source profile registry.

### 6.2 `database/tools/county_geojson.py`

**Disposition:** Adapt.

Valuable capabilities:

- ArcGIS-to-GeoJSON geometry contract;
- polygon and polyline validation;
- finite coordinate validation;
- minimum ring and path rules;
- geometry-type rejection.

Required adaptation:

- move into a project-neutral geometry validation module;
- retain strict rejection behavior;
- add tests for every active Kane Condo source profile;
- keep it independent of County Field Map cells.

### 6.3 `database/tools/county_harvest.py`

**Disposition:** Adapt.

Valuable capabilities:

- offline validation of a harvested GeoJSON/manifest pair;
- source-profile contract comparison;
- source object inventory validation;
- exclusion inventory validation;
- deterministic release-key creation;
- published and harvested timestamp checks.

Required adaptation:

- target the new provenance schema;
- support the update-status and candidate lifecycle;
- record source-check evidence separately from full harvest evidence;
- remove donor project naming.

### 6.4 Harvest shell wrappers

Donor files:

```text
database/harvest-kane-boundary.sh
database/harvest-kane-buildings.sh
database/harvest-kane-roads.sh
database/harvest-kane-fox-river.sh
database/harvest-kane-creeks.sh
database/validate-kane-boundary-harvest.sh
database/validate-kane-building-harvest.sh
database/validate-kane-road-harvest.sh
database/validate-kane-fox-river-harvest.sh
database/validate-kane-creek-harvest.sh
database/validate-source-profile.sh
```

**Disposition:** Adapt patterns, not files.

Valuable pattern:

- explicit input/output paths;
- `set -eu`;
- direct Python entry point;
- no dependency on preserved executable bits;
- no workstation execution.

Required adaptation:

- one Kane Condo command surface;
- server-job integration;
- explicit external data root;
- no hard-coded donor database path;
- consistent source-status, harvest, validate, and accept commands.

## 7. Adapt into Kane Condo — GeoPackage foundation

### 7.1 `database/migrations/0001_geopackage_core.sql`

**Disposition:** Adapt substantially, using the SQL as a reviewed starting point.

Valuable content:

- migration ledger;
- GeoPackage spatial reference system table;
- GeoPackage contents table;
- geometry-column metadata;
- EPSG:4326 registration.

Required adaptation:

- create a new Kane Condo migration numbered from its own clean history;
- verify GeoPackage conformance requirements;
- avoid treating the donor migration hash as a Kane Condo migration hash;
- add only extensions actually required by the chosen runtime and tooling.

### 7.2 `database/migrations/0002_administration.sql`

**Disposition:** Adapt.

Valuable concepts:

- project settings;
- county identity;
- source agencies;
- datasets;
- source releases;
- source files;
- harvest runs;
- one accepted release per dataset;
- candidate, accepted, superseded, and rejected states.

Required adaptation:

- align lifecycle states with update detection, processing, review, promotion, publication, and failure reporting;
- distinguish lightweight source checks from full harvest runs;
- support server jobs and package publication;
- preserve immutable accepted-release history;
- add any explicit profile-version reference required by the new source registry.

### 7.3 `database/migrations/0004_refresh_control.sql`

**Disposition:** Adapt concepts only.

Valuable concepts:

- refresh issues;
- release promotion records;
- candidate-safe promotion history.

Required adaptation:

- remove assumptions tied to donor release construction;
- add Kane Condo update-state reporting;
- support promotion authorization and rollback;
- record server job identity;
- link building-identity reconciliation results;
- separate candidate failure from accepted state.

### 7.4 `database/tools/county_db.py`

**Disposition:** Adapt architecture, not wholesale implementation.

Valuable capabilities:

- ordered migrations;
- migration hash validation;
- candidate database construction;
- SQLite foreign-key and integrity validation;
- distinct validation modes;
- database information reporting.

Required adaptation:

- new Kane Condo schema;
- no classification ledger requirement;
- no grid calibration requirement;
- no review-bundle requirement;
- explicit project-building identity and classification validation;
- clean separation of migration, seed import, refresh, package, and API concerns;
- server-safe database path ownership.

### 7.5 `database/tools/county_cli.py`

**Disposition:** Adapt command-dispatch pattern.

Valuable capability:

- one public command surface for database operations.

Required adaptation:

- create a new Kane Condo command vocabulary;
- avoid donor commands such as ledger import, spatial calibration, open-review export, or prepared-core export;
- align each command with a bounded milestone;
- keep browser and workstation outside the command-line processing path.

## 8. Adapt into Kane Condo — canonical source geometry

### 8.1 `database/migrations/0005_source_buildings.sql`

**Disposition:** Adapt.

Valuable concepts:

- immutable building rows grouped by source release;
- source feature ID;
- source ordinal;
- geometry BLOB;
- geometry type;
- geometry, attributes, and content hashes;
- numeric bounds;
- release-specific uniqueness;
- native GeoPackage feature registration.

Required adaptation:

- retain official source identity as release identity;
- add or support mapping to Kane Condo project building identity;
- ensure official geometry remains immutable;
- preserve complete source attributes selected by the active profile;
- support efficient spatial indexing or package generation without cell relations.

### 8.2 `database/tools/county_buildings.py`

**Disposition:** Adapt.

Valuable capabilities:

- strict Polygon and MultiPolygon normalization;
- ring validation;
- GeoPackage geometry construction;
- canonical attributes;
- per-feature hashes;
- numeric bounds;
- deterministic source order;
- duplicate identity rejection.

Required adaptation:

- target the clean Kane Condo building-release schema;
- preserve holes and multipolygon ownership correctly;
- produce the future project-building mapping input;
- remove any path or validation dependency on classification releases;
- add source-profile versioning and seed-import support.

### 8.3 `database/migrations/0008_county_boundary.sql`

**Disposition:** Split.

Adapt:

- `source_county_boundary`;
- release linkage;
- geometry hashes;
- attributes;
- bounds;
- GeoPackage registration.

Reject:

```text
ALTER TABLE classification_grid_calibration ...
classification_grid_boundary_release
```

Reason:

- the first half is valid county geometry;
- the second half couples boundary data to the obsolete County Field Map grid.

The Kane Condo boundary migration must be written cleanly and must not carry the grid alteration.

### 8.4 `database/tools/county_boundary.py`

**Disposition:** Adapt.

Valuable capabilities:

- one-feature boundary normalization;
- deterministic geometry and content hashes;
- candidate-safe acceptance;
- accepted-boundary validation;
- GeoPackage geometry verification;
- extent reporting.

Required adaptation:

- remove accepted-building and grid-calibration coupling;
- target the new provenance and boundary schema;
- support full-county startup extent and package generation.

### 8.5 `database/migrations/0009_map_layers.sql`

**Disposition:** Adapt.

Valuable concepts:

- immutable release-grouped road and water geometry;
- LineString, MultiLineString, Polygon, and MultiPolygon support;
- source order;
- canonical attributes;
- content hashes;
- bounds;
- GeoPackage registration.

Required adaptation:

- decide whether roads and water remain in one general feature table or receive typed tables;
- support later release comparison and supersession;
- support level-of-detail package generation;
- retain dataset identity explicitly.

### 8.6 `database/tools/county_map_layers.py`

**Disposition:** Adapt.

Valuable capabilities:

- line and polygon normalization;
- GeoPackage geometry construction;
- canonical source attributes;
- candidate-safe acceptance of roads, Fox River, and creeks;
- complete geometry and hash validation;
- extent updates.

Required adaptation:

- implement later road/water refresh semantics;
- remove deployment validation requiring County Field Map classification;
- provide inputs for the future offline render package;
- retain atomic coordination for related water datasets.

## 9. Adapt into Kane Condo — release comparison

### 9.1 `database/migrations/0006_building_refresh.sql`

**Disposition:** Adapt.

Valuable concepts:

- comparison between previous and candidate building releases;
- added;
- removed;
- unchanged;
- geometry changed;
- attributes changed;
- combined modification;
- immutable previous and candidate references;
- aggregate count validation.

Required adaptation:

- comparison cannot end at exact source `FPId`;
- add a separate project-building reconciliation stage;
- preserve source comparison as evidence;
- distinguish source-feature change from project-identity change;
- support split, merge, replacement, disappearance, and reappearance.

### 9.2 `database/tools/county_building_refresh.py`

**Disposition:** Adapt.

Valuable capabilities:

- candidate-copy upgrade;
- deterministic source-release comparison;
- failed candidate isolation;
- accepted-release supersession;
- exact change recording;
- validation of comparison counts and content.

Required adaptation:

- target the new migration history;
- integrate project identity mapping;
- prevent automatic classification loss;
- produce application-visible candidate summaries;
- isolate ambiguous identity cases;
- support atomic promotion and rollback.

### 9.3 Refresh shell scripts

Donor files:

```text
database/build-kane-harvest-database.sh
database/refresh-kane-harvest-database.sh
database/build-building-database.sh
database/refresh-building-database.sh
database/accept-kane-boundary.sh
database/accept-kane-map-layers.sh
```

**Disposition:** Adapt workflow patterns.

Do not copy the exact scripts because:

- paths and command names belong to the donor schema;
- building, boundary, roads, and water acceptance must target the new database;
- accepted candidates must include project-identity reconciliation;
- update processing is exposed through the private server.

## 10. Adapt into Kane Condo — geometry utilities

### 10.1 `database/tools/county_geometry.py`

**Disposition:** Split.

Adapt:

- GeoPackage geometry decoding;
- Polygon and MultiPolygon decoding;
- LineString and MultiLineString decoding;
- point-in-polygon logic if later required;
- reusable geometry validation helpers.

Reject from active transfer:

- rectangle-intersection logic copied solely for County Field Map cell relations;
- any assumption that a practical cell is a persistent application object.

A future rendering or hit-testing module may use the general geometry portions after benchmark and test review.

### 10.2 Bounds indexes

The donor uses numeric `min_x`, `min_y`, `max_x`, and `max_y` columns and indexes.

**Disposition:** Adapt as a baseline.

The final Kane Condo schema may use:

- numeric bounds;
- GeoPackage RTree indexes;
- package-time spatial partitioning;
- or a combination.

The choice is deferred to database and render-format milestones.

## 11. Adapt into Kane Condo — tests

### 11.1 Strong donor tests

Adapt the contracts represented by:

```text
database/tests/test_arcgis.py
database/tests/test_boundary_harvest.py
database/tests/test_harvest_acceptance.py
database/tests/test_linear_harvest.py
database/tests/test_boundary_acceptance.py
database/tests/test_buildings.py
database/tests/test_map_layers.py
```

Valuable coverage:

- source profile validation;
- complete object inventories;
- canonical harvest output;
- malformed geometry rejection;
- missing-geometry exclusion auditing;
- immutable source-pair validation;
- candidate-safe acceptance;
- source-file provenance;
- geometry and content tampering detection;
- failed candidate preservation.

Required adaptation:

- new package imports;
- new migration schema;
- new dataset lifecycle;
- no classification ledger;
- no review rows.

### 11.2 Partial donor tests

Adapt selected ideas from:

```text
database/tests/test_database.py
database/tests/test_prepared_core.py
database/tests/test_portable_archive.py
```

Keep:

- migration hash checks;
- SQLite integrity;
- foreign-key validation;
- deterministic generated output;
- component inventory;
- byte-length and SHA-256 verification;
- candidate-safe output replacement;
- dirty-tree or source-identity protection where appropriate.

Do not keep:

- requirement for accepted cell classification;
- donor application payload list;
- donor package root and schema;
- monolithic GeoJSON as the assumed final render format;
- review-bundle exclusions as a product rule.

### 11.3 Rejected donor tests

Do not transfer tests whose purpose is the obsolete workflow:

```text
database/tests/test_browser_review.py
database/tests/test_review_bundle.py
database/tests/test_review_export.py
database/tests/test_spatial.py
```

Their existence remains useful historical evidence of what the donor implemented, but the tested behavior is not Kane Condo behavior.

## 12. Adapt into Kane Condo — deterministic output principles

### 12.1 `database/tools/county_prepared.py`

**Disposition:** Adapt principles, reject exact export format.

Valuable principles:

- read accepted database in read-only mode;
- decode geometry from the accepted GeoPackage;
- canonical serialization;
- deterministic feature order;
- feature counts;
- byte lengths;
- SHA-256 hashes;
- candidate directory;
- validation before promotion;
- refusal to overwrite without deliberate force.

Reject as the final Kane Condo renderer input:

```text
county_boundary.json
roads.json
water.json
buildings.json
```

Reason:

- the building file is approximately 104 MB uncompressed;
- all buildings are represented as one monolithic browser object;
- the format does not implement progressive levels of detail;
- it does not provide invisible viewport partitioning;
- it does not separate stable base geometry from a replaceable classification snapshot;
- it was built for the donor application.

The accepted prepared files remain useful as validation and interchange evidence.

### 12.2 `deployment/tools/portable_archive.py`

**Disposition:** Adapt packaging discipline, reject exact payload contract.

Valuable principles:

- complete payload inventory;
- source commit identity;
- deterministic path order;
- fixed ZIP metadata;
- byte length and SHA-256 for every file;
- candidate archive;
- archive self-validation;
- unexpected-file rejection;
- overwrite refusal;
- atomic promotion.

Reject:

- project name `kane-offline-map`;
- donor root directory;
- donor browser payload list;
- review-bundle manual addition;
- TrivialHTTP manual-addition model;
- County Field Map storage directories;
- monolithic prepared-core requirement.

The future Kane Condo package builder is defined only after Batch 025 selects the render format.

### 12.3 Deployment shell wrappers

Donor files:

```text
deployment/build-deployment-archive.sh
deployment/build-portable-archive.sh
```

**Disposition:** Adapt command and candidate-build patterns only.

Do not copy before:

- offline format selection;
- package manifest contract;
- deterministic package generation milestone.

## 13. Adapt into Kane Condo — local static server

### 13.1 Potentially reusable TrivialHTTP files

Potential donor files:

```text
trivialhttp/src/trivialhttp.c
trivialhttp/src/platform.c
trivialhttp/src/http.c
trivialhttp/src/trivialhttp.h
trivialhttp/scripts/build-linux.sh
trivialhttp/scripts/build-windows-mingw.sh
```

**Disposition:** Evaluate and adapt only if selected later.

Potentially valuable capabilities:

- loopback binding;
- local static-file serving;
- MIME handling;
- browser launch;
- `--root`;
- `--open`;
- Linux build;
- Windows cross-build;
- path containment.

Required review before reuse:

- confirm no sector-storage dependency remains in request routing;
- confirm safe large tile/chunk serving;
- confirm byte-range requirements of the selected offline format;
- confirm cache headers;
- confirm Windows and Ubuntu behavior;
- confirm failure messages and process shutdown;
- confirm no write endpoint is exposed.

No TrivialHTTP source transfer is authorized in Batch 005.

### 13.2 Rejected TrivialHTTP components

Reject:

```text
trivialhttp/src/sector_storage.c
```

Reject the endpoint contracts:

```text
/__county_field_map/sector-state
/__kane_map/sector-state
```

Reject the storage location:

```text
project-data/sectors
```

Reason:

- they write County Field Map classification ledgers;
- they have no role in Kane Condo;
- authoritative Kane Condo writes belong to the private server API.

## 14. Preserve as external seed only

### 14.1 Accepted donor GeoPackage

Preserve externally:

```text
/root/kane-offline-data/database/kane-county.gpkg
```

Purpose:

- seed source for the first Kane Condo canonical database;
- comparison reference;
- accepted source geometry and provenance;
- validation reference.

Restrictions:

- do not rename it as the live Kane Condo database;
- do not serve it directly to the browser;
- do not continue applying donor migrations;
- do not delete donor classification tables in place and call the result clean;
- do not commit it to Git.

The first Kane Condo database must be newly created from the Kane Condo migration history and selectively seeded from validated donor tables and external source evidence.

### 14.2 Prepared browser exports

Preserve externally:

```text
county_boundary.json
roads.json
water.json
buildings.json
core-manifest.json
```

Purpose:

- independent feature-count check;
- geometry visualization reference;
- export hash evidence;
- render-format benchmark input;
- regression comparison.

Restrictions:

- not the final runtime format;
- not the authoritative database;
- not committed to Git;
- not loaded as one monolithic production map unless Batch 025 benchmarking unexpectedly proves that acceptable.

### 14.3 Completed deployment ZIP

Preserve as historical evidence:

```text
/root/kane-offline-data/deployment/kane-offline-map.zip
```

Known identity:

```text
Byte length:
  34,353,261

SHA-256:
  aa90fa7fbae207a077c54f43550061a8c9470b20742f1a9e33d671e93a830d2d
```

Purpose:

- proof that the donor data bundle was complete and portable;
- visual reference for road, creek, water, and building rendering;
- package-integrity reference.

Restriction:

- not a Kane Condo deployment base;
- not copied into the new repository;
- not patched into the Kane Condo application.

### 14.4 County Field Map sector archive

Donor file:

```text
database/input/sectors.zip
```

**Disposition:** Historical evidence and possible VOID-mask research input only.

Permitted future use:

- Batch 026 may audit its alignment and decide whether it safely reduces exported geometry.

Prohibited use:

- no visible grid;
- no user classification;
- no building classification ownership;
- no automatic exclusion before the alignment audit;
- no direct import into the Kane Condo canonical schema as active classification data.

### 14.5 Donor review outputs

Any existing open-review exports or bundles are preserved only as historical diagnostics.

They are not seed data for Kane Condo.

## 15. Reject — donor classification schema

Reject completely:

```text
database/migrations/0003_classification.sql
```

Including:

- `classification_release`;
- `classification_sector`;
- `classification_cell`;
- `classification_review`;
- discovered, muted, and undiscovered states;
- practical-cell counts;
- sector completion counts.

Reason:

- the classified object is a cell;
- Kane Condo classifies buildings;
- carrying this schema forward would recreate the original architectural error.

## 16. Reject — spatial cell calibration and relations

Reject completely:

```text
database/migrations/0007_spatial_cell_index.sql
database/tools/county_grid.py
database/tools/county_spatial.py
database/calibrate-spatial-database.sh
database/validate-spatial-database.sh
```

Including:

- `classification_grid_calibration`;
- `classification_cell_spatial`;
- `building_cell_relation`;
- 512×512 practical-cell geography;
- cell-boundary intersection;
- building-to-cell review generation.

Reason:

- Kane Condo has no persistent classification grid;
- map chunks or tiles are implementation details, not data owners;
- the failed orange review layer originated from this coupling.

## 17. Reject — completed ledger import

Reject from Kane Condo:

```text
database/tools/county_ledger.py
database/build-ledger-database.sh
database/validate-ledger-database.sh
docs/JSON_TO_GEOPACKAGE_MIGRATION.md
```

The completed County Field Map ledger remains historical input only for the later VOID audit.

It must not become a Kane Condo table or user workflow.

## 18. Reject — donor review system

Reject:

```text
database/tools/county_review_export.py
database/tools/county_review_bundle.py
database/export-open-reviews.sh
database/export-open-review-bundle.sh
docs/REVIEW_EXPORT.md
docs/REVIEW_BUNDLE.md
docs/REVIEW_BROWSER.md
data/reviews/
```

Reason:

- reviews are generated from building-to-cell contradictions;
- the browser review records are read-only;
- the overlay does not resolve identity ambiguity;
- the system implies missed buildings without proving that conclusion;
- it has no relationship to Kane Condo’s legitimate refresh reconciliation.

A future Kane Condo review system is limited to ambiguous source changes affecting project building identity or classifications.

## 19. Reject — donor browser application

Reject as a Kane Condo application base:

```text
index.html
styles/app.css
src/app.js
src/constants.js
src/grid.js
src/stateStore.js
src/reviewBundleLoader.js
src/reviewOverlay.js
```

Reason:

- the interface is a County Field Map classification ledger;
- it contains Mute, Return to undiscovered, and Mute all 64 cells;
- it mutates classification during navigation;
- it stores sector state;
- it exposes review cells;
- it navigates through persistent sector, inspection, and practical-cell levels.

The browser application must be rewritten from the Kane Condo charter.

## 20. Partial rejection — donor renderer and loader

### 20.1 `src/dataLoader.js`

**Disposition:** Reject as a module; retain only as visual reference.

Useful observations:

- county boundary, roads, water, and buildings were successfully decoded for browser drawing;
- feature bounds were used for viewport filtering;
- accepted data can render without online basemap services.

Reasons not to transfer:

- monolithic files are loaded before viewport filtering;
- the format is not the approved future offline package;
- building geometry handling is not designed around project building identity and exact editing;
- donor application assumptions are embedded.

### 20.2 `src/renderer.js`

**Disposition:** Reject as a module; retain small algorithms as reference only.

Potential reference ideas:

- Canvas coordinate transformation;
- pan and zoom;
- road, water, and building drawing;
- geometry clipping by bounds;
- local rendering without a network basemap.

Reasons not to transfer:

- renderer states are organized around county sectors and cells;
- classification colors represent cell states;
- review overlays are embedded;
- selection ownership is wrong;
- no building-centered editing contract exists.

Any future reuse of a mathematical fragment requires a new implementation batch and test.

## 21. Reject — donor application state storage

Reject:

```text
src/stateStore.js
project-data/sectors/
deployment/SECTOR_STORAGE_README.txt
```

Reason:

- stores cell-ledger state;
- writes belong to the wrong application;
- Kane Condo classification authority is the private server database;
- Version 1 has no offline edit queue.

## 22. Reject — exact donor deployment interface

Reject:

```text
deployment/START-URL.txt
deployment/USB_DEPLOYMENT_README.txt
deployment/TRIVIALHTTP_RUNTIME_README.txt
deployment/SECTOR_STORAGE_README.txt
portable_config.js
```

Reason:

- the URL and configuration request the donor prepared bundle and review path;
- the runtime instructions assume the donor application;
- the storage documentation belongs to County Field Map compatibility.

Concepts such as a local launch URL and USB instructions will be recreated later for Kane Condo.

## 23. Reject — donor verification aggregate

Reject as an executable Kane Condo verifier:

```text
verify-linux.sh
CHECKSUMS.sha256
TEST_RESULTS.txt
BASELINE.txt
```

Preserve them in donor history as evidence.

Reason:

- checksums identify the donor tree;
- tests include rejected classification and review behavior;
- package expectations belong to Kane Offline Map;
- the new repository requires a new verifier built incrementally from accepted Kane Condo batches.

Valuable pattern to adapt later:

- one bounded Linux verification entry point;
- explicit test inventory;
- no network requirement for deterministic tests;
- no Python bytecode artifacts in delivery.

## 24. Reject — donor batch narratives as project instructions

Do not copy:

```text
BATCH_005.md
...
BATCH_023.md
README.md
database/README.md
docs/BUILDING_SOURCE_IMPORT.md
docs/DATABASE_ARCHITECTURE.md
docs/DEVELOPMENT_WORKFLOW.md
docs/HARVEST_ACCEPTANCE.md
docs/MAP_LAYER_ACCEPTANCE.md
docs/PREPARED_CORE_EXPORT.md
docs/PORTABLE_ARCHIVE.md
```

as controlling Kane Condo documentation.

They may be consulted as historical technical evidence.

Reason:

- project identity and required database completeness are donor-specific;
- several documents treat classification cells as mandatory;
- Kane Condo already has new controlling contracts.

Useful material must be rewritten into Kane Condo documentation rather than copied as authoritative text.

## 25. File-group disposition table

| Donor asset group | Disposition | Future destination or use |
|---|---|---|
| Exact donor commit | Preserve unchanged | Documentation and transfer ledger |
| Five original source profiles | Preserve unchanged as historical contracts; adapt active registry later | External evidence; Batch 016 |
| Harvested GeoJSON/manifest pairs | Preserve unchanged externally | Source evidence |
| Accepted donor GeoPackage | External seed only | Batch 015 seed import |
| `county_arcgis.py` | Adapt | Source acquisition service |
| `county_geojson.py` | Adapt | Geometry validation |
| `county_harvest.py` | Adapt | Harvest-pair validation |
| GeoPackage core migration | Adapt | New Kane Condo migration |
| Administration migration | Adapt | New provenance schema |
| Refresh control migration | Adapt concepts | New job/promotion schema |
| Source building migration/tool | Adapt | Official building releases |
| Boundary migration/tool | Split and adapt | County boundary |
| Map layer migration/tool | Adapt | Roads and water |
| Building comparison migration/tool | Adapt | Source comparison and identity reconciliation |
| General geometry decoding | Adapt selectively | Database/package/renderer utilities |
| Strong acquisition tests | Adapt | New test suite |
| Prepared exporter | Adapt principles only | Render-package generator after Batch 025 |
| Portable archive builder | Adapt principles only | Deployment package after format decision |
| TrivialHTTP static core | Evaluate later | Local launcher/server if approved |
| TrivialHTTP sector storage | Reject | None |
| Classification migration | Reject | None |
| Grid calibration and building-cell relation | Reject | None |
| Ledger import | Historical only | VOID audit input |
| Review export/bundle/browser | Reject | None |
| Donor HTML/application/state | Reject | None |
| Donor renderer/loader | Reference only | New renderer design |
| Donor deployment templates | Reject | New Kane Condo deployment |
| Donor checksums/verifier | Historical only | New verifier later |
| Donor batch documentation | Historical reference only | New Kane Condo docs |

## 26. Transfer protocol for future batches

No donor source file is copied merely because this manifest marks it Adapt.

For each future transfer batch:

1. Identify the exact donor file and donor commit.
2. State the Kane Condo destination.
3. State which functions or schema concepts are being retained.
4. State which donor dependencies are removed.
5. Write or update Kane Condo tests first or in the same bounded batch.
6. Copy only complete reviewed files.
7. Run the bounded test set.
8. Deliver the complete new and changed files.
9. User tests and commits.
10. Reconcile against the supplied commit SHA.
11. Record the transfer in a future provenance or donor ledger if required.

A donor file must not enter Kane Condo through an unrelated batch.

## 27. Seed-import protocol

The accepted donor GeoPackage is not upgraded into Kane Condo.

The later seed import must:

1. Create a new empty Kane Condo database from Kane Condo migrations.
2. Open the donor GeoPackage read-only.
3. Verify its byte length and SHA-256.
4. Verify accepted source release identities.
5. Verify expected feature counts and bounds.
6. Import only approved administration, provenance, boundary, road, water, and building content.
7. Create Kane Condo project building identities.
8. Create zero explicit classifications.
9. import no classification grid;
10. import no building-cell relation;
11. import no review rows;
12. validate the new database independently;
13. leave the donor database byte-for-byte unchanged.

## 28. VOID-mask protocol

The County Field Map ledger is not automatically trusted as a geometry-removal mask.

Batch 026 must determine:

- whether grid coordinates align exactly with accepted source geometry;
- whether the prior browser projection introduced error;
- whether building intersections near cell boundaries were misinterpreted;
- whether roads and water would be broken by exclusion;
- whether VOID should remove geometry, suppress package creation, or be rejected entirely;
- whether any building can be excluded without an independent geometry test.

Until that audit passes:

- no accepted building is removed from the Kane Condo seed;
- no road or water geometry is clipped by the ledger;
- no user-visible map behavior depends on the ledger.

## 29. Risks carried forward

The salvage work retains these known risks for later resolution:

### 29.1 Official building identity

`FPId` is stable enough for donor release comparison but is not permanent project identity.

Resolution:

- Batch 013 project building identity;
- Batch 023 reconciliation.

### 29.2 Road detail attributes

The accepted road profile collects only `OBJECTID`.

Resolution:

- determine whether geometry-only level-of-detail is sufficient;
- otherwise version and harvest an expanded road profile.

### 29.3 Road and water refresh

The donor accepted first road and water releases but intentionally refused later refresh.

Resolution:

- define comparison and supersession before live refresh promotion.

### 29.4 Monolithic browser export

The donor building export is approximately 104 MB.

Resolution:

- Batch 025 format benchmark;
- spatially partitioned or tiled offline package.

### 29.5 Browser building ownership

The donor browser was not designed for exact project-building selection.

Resolution:

- new renderer;
- exact hit testing;
- editing-scale gate;
- server-confirmed project identity.

### 29.6 VOID alignment

The failed orange review layer indicates that the grid-to-building relationship cannot be assumed correct.

Resolution:

- Batch 026 audit before any removal.

## 30. What Kane Condo receives from the donor

After approved adaptation, Kane Condo may receive:

- proven official-source acquisition logic;
- immutable harvest evidence;
- strict geometry validation;
- accepted county boundary;
- complete road geometry;
- complete water and creek geometry;
- complete building footprints;
- release provenance;
- candidate-safe database construction;
- building source-release comparison;
- deterministic integrity and packaging discipline;
- Linux-first processing and cross-platform delivery patterns.

Kane Condo does not receive:

- the donor cell classifier;
- the donor map hierarchy;
- the donor review overlay;
- the donor state store;
- the donor application interface;
- the donor database as a live database;
- the donor deployment package as a patch target.

## 31. Core salvage invariants

The following must remain true:

1. The donor commit boundary is fixed.
2. The donor database remains read-only seed evidence.
3. Kane Condo starts with a new migration history.
4. No donor classification table enters the new schema.
5. No donor cell relation owns a building.
6. No review bundle enters the new user workflow.
7. No donor browser module is copied wholesale.
8. Official source evidence remains external and immutable.
9. Adapted acquisition logic remains server-side.
10. Workstations do not perform harvesting or processing.
11. Generated monolithic JSON is not assumed to be the final renderer format.
12. Project building identity is added before classifications are relied upon.
13. Existing county geometry and provenance are preserved.
14. Every donor transfer occurs in a separately authorized batch.
15. Approval of this manifest does not authorize copying.

## 32. Acceptance checklist

Batch 005 is accepted when the project owner confirms:

- the donor boundary is commit `0911eeefeafbb18c58af0618200ba9edead29bdc`;
- the accepted GeoPackage and source harvests are preserved externally;
- the new database will be created cleanly rather than modifying the donor database;
- acquisition, validation, provenance, geometry, and comparison work are salvageable;
- the exact donor classification, grid, review, browser, and sector-storage systems are rejected;
- the current prepared JSON is reference data, not the final package decision;
- TrivialHTTP is only a possible future local static-server donor;
- the County Field Map ledger is only an unaudited VOID-mask input;
- no donor file transfer is authorized yet.

Approval of this document completes the salvage decision but does not authorize implementation.
