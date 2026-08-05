# Kane Condo Version 1 Scope

**Document status:** Proposed Batch 006 Version 1 scope contract  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `1074275`  
**Depends on:** `docs/PROJECT_CHARTER.md`, `docs/USER_WORKFLOW.md`, `docs/DATA_OWNERSHIP.md`, `docs/RUNTIME_TOPOLOGY.md`, `docs/SALVAGE_MANIFEST.md`  
**Implementation authorization:** None. This document fixes the Version 1 delivery boundary. It does not authorize repository scaffolding, donor-file transfer, database work, server work, rendering work, or deployment work.

## 1. Purpose

Kane Condo Version 1 must deliver one complete operational workflow:

> A project owner opens a continuous offline Kane County map from the shared USB, connects through the private network for authoritative editing, classifies individual building footprints as Other, Condominium, Apartments, or Unclassified, hides completed Other buildings, and can see whether fresher official county data is available.

Version 1 is not a demonstration, proof of concept, or partial map viewer.

It must be reliable enough to begin sustained county-wide building classification without creating a later data-conversion crisis.

This document separates:

- mandatory Version 1 capabilities;
- acceptable implementation freedom;
- explicit non-goals;
- postponed features;
- release blockers;
- Version 1 acceptance evidence.

## 2. Version 1 product boundary

Version 1 consists of five coordinated products:

1. **Authoritative Kane Condo database**
2. **Private application and processing services**
3. **Offline county render package**
4. **Windows and Ubuntu USB application runtime**
5. **Operational update and recovery workflow**

All five are required for Version 1 acceptance.

A map viewer without authoritative persistence is not Version 1.

A server database without an offline county map is not Version 1.

A classification interface without source-refresh reporting is not Version 1.

A development build that cannot operate from the project USB on the approved workstations is not Version 1.

## 3. Mandatory Version 1 user workflow

Version 1 must support the following end-to-end sequence:

1. Start Kane Condo from the USB on Windows or Ubuntu.
2. Validate the local application and offline package.
3. Open with the complete Kane County outline fitted to the viewport.
4. Render the county continuously without visible sectors, cells, tile boundaries, or loading grids.
5. Pan and zoom through the county.
6. Progressively show roads, water, creeks, and buildings according to useful scale.
7. Apply the published classification snapshot to building colors.
8. Show or hide Unclassified, Other, Condominium, and Apartments independently.
9. Connect to the private Kane Condo server through the approved WireGuard/proxy path.
10. Reach the approved editing scale.
11. Select one exact building footprint.
12. Confirm the current authoritative classification.
13. Deliberately choose a new classification.
14. Observe Pending, Saving, Saved, or Failed status truthfully.
15. Preserve the classification in SQLite/GeoPackage with append-only history.
16. Hide Other buildings and continue classification on the thinned map.
17. Check official-source update status from inside the application.
18. Observe processing, review, package-readiness, and failure states.
19. Install a complete validated offline package deliberately.
20. Retain or restore the previous working package if installation fails.

Every mandatory Version 1 component exists to support this sequence.

## 4. Mandatory classification model

Version 1 supports exactly four current building states:

| State | Color | Meaning |
|---|---|---|
| **Unclassified** | Gray | No explicit project decision is currently active |
| **Other** | Red | The building is not currently a condominium or apartment target |
| **Condominium** | Green | The project classifies the building as condominium property |
| **Apartments** | Yellow | The project classifies the building as apartment property |

Requirements:

- every project building begins Unclassified;
- Unclassified remains the database default;
- the user may explicitly return a classified building to Unclassified;
- every confirmed change creates history;
- corrections do not erase prior events;
- color follows authoritative or declared snapshot state;
- Pending state is visibly distinct from Saved state;
- no source attribute or algorithm silently creates an authoritative classification.

Version 1 does not require classification confidence, notes, citations, attachments, or legal evidence fields.

Those may be considered later without changing the four-state core.

## 5. Mandatory building identity

Version 1 must not attach classifications only to the current county `FPId`.

It requires:

- a Kane Condo project building identity;
- an initial deterministic mapping to the accepted official footprint;
- retained mapping history by source release;
- support for clear replacement and geometry-change continuity;
- explicit handling of added, removed, split, merged, and ambiguous footprints;
- preservation of classification history when an official identifier changes.

Version 1 may use conservative reconciliation rules.

It is acceptable for ambiguous cases to require explicit review.

It is not acceptable to guess and silently transfer or delete classifications.

## 6. Mandatory authoritative database

Version 1 uses SQLite, with GeoPackage spatial structures where required, as the authoritative data foundation.

The authoritative database must contain or represent:

- migration state;
- Kane County identity;
- approved source agencies;
- source profiles and versions;
- preserved source-release references;
- harvest and validation records;
- accepted county boundary release;
- accepted roads release;
- accepted Fox River release;
- accepted creeks release;
- accepted building release;
- immutable normalized source geometry;
- project building identities;
- official-footprint mappings;
- current classifications;
- append-only classification history;
- candidate comparisons;
- reconciliation decisions;
- release promotion history;
- package publication records;
- server and package compatibility identities.

The authoritative database must not contain an operational County Field Map classification ledger.

The new database must begin from a clean Kane Condo migration history.

## 7. Mandatory seed import

Version 1 may reuse the accepted county data produced by the donor project, but only through a verified seed import.

The seed import must:

- create a new Kane Condo database;
- open the donor GeoPackage read-only;
- verify the donor file identity;
- verify the expected source-release identities;
- verify boundary, roads, water, and building counts;
- import only approved canonical and provenance data;
- create Kane Condo project building identities;
- begin with zero explicit building classifications;
- import no discovered, muted, or undiscovered state;
- import no sector ledger;
- import no building-cell relation;
- import no orange-review records;
- leave the donor database unchanged.

A failed seed import must leave no accepted Kane Condo database.

## 8. Mandatory official-source registry

Version 1 must track the approved official sources for:

- Kane County boundary;
- building footprints;
- road centerlines;
- Fox River;
- creeks.

Each active profile must declare:

- dataset identity;
- source agency;
- official endpoint;
- expected geometry type;
- source stable-identity field;
- requested attributes;
- source coordinate system;
- pagination or object-inventory rules;
- validation rules;
- profile version;
- profile hash.

The exact source attributes may be expanded before the first Kane Condo harvest if needed for map level-of-detail decisions.

Any expansion creates a new profile version and does not rewrite the donor historical profile.

## 9. Mandatory source update detection

Version 1 must report source freshness from inside Kane Condo.

The server must support a lightweight check that can report:

- Up to date;
- New source detected;
- Source unavailable;
- Source changed unexpectedly;
- Last checked time;
- Last successful full harvest;
- current accepted release identity.

The browser must not contact the official ArcGIS sources directly.

The source check must not automatically download, accept, promote, publish, install, or activate new data.

## 10. Mandatory candidate harvesting

When authorized, Version 1 must be able to harvest complete candidates for all five tracked source profiles.

The harvest system must verify:

- endpoint identity;
- layer metadata;
- complete object-ID inventory;
- complete page or object-group retrieval;
- expected geometry type;
- finite coordinates;
- stable source identities;
- no duplicate required identities;
- canonical serialization;
- source manifest;
- byte length;
- SHA-256;
- exclusions, if any, with explicit audit records.

A partial or malformed harvest must not become a candidate release.

## 11. Mandatory candidate validation

Version 1 must validate candidate source evidence independently of the live retrieval process.

Validation must detect:

- missing source files;
- altered source files;
- altered manifests;
- incomplete object inventories;
- out-of-order or duplicated features when order is contractual;
- missing required attributes;
- invalid geometry;
- invalid coordinate ranges;
- source-profile mismatch;
- unexpected endpoint or layer identity;
- candidate counts outside approved safety rules;
- canonical serialization mismatch.

Validation failure leaves the accepted release unchanged.

## 12. Mandatory source comparison

Version 1 must compare a validated candidate with the currently accepted release.

For buildings, the minimum comparison categories are:

- added;
- removed;
- unchanged;
- geometry changed;
- attributes changed;
- geometry and attributes changed.

For county boundary, roads, Fox River, and creeks, Version 1 must at minimum report:

- prior and candidate feature counts;
- content-hash change;
- bounds change;
- added and removed source identities where stable identity is available;
- geometry or attribute change counts where practical;
- validation warnings requiring review.

The exact road and water comparison depth may differ from the building comparison, but replacement must never be blind.

## 13. Mandatory identity reconciliation

Before a new building release can be promoted, Version 1 must reconcile candidate official footprints with Kane Condo project building identities.

It must:

- preserve clear one-to-one continuity;
- create project identities for clear additions;
- preserve historical identities for removals;
- identify clear geometry redraws;
- detect potential splits;
- detect potential merges;
- detect uncertain replacements;
- isolate classifications affected by ambiguity;
- report unresolved cases.

Promotion policy may allow unrelated unambiguous updates to proceed only if the approved reconciliation contract defines how unresolved cases remain safe.

Version 1 must never silently erase or duplicate a Condominium, Apartments, or Other classification because of source geometry change.

## 14. Mandatory atomic promotion and rollback

Version 1 must construct and validate a candidate database separately from the accepted database.

Promotion must:

- occur only after complete validation;
- record the authorized action;
- create immutable release and promotion records;
- supersede rather than overwrite the prior accepted release;
- use an atomic file or transaction boundary;
- retain the prior accepted database until post-promotion verification passes;
- support rollback to the prior accepted database.

A failed or interrupted promotion must leave the prior accepted database operational.

## 15. Mandatory offline package

Version 1 must produce a complete offline Kane County render package for the USB.

The package must provide:

- immediate county outline;
- progressive road detail;
- progressive water and creek detail;
- progressive building detail;
- exact building footprints at editing scale;
- invisible spatial partitioning;
- building identity linkage;
- compact classification snapshot;
- package manifest;
- source release identities;
- database or build identity;
- component inventory;
- byte lengths;
- SHA-256 hashes;
- package-format version;
- minimum compatible application version.

The package must not require online map tiles or public mapping services.

## 16. Mandatory continuous map behavior

Version 1 must present one continuous map.

Required behavior:

- startup fits the complete county;
- pan and zoom are continuous;
- internal tiles, chunks, sectors, and indexes are invisible;
- major roads and major water orient the county overview;
- additional roads and creeks appear progressively;
- buildings appear according to useful screen scale;
- large footprints may appear before small footprints;
- all local buildings are present by neighborhood scale;
- exact geometry is available at editing scale;
- layer transitions do not blank or visibly partition the map.

The exact zoom thresholds are implementation decisions validated by workstation tests.

## 17. Mandatory local rendering

Version 1 renders the base county map entirely from USB-resident data.

The private server must not be required for:

- application startup;
- county outline;
- roads;
- water;
- creeks;
- buildings;
- pan;
- zoom;
- published classification colors;
- visibility filters;
- package identity inspection.

Network delay must not become map-rendering delay.

## 18. Mandatory building hit testing

At editing scale, Version 1 must reliably select one exact visible building footprint.

Required behavior:

- hidden buildings are excluded from selection;
- holes and multipolygons are handled correctly;
- adjacent buildings are distinguishable;
- uncertain selection requires more zoom instead of guessing;
- only one project building becomes active;
- selection alone does not change classification;
- the selected project identity is confirmed before save.

The exact rendering and hit-testing technology is deferred to the approved format and renderer decisions.

## 19. Mandatory editing gate

Version 1 enables classification only when:

- the map is at the approved editing scale;
- one exact project building is selected;
- the private API is reachable;
- client and server versions are compatible;
- the building identity is current and writable;
- no blocking maintenance or promotion condition exists.

Below editing scale, buildings may be inspected but not classified.

Server loss or compatibility failure disables authoritative editing without disabling the map.

## 20. Mandatory classification API

Version 1 must provide private server operations for:

- server health;
- compatibility;
- current classification lookup;
- classification write;
- classification history sufficient for audit;
- deliberate undo or correction support;
- update status;
- candidate summary;
- reconciliation-review status;
- package publication status.

The API must:

- be available only through the approved private network path;
- reject unauthenticated writes;
- validate project building identity;
- validate allowed classifications;
- use SQLite transactions;
- distinguish stale state, invalid identity, invalid class, unavailable database, and incompatible client;
- return a confirmed authoritative result.

The browser must not write directly to the database file.

## 21. Mandatory save lifecycle

Version 1 must expose these user-visible states:

- Current;
- Pending;
- Saving;
- Saved;
- Failed;
- Server unavailable;
- Server incompatible.

Rules:

- selecting a building does not create Pending state;
- choosing the current value creates no redundant write;
- a Pending color is not Saved;
- browser closure does not imply save;
- a failed or unconfirmed write leaves the prior authoritative state in force;
- a successful write creates classification history;
- the displayed color follows the confirmed state after save.

## 22. Mandatory visibility filters

Version 1 must provide independent controls for:

- Unclassified;
- Other;
- Condominium;
- Apartments.

Requirements:

- filter changes are local display state;
- hiding a class does not modify classifications;
- hidden buildings are excluded from pointer selection;
- showing a class restores it without server work;
- hiding Other visibly reduces the working population;
- filters operate both online and offline;
- unknown classification values default visibly to Unclassified.

Persisting filter preferences between sessions is optional for Version 1.

## 23. Mandatory rapid Other workflow

Version 1 must make repeated Other classification practical.

Minimum requirement:

- select one exact building;
- choose Other;
- receive truthful save status;
- continue to the next building;
- optionally hide Other immediately after save.

Version 1 may include safe keyboard shortcuts if approved during the editing milestone.

Version 1 does not require:

- drag selection;
- rectangle selection;
- mass classification;
- neighborhood-wide classification;
- automatic house classification;
- cell-based bulk actions.

Efficiency must not compromise exact building ownership or save truthfulness.

## 24. Mandatory correction and undo

Version 1 must allow:

- changing any current classification to another allowed classification;
- returning a building to Unclassified;
- preserving the prior classification in history;
- deliberate reversal of the most recent applicable change.

Undo may be limited to a well-defined recent action and may require the current server state to match the expected state.

Version 1 does not require arbitrary history rewriting.

## 25. Mandatory offline state

When disconnected, Version 1 must still provide:

- valid local application startup;
- county map;
- roads;
- water and creeks;
- buildings;
- published classification colors;
- filters;
- building inspection;
- active package and release identity;
- truthful server-unavailable status.

When disconnected, Version 1 must not provide authoritative editing.

Version 1 has no local pending-edit journal.

## 26. Mandatory update panel

Version 1 must make update state visible inside the application.

Minimum information:

- active local package identity;
- accepted county-data release identity;
- local classification snapshot identity;
- server reachability;
- last source check;
- source status for all tracked datasets;
- active processing stage;
- candidate change summary;
- identity-review requirement;
- package readiness;
- installed package versus available package;
- failure details sufficient for operator action.

Update information may be placed in a dedicated panel or screen, but it must remain part of the Kane Condo application.

## 27. Mandatory refresh processing states

Version 1 must distinguish at least:

- Offline;
- Up to date;
- New source detected;
- Queued;
- Harvesting;
- Validating;
- Comparing;
- Reconciling;
- Review required;
- Ready for promotion;
- Promoting;
- Packaging;
- Ready to install;
- Installed;
- Failed;
- Rolled back.

The exact internal job-state model may contain additional states.

The browser reports these states but does not execute heavy processing.

## 28. Mandatory ambiguity review

Version 1 must provide a bounded review workflow for building-source changes that affect project identity.

Review records must be tied to actual cases such as:

- split;
- merge;
- removed classified building;
- uncertain replacement;
- conflicting prior classifications;
- source identity discontinuity.

The review workflow must not:

- cover the entire county generically;
- depend on old cell states;
- color every affected sector orange;
- force reinspection of unrelated buildings;
- mutate classifications by opening a record.

The exact user interface may be simple in Version 1, but the review decision and its effect must be auditable.

## 29. Mandatory package publication

After accepted data or a published classification snapshot changes, Version 1 must be able to publish a compatible USB artifact.

A published artifact must be:

- complete;
- immutable;
- versioned;
- hashed;
- linked to the accepted database state;
- linked to the classification snapshot;
- distinguishable from staging output;
- available only after validation;
- retained according to rollback policy.

Classification-only snapshot publication may be separate from base geometry publication if the selected format supports it safely.

## 30. Mandatory package installation

Version 1 must have one reliable installation method for Windows and Ubuntu.

The first method may be:

- a local updater helper;
- a launcher-integrated updater;
- or a deliberate documented manual replacement.

It need not be browser-only.

It must:

1. obtain the complete published artifact;
2. stage it outside the active package;
3. verify manifest and hashes;
4. verify compatibility;
5. retain the current working package;
6. activate the new package atomically;
7. open and verify the new package;
8. preserve rollback if verification fails.

A partial download must not become active.

## 31. Mandatory local launcher or static server

Version 1 requires a supported method to serve the USB application from a local loopback origin on both Windows and Ubuntu.

The local runtime must:

- serve application assets;
- serve the selected offline package format;
- bind locally;
- prevent path traversal;
- open the correct start URL;
- provide clear startup failures;
- support the package sizes and access patterns selected by Batch 025;
- contain no County Field Map write API.

The exact runtime is not fixed by this document.

TrivialHTTP may be reused only if later testing proves it satisfies the selected format and security requirements.

## 32. Mandatory private network boundary

Version 1 authoritative services must remain on the approved WireGuard/proxy network.

Requirements:

- encrypted transport;
- server identity verification;
- no public unauthenticated write endpoint;
- no credentials in Git;
- no authoritative SQLite file shared directly to the workstation;
- explicit server health and compatibility check;
- write authorization;
- controlled refresh and promotion authorization.

A complex multi-user role system is not required.

## 33. Mandatory server backup and restore

Before Version 1 release, the authoritative database must have a tested backup and restore procedure.

It must preserve:

- migration state;
- project building identities;
- current classifications;
- classification history;
- official source release records;
- mapping history;
- reconciliation decisions;
- promotion history;
- package publication records.

A successful restore must reproduce the authoritative classification state exactly.

The USB is not the authoritative backup.

## 34. Mandatory cross-platform support

Version 1 supports:

- one approved Windows workstation configuration;
- one approved Ubuntu workstation configuration;
- the shared project USB;
- the designated private server environment;
- the designated Linux development and processing environment.

Version 1 does not require macOS support.

Cross-platform acceptance must use the actual user workflow, not only unit tests.

## 35. Mandatory operating documentation

Version 1 must include concise operator documentation for:

- starting Kane Condo on Windows;
- starting Kane Condo on Ubuntu;
- understanding local package validation;
- navigating the map;
- reaching editing scale;
- classifying a building;
- hiding Other;
- correcting a classification;
- understanding save status;
- working offline;
- checking for updates;
- interpreting refresh states;
- installing a package;
- rolling back;
- backing up and restoring server authority;
- reporting a failure.

Development documentation does not substitute for operator instructions.

## 36. Mandatory integrity and failure behavior

Version 1 must fail safely under:

- missing local package component;
- altered local package component;
- unsupported package version;
- private server unavailable;
- API incompatible;
- classification write interrupted;
- duplicate write request;
- database transaction failure;
- source unavailable;
- incomplete source harvest;
- malformed geometry;
- source-schema drift;
- failed candidate validation;
- ambiguous building reconciliation;
- package generation failure;
- package download interruption;
- package activation interruption;
- workstation shutdown;
- USB removal;
- server restart.

In each case, the last accepted authoritative database and last working local package must remain recoverable.

## 37. Version 1 performance boundary

Version 1 performance must be measured on the actual target workstations.

The following must be acceptable for sustained use:

- initial local application launch;
- county outline display;
- cross-county pan;
- continuous zoom;
- detail-band transitions;
- dense building rendering;
- building selection;
- classification-color update;
- filter application;
- API save confirmation;
- update-status refresh;
- package validation and activation.

Exact numeric thresholds are set during the format benchmark and read-only performance batches.

A feature is not accepted merely because it functions on the development host.

## 38. Version 1 data-quality boundary

Version 1 is a human classification tool.

It does not guarantee that:

- official building footprints are legally authoritative;
- a project classification is a legal condominium determination;
- an apartment classification reflects current occupancy;
- every official building exists physically;
- every physical building appears in the official source;
- official road or water geometry is complete forever.

Version 1 must preserve provenance and allow correction as better information becomes available.

The project’s authoritative claim is the classification decision and its history, not the legal status of the property.

## 39. Allowed implementation freedom

The following decisions remain open until their scheduled decision batches:

- server programming language and framework;
- process manager;
- API path design;
- exact authentication mechanism;
- exact GeoPackage table structure;
- use of GeoPackage RTree;
- offline spatial package format;
- vector-tile schema;
- canvas, WebGL, or other renderer;
- local static server;
- package updater mechanism;
- exact zoom levels;
- exact visual line widths;
- exact panel placement;
- keyboard shortcuts;
- snapshot publication frequency;
- server job scheduler;
- backup software;
- deployment layout.

An implementation choice is acceptable only if it satisfies the approved contracts and bounded acceptance tests.

## 40. Explicitly postponed — multi-user features

The following are postponed beyond Version 1:

- simultaneous classification by multiple users;
- collaborative cursors;
- record locking visible to multiple users;
- merge of concurrent classification histories;
- user roles;
- team dashboards;
- per-user assignments;
- workload distribution;
- user productivity metrics.

The database may retain minimal actor metadata if inexpensive, but Version 1 must not expand into a collaboration platform.

## 41. Explicitly postponed — offline editing

Postponed:

- USB-local pending classification journal;
- offline authoritative classification;
- later replay of offline changes;
- conflict resolution between local and server changes;
- multiple unsynchronized USB copies;
- portable editable SQLite classification database.

Version 1 disables editing when the server is unavailable.

## 42. Explicitly postponed — search and navigation aids

Postponed unless separately promoted through scope revision:

- street-address search;
- parcel-number search;
- owner-name search;
- municipality search;
- subdivision search;
- saved bookmarks;
- route planning;
- geolocation;
- GPS field use;
- navigation directions.

The continuous visual map is sufficient for Version 1.

## 43. Explicitly postponed — parcel and tax integration

Postponed:

- parcel polygons;
- tax parcel identifiers;
- assessor ownership records;
- taxpayer records;
- tax classifications;
- assessment history;
- legal descriptions;
- PIN-based building matching;
- parcel-to-building aggregation.

These may later improve evidence, but they are not required to start building classification.

## 44. Explicitly postponed — automatic classification

Postponed:

- automatic house detection;
- automatic condominium detection;
- automatic apartment detection;
- machine-learning classification;
- shape-based classification;
- parcel-class inference;
- address-pattern inference;
- bulk classification suggestions;
- confidence scoring.

The first authoritative classifications are deliberate human decisions.

## 45. Explicitly postponed — evidence attachments

Postponed:

- photos;
- documents;
- website captures;
- notes;
- citations;
- assessment records;
- legal filings;
- contact records;
- classification rationale fields.

Version 1 preserves classification history but not a full evidence dossier.

## 46. Explicitly postponed — public and external access

Postponed:

- public map;
- public API;
- external project-owner accounts;
- public downloads;
- public statistics;
- public comments;
- crowdsourced corrections;
- third-party integrations;
- mobile public access.

Version 1 is a private project tool.

## 47. Explicitly postponed — analytics and reporting

Postponed:

- classification totals dashboard;
- municipality summaries;
- condominium density maps;
- apartment density maps;
- progress charts;
- completion percentages;
- CSV reporting;
- public reports;
- change-over-time analytics.

Simple diagnostic counts required for validation and operation are allowed.

## 48. Explicitly postponed — editing official geometry

Postponed:

- drawing new building footprints;
- correcting county footprints;
- splitting or merging official geometry manually;
- editing roads;
- editing water;
- editing county boundary;
- publishing project-authored geometry as official geometry.

Identity reconciliation may map official versions without editing the official source representation.

## 49. Explicitly postponed — additional jurisdictions

Version 1 is Kane County only.

Postponed:

- adjacent counties;
- Illinois-wide coverage;
- state databases;
- national datasets;
- generic county configuration;
- multi-county UI;
- jurisdiction switching.

The internal design should avoid gratuitous hard-coding where simple, but Version 1 is not a general mapping platform.

## 50. Explicitly postponed — mobile and touch optimization

Version 1 targets desktop-class Windows and Ubuntu workstations.

Postponed:

- phone layouts;
- tablet-specific controls;
- touch-first hit testing;
- mobile offline storage;
- mobile WireGuard setup;
- field GPS workflows.

Basic browser responsiveness is acceptable, but mobile support is not an acceptance criterion.

## 51. Explicitly postponed — advanced administrative interface

Postponed:

- graphical source-profile editor;
- graphical database migration console;
- graphical server configuration;
- graphical backup scheduler;
- graphical log explorer;
- graphical user management;
- general-purpose GIS administration.

Version 1 may use controlled server commands for administration while reporting operational state through the application.

## 52. Explicitly postponed — automatic USB synchronization

Postponed unless the later package-installation design proves it bounded and safe:

- background automatic package download;
- automatic activation on startup;
- silent classification snapshot replacement;
- continuous USB synchronization;
- remote write access to arbitrary USB paths.

Version 1 prioritizes deliberate verified package activation.

## 53. Excluded permanently from this project identity

The following are not merely postponed; they conflict with the approved project:

- persistent county classification grid;
- discovered, muted, and undiscovered building-area states;
- Mute controls;
- opening a map area changing data;
- sector completion workflow;
- building-to-cell contradiction reviews;
- generic orange review overlay;
- direct browser writes to production SQLite;
- monolithic JSON as an assumed architectural requirement;
- online basemap dependency;
- public data harvesting from the workstation;
- treating official `FPId` as permanent project identity;
- patching Kane Offline Map into Kane Condo.

Any proposal to add one of these requires a project-charter revision, not a normal feature request.

## 54. Version 1 milestone inclusion

The planned milestones included in Version 1 are:

- Milestone 0 — Project contract;
- Milestone 1 — Canonical database;
- Milestone 2 — Refresh detection and safe promotion;
- Milestone 3 — Offline render package;
- Milestone 4 — Read-only continuous map;
- Milestone 5 — Real server and API;
- Milestone 6 — Building-editing workflow;
- Milestone 7 — In-application refresh reporting;
- Milestone 8 — Cross-platform deployment;
- Milestone 9 — Production hardening and release.

No milestone may be skipped because a later feature appears to work.

## 55. Version 1 release blockers

The following block Version 1 release:

1. Visible or operational County Field Map grid behavior.
2. Any navigation action that changes data.
3. Classification attached only to source `FPId`.
4. Missing append-only classification history.
5. Offline package requiring the private server to render.
6. Authoritative editing possible without confirmed persistence.
7. Unvalidated source data replacing accepted data.
8. No rollback for database promotion.
9. No rollback for USB package activation.
10. Ambiguous building refresh silently altering classifications.
11. Publicly exposed unauthenticated write API.
12. Monolithic county building load that fails target workstation performance.
13. Hidden Other buildings remaining pointer-selectable.
14. Pending classification displayed as Saved.
15. No tested server backup and restore.
16. Windows or Ubuntu package requiring development tools.
17. Missing package manifest or integrity validation.
18. Update state unavailable inside the application.
19. Failed update leaving the active map unusable.
20. Production data or secrets committed to Git.

## 56. Version 1 acceptance evidence

Version 1 acceptance requires recorded evidence for:

### Database

- clean migration from empty database;
- verified seed import;
- expected feature counts;
- zero initial explicit classifications;
- project building identity count;
- foreign-key check;
- SQLite integrity check;
- migration hash verification;
- backup and restore comparison.

### Source refresh

- update detection;
- complete candidate harvest;
- malformed candidate rejection;
- comparison report;
- identity reconciliation;
- ambiguous case handling;
- atomic promotion;
- rollback.

### Offline package

- deterministic or controlled reproducible build;
- component inventory;
- hashes;
- startup validation;
- progressive detail;
- package compatibility;
- activation;
- rollback.

### Application

- full-county startup;
- cross-county pan and zoom;
- dense building rendering;
- exact selection;
- classification save;
- failed-save handling;
- filters;
- Other thinning;
- offline viewing;
- server reconnection;
- update reporting.

### Deployment

- Windows USB test;
- Ubuntu USB test;
- server clean-install test;
- WireGuard/proxy access test;
- API authorization test;
- USB reconstruction test;
- operator-documentation walkthrough.

### Failure testing

- power interruption;
- network interruption;
- server restart;
- package corruption;
- source-schema drift;
- interrupted package activation;
- duplicate write;
- database write failure.

## 57. Version 1 completion definition

Version 1 is complete only when:

- every mandatory scope item is implemented and accepted;
- every release blocker is resolved;
- all required acceptance evidence is recorded;
- the repository matches the accepted release commit;
- the authoritative database is backed up;
- the server package is reproducible;
- Windows and Ubuntu USB packages are reproducible;
- the active package manifest is recorded;
- rollback procedures are tested;
- operator instructions are complete;
- the user explicitly approves release.

A large amount of classified data is not required before Version 1 release.

The system must be ready to preserve that work before county-wide classification begins.

## 58. Scope-change procedure

A proposed feature changes Version 1 scope only when:

1. it is described in writing;
2. its effect on the project charter is evaluated;
3. its database ownership is identified;
4. its runtime owner is identified;
5. its effect on offline rendering is evaluated;
6. its security and recovery effects are evaluated;
7. its milestone and bounded batches are added;
8. the project owner explicitly approves the revision;
9. the revision is committed before implementation.

Informal discussion does not silently expand Version 1.

## 59. Milestone 0 exit gate

Batch 006 completes the planned Milestone 0 documentation set.

Milestone 0 exits only when the project owner confirms that the following committed documents are mutually consistent:

```text
docs/PROJECT_CHARTER.md
docs/USER_WORKFLOW.md
docs/DATA_OWNERSHIP.md
docs/RUNTIME_TOPOLOGY.md
docs/SALVAGE_MANIFEST.md
docs/V1_SCOPE.md
```

The exit decision must explicitly authorize moving from documentation into Milestone 1 planning.

Approval of Batch 006 alone confirms the Version 1 boundary. It does not automatically authorize Batch 007 implementation.

## 60. Acceptance checklist

Batch 006 is accepted when the project owner confirms:

- Version 1 is a complete operational system, not only a viewer;
- SQLite/GeoPackage remains authoritative;
- project building identity is mandatory;
- continuous offline rendering is mandatory;
- server-connected authoritative editing is mandatory;
- update detection and refresh reporting are mandatory;
- validated candidate promotion and rollback are mandatory;
- USB package installation and rollback are mandatory;
- Windows and Ubuntu are mandatory;
- offline editing is postponed;
- multi-user support is postponed;
- search, parcels, automation, evidence attachments, analytics, and public access are postponed;
- the County Field Map architecture is excluded;
- the listed release blockers are correct;
- Milestone 0 is complete only after this document is committed and explicitly approved as a set with the other five contracts.

Approval of this document does not authorize implementation.
