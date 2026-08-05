# Kane Condo Development Milestones

**Status:** Planning document only. No implementation is authorized by this document.

## 1. Fixed project purpose

Kane Condo is a single-user building-classification application for Kane County.

The application must:

- open with the full county outline fitted to the screen;
- present one continuous, Google-Maps-like pan-and-zoom experience;
- render county boundary, roads, water/creeks, and building footprints from an offline package;
- allow building classification only at the maximum editing scale;
- classify buildings as **Unclassified**, **Other**, **Condominium**, or **Apartments**;
- use gray, red, green, and yellow respectively;
- allow **Other** buildings to be hidden so the remaining map progressively thins;
- retain manual classifications independently of official county building identifiers;
- use SQLite/GeoPackage as the authoritative data store;
- report official-source update availability from inside the application;
- perform harvesting, validation, comparison, reconciliation, and package generation on the server;
- keep rendering operational from the USB even when the server is unavailable.

The application must not expose or reproduce County Field Map classification behavior. There is no visible sector grid, 16×16 grid, 8×8 grid, mute state, discovered state, undiscovered state, automatic cell update, or generic orange review layer.

## 2. Delivery discipline

Every implementation batch is intentionally small enough to complete, test, deliver, and reconcile in one bounded cycle.

The required cycle is:

1. Discuss one batch.
2. Confirm the exact scope and acceptance test.
3. User explicitly authorizes implementation.
4. Implement only that batch.
5. Run its bounded tests.
6. Deliver complete new and changed files in a ZIP.
7. User tests.
8. User commits to `kane-condo`.
9. User supplies the commit SHA.
10. Reconcile against that SHA before discussing the next implementation batch.

Rules:

- No batch begins from an unconfirmed repository state.
- No batch combines database, server, renderer, and user-interface changes unless it is explicitly an end-to-end integration batch.
- No future batch is implemented in anticipation of approval.
- Failed batches are not extended. Recovery returns to the last accepted commit.
- Donor code from `kane-offline-map` is copied only when a salvage decision has already been documented and approved.
- The large county database, harvested source files, generated tiles, and deployment packages remain outside Git.

---

# Milestone 0 — Lock the project contract

**Purpose:** Eliminate architectural ambiguity before any code enters the new repository.

## Batch 001 — Project charter

**Deliverable:** `docs/PROJECT_CHARTER.md`

Define the purpose, single-user operating model, classification categories and colors, offline rendering requirement, server processing requirement, and explicit exclusions.

**Acceptance:** Every statement matches the approved discussion. No unnecessary implementation choice is introduced.

**Stop point:** Review and commit the charter only.

## Batch 002 — User workflow

**Deliverable:** `docs/USER_WORKFLOW.md`

Define the normal sequence:

1. open full county;
2. pan and zoom;
3. buildings progressively appear;
4. reach editing scale;
5. select one building;
6. assign a classification;
7. save;
8. optionally hide Other;
9. continue classification.

Also define inspection-only behavior below editing scale and behavior when the server is unreachable.

**Acceptance:** Opening, zooming, panning, or selecting for inspection never changes data.

## Batch 003 — Data ownership contract

**Deliverable:** `docs/DATA_OWNERSHIP.md`

Separate official county source data, accepted canonical county releases, project-owned building identities, manual classifications, classification history, offline render packages, and USB-local temporary state.

**Acceptance:** A future county refresh cannot silently erase a Condominium or Apartments classification.

## Batch 004 — Runtime topology decision

**Deliverable:** `docs/RUNTIME_TOPOLOGY.md`

Define the responsibilities of the orchestrator, real web/API server, WireGuard/proxy network, USB, local workstation browser, and optional local static server.

Resolve whether editing requires a live server connection or whether a USB-local pending journal is required.

**Acceptance:** Every read, write, processing task, and file location has one owner.

## Batch 005 — Salvage manifest

**Deliverable:** `docs/SALVAGE_MANIFEST.md`

List exact donor assets under four headings:

- preserve unchanged;
- adapt;
- preserve as external seed only;
- reject.

Include the accepted GeoPackage, source profiles, harvesting logic, provenance model, road/water/building data, current deployment exports, obsolete grid schema, obsolete review workflow, and current browser code.

**Acceptance:** Nothing is copied merely because it already exists.

## Batch 006 — Version 1 boundary

**Deliverable:** `docs/V1_SCOPE.md`

Version 1 should include the county map, progressive layer visibility, classification, filters, server persistence, update detection, validated refresh, offline package replacement, and rollback.

Postpone multi-user access, public access, advanced search, parcel integration, address lookup, and statistical reporting unless explicitly promoted into scope.

**Milestone 0 exit gate:** The six documents are approved and committed. No unresolved question changes the database ownership, runtime topology, or primary workflow.

---

# Milestone 1 — Establish the canonical database

**Purpose:** Create a clean Kane Condo GeoPackage/SQLite foundation without importing obsolete grid behavior.

## Batch 007 — Repository and migration skeleton

Create only the minimum project structure required for migrations, tests, documentation, and repeatable command entry points.

**Acceptance:** A clean checkout can run a no-op verification command. No county data or application code is added.

## Batch 008 — GeoPackage core

Add the GeoPackage core metadata and migration ledger.

**Acceptance:** A new empty database is standards-valid and records the exact migration state.

## Batch 009 — Administrative provenance

Add county, source agency, dataset, source profile, source release, source file, and harvest-run records.

**Acceptance:** A release can be traced to its official source, source metadata, harvest time, byte length, and SHA-256 hash.

## Batch 010 — County boundary storage

Add the accepted county boundary feature model and release association.

**Acceptance:** The seed county boundary imports with the expected feature count, bounds, and hash.

## Batch 011 — Roads and water storage

Add road, Fox River, creek, and other accepted water feature storage without any grid dependency.

**Acceptance:** Imported counts and geometry bounds match the accepted seed database.

## Batch 012 — Official building-release storage

Add immutable official building releases and source-footprint identity.

**Acceptance:** All accepted source building footprints import without duplicate current-release identity.

## Batch 013 — Project building identity

Add a Kane Condo identity independent of county `FPId`, plus mapping between project identity and official-release footprints.

**Acceptance:** Initial import creates a deterministic one-to-one mapping while allowing future split, merge, replacement, and renumbering cases.

## Batch 014 — Classification and history

Add current classification and append-only classification history.

Classifications:

- Unclassified;
- Other;
- Condominium;
- Apartments.

**Acceptance:** Unclassified is the default and does not require a redundant row for every building. Every explicit change is auditable.

## Batch 015 — Seed import and audit report

Import the approved county seed data from the external GeoPackage into the new schema.

**Acceptance report must include:** feature counts, release identities, source hashes, geometry bounds, number of project building identities, zero explicit classifications, and confirmation that no classification grid or review records were imported.

**Milestone 1 exit gate:** The new database independently represents the accepted county map and zero-state Kane Condo classifications.

---

# Milestone 2 — Build refresh detection and safe promotion

**Purpose:** Make official data freshness observable without allowing an unvalidated source change to replace accepted data.

## Batch 016 — Source profile registry

Transfer and normalize the approved county boundary, buildings, roads, Fox River, and creeks source profiles.

**Acceptance:** Each profile identifies the official endpoint, stable source identifier, requested fields, geometry type, and validation rules.

## Batch 017 — Lightweight update check

Implement a source-status check that detects likely upstream change without downloading the full dataset.

**Acceptance:** The check reports Up to date, New source detected, Source unavailable, or Source changed unexpectedly.

## Batch 018 — Building candidate harvest

Harvest a complete building candidate into an external staging area.

**Acceptance:** Object inventory, feature count, stable IDs, serialization, and source hashes validate before candidate registration.

## Batch 019 — Road candidate harvest

Harvest and validate a complete road candidate.

**Acceptance:** No accepted road release is changed.

## Batch 020 — Water candidate harvest

Harvest and validate Fox River and creek candidates as one coordinated water update.

**Acceptance:** Partial water updates cannot be promoted.

## Batch 021 — County boundary candidate harvest

Harvest and validate a boundary candidate.

**Acceptance:** Unexpected geometry type, county identity, or gross bounds rejects the candidate.

## Batch 022 — Candidate comparison

Compare each candidate with its accepted release. For buildings, report added, removed, unchanged, geometry changed, attributes changed, and both changed.

**Acceptance:** Comparison is deterministic and repeatable.

## Batch 023 — Project-identity reconciliation

Map the new building release to existing Kane Condo building identities. Automatically handle clear one-to-one matches. Isolate ambiguous split, merge, replacement, and disappearance cases.

**Acceptance:** Existing classifications remain attached unless an ambiguity is explicitly reported.

## Batch 024 — Atomic promotion and rollback

Promote a fully validated candidate database atomically and retain the previous accepted database until the new one passes post-promotion verification.

**Acceptance:** An interrupted or failed promotion leaves the accepted database usable.

**Milestone 2 exit gate:** The system can detect, harvest, validate, compare, reconcile, promote, and roll back official data without a browser application.

---

# Milestone 3 — Define and generate the offline render package

**Purpose:** Produce a seamless county map package that avoids monolithic JSON loading.

## Batch 025 — Render-format benchmark

Evaluate the current county dataset using a controlled benchmark of candidate offline formats.

Compare startup time, zoom performance, building hit testing, package size, Windows and Ubuntu support, update replacement complexity, and the ability to apply classification colors without regenerating all base geometry.

**Acceptance:** One format is selected in a written decision record. No full renderer is built.

## Batch 026 — VOID-mask audit

Verify the County Field Map VOID result against accepted building, road, and water geometry.

Check coordinate alignment, cell-boundary behavior, false exclusion risk, continuity of roads and water, and whether the mask removes geometry or only controls packaging.

**Acceptance:** The mask is either approved with explicit rules or rejected. It is never exposed in the Kane Condo interface.

## Batch 027 — County overview layer

Generate the low-detail county outline and overview metadata.

**Acceptance:** The full county can be fitted immediately without loading detailed roads or buildings.

## Batch 028 — Road levels of detail

Generate progressively detailed road representations.

**Acceptance:** Major roads orient the county view; the complete network appears at close scale without visible chunk boundaries.

## Batch 029 — Water levels of detail

Generate progressively detailed Fox River, water, and creek representations.

**Acceptance:** Major water is visible at overview scale; detailed creeks appear as zoom increases.

## Batch 030 — Building levels of detail

Generate building data that appears progressively according to usable screen size and zoom.

**Acceptance:** Large buildings appear before small houses, all buildings are available by neighborhood scale, and exact footprints are available at editing scale.

## Batch 031 — Classification snapshot

Generate a compact offline classification snapshot keyed by Kane Condo project building identity.

**Acceptance:** The base geometry package does not need to be regenerated after every classification change.

## Batch 032 — Package manifest and integrity

Create a versioned render-package manifest containing database release identity, package format version, source release identities, tile/chunk inventory, byte lengths, hashes, creation time, and classification snapshot identity.

**Acceptance:** Missing or altered package components are detected before use.

## Batch 033 — Reproducible package build

Build the same package twice from the same accepted database and compare outputs.

**Acceptance:** Outputs are deterministic where practical; intentionally variable metadata is isolated and documented.

**Milestone 3 exit gate:** A validated offline county package exists independently of the final user interface.

---

# Milestone 4 — Build the read-only continuous map

**Purpose:** Prove the map experience before any editing or server write behavior is introduced.

## Batch 034 — Minimal application shell

Create the browser shell, configuration loader, status reporting, and local package validation.

**Acceptance:** The application either opens a valid package or reports a precise integrity/compatibility error.

## Batch 035 — Full-county opening view

Fit the county outline to the viewport on startup.

**Acceptance:** Startup presents the complete county, not an arbitrary tile or prior sector.

## Batch 036 — Continuous pan and zoom

Implement smooth pan and zoom with no visible grid, sector, tile, or loading boundary.

**Acceptance:** Navigation has no data side effects.

## Batch 037 — Progressive road rendering

Connect the road levels of detail to zoom.

**Acceptance:** The transition between detail bands is visually stable and does not blank the map.

## Batch 038 — Progressive water rendering

Connect water and creek levels of detail to zoom.

**Acceptance:** Major water remains useful at county scale and complete detail appears at close scale.

## Batch 039 — Progressive building rendering

Add building footprints according to the approved appearance rules.

**Acceptance:** County scale is not overwhelmed; every building is present at neighborhood/editing scale.

## Batch 040 — Classification colors

Apply gray, red, green, and yellow from the offline classification snapshot.

**Acceptance:** Unknown or missing classification data defaults safely to Unclassified gray.

## Batch 041 — Visibility filters

Add independent visibility controls for Unclassified, Other, Condominium, and Apartments.

**Acceptance:** Hiding Other removes red buildings from rendering and hit testing without changing their stored classification.

## Batch 042 — Read-only performance acceptance

Test startup, county overview, cross-county panning, rapid zoom, and dense urban areas on the target Windows and Ubuntu workstations.

**Acceptance:** Performance targets are recorded and met before editing is added.

**Milestone 4 exit gate:** The application is a useful, continuous, offline, read-only Kane County building map.

---

# Milestone 5 — Establish the real server and API

**Purpose:** Add authoritative persistence and refresh reporting without coupling rendering to the network.

## Batch 043 — Server technology decision

Choose the smallest maintainable server stack that can safely provide SQLite transactions, authentication, update jobs, and package publication.

**Acceptance:** The decision includes deployment, backup, dependency, and long-term maintenance implications.

## Batch 044 — Health and compatibility API

Provide server health, API version, database version, and render-package compatibility status.

**Acceptance:** The client can distinguish offline, incompatible, degraded, and healthy states.

## Batch 045 — Classification read API

Read classifications and modification metadata by project building identity.

**Acceptance:** The response does not expose or depend on County Field Map cells.

## Batch 046 — Classification write API

Write one classification change in a SQLite transaction.

**Acceptance:** Invalid identity, invalid class, stale request, and database failure return distinct errors; successful writes create history.

## Batch 047 — Undo/history API

Expose the previous classification state and allow a deliberate undo.

**Acceptance:** Undo creates a new history event rather than deleting history.

## Batch 048 — Update-status API

Expose current accepted releases, last source checks, detected updates, processing state, validation results, and package readiness.

**Acceptance:** The client can report updates without running processing locally.

## Batch 049 — Network and access control

Define the WireGuard/proxy path, origin rules, authentication, and server exposure boundary.

**Acceptance:** The API is not publicly exposed and rejects unauthenticated writes.

## Batch 050 — Database backup and restore

Create verified server-side backup and restore procedures for classifications and project identity.

**Acceptance:** A restored database reproduces current classifications and history exactly.

**Milestone 5 exit gate:** The server can safely read/write classifications and report refresh state while the map remains fully offline.

---

# Milestone 6 — Add the building-editing workflow

**Purpose:** Turn the proven read-only map into the intended classifier.

## Batch 051 — Building hit testing

Select the exact visible building footprint at close scale.

**Acceptance:** Dense adjacent buildings can be distinguished reliably.

## Batch 052 — Editing-scale gate

Define the maximum editing scale numerically and disable classification below it.

**Acceptance:** Zooming and inspection below the threshold cannot alter data.

## Batch 053 — Selection presentation

Highlight the selected building and optionally recenter it without hiding neighboring context.

**Acceptance:** Selection is visually clear without adding a persistent grid.

## Batch 054 — Classification controls

Add Unclassified, Other, Condominium, and Apartments controls.

**Acceptance:** The current state is explicit; no classification changes until the user chooses a class.

## Batch 055 — Save lifecycle

Implement Pending, Saving, Saved, Failed, and Server unavailable states.

**Acceptance:** The map never implies that an unsaved classification is authoritative.

## Batch 056 — Rapid Other workflow

Optimize the repeated task of marking obvious buildings as Other while preventing accidental bulk mistakes. Keyboard shortcuts may be considered only after the basic click workflow is accepted.

**Acceptance:** A user can classify many obvious buildings efficiently and hide them immediately.

## Batch 057 — Correction and undo

Allow a mistaken classification to be corrected and the most recent change to be undone.

**Acceptance:** Every correction remains visible in history.

## Batch 058 — Server-unavailable behavior

When the server cannot be reached, preserve offline rendering and disable authoritative editing unless Batch 004 explicitly approved a pending-change journal.

**Acceptance:** Network failure cannot create silent unsaved edits.

## Batch 059 — Editing pilot

Test a small, representative set of rural, suburban, industrial, municipal, condominium, and apartment areas.

**Acceptance:** The workflow is accepted before county-wide classification begins.

**Milestone 6 exit gate:** The user can accurately classify buildings and progressively thin the map by hiding Other.

---

# Milestone 7 — Put refresh reporting inside the application

**Purpose:** Make data freshness operationally visible without performing heavy processing in the browser.

## Batch 060 — Updates panel

Display accepted release, package version, classification snapshot version, last check time, and server reachability.

**Acceptance:** The user can tell exactly what data the USB is displaying.

## Batch 061 — Check for updates action

Request a fresh source-status check from the server.

**Acceptance:** The action reports Up to date, New source detected, Source unavailable, or Source changed unexpectedly.

## Batch 062 — Processing status

Display queued, harvesting, validating, comparing, reconciling, packaging, ready, and failed states.

**Acceptance:** Long server work is observable without keeping the browser responsible for execution.

## Batch 063 — Candidate summary

Display feature counts and building change categories before promotion.

**Acceptance:** A new source release is never presented merely as “update available” without meaningful scope.

## Batch 064 — Ambiguous building review

Present only ambiguous changes affecting existing Kane Condo building identities or classifications.

**Acceptance:** There is no generic county-wide orange warning layer.

## Batch 065 — Promotion authorization

Provide an explicit action for accepting a validated candidate after required ambiguities are resolved.

**Acceptance:** Detection alone never replaces accepted data.

## Batch 066 — Offline package publication

Publish the validated package and classification snapshot for the USB.

**Acceptance:** The package is complete, hashed, version-compatible, and linked to the promoted database release.

## Batch 067 — USB installation procedure

Define the first reliable installation method. It may initially be a deliberate manual replacement rather than premature browser automation.

**Acceptance:** Installation is atomic and retains the previous working package until the new package opens successfully.

## Batch 068 — Rollback reporting

Expose the active package, previous package, and rollback result.

**Acceptance:** A failed update leaves the last accepted map usable.

**Milestone 7 exit gate:** Update availability, processing, review, promotion, installation, and rollback are understandable from the Kane Condo application.

---

# Milestone 8 — Cross-platform deployment

**Purpose:** Make the system reproducible on the actual infrastructure and user workstations.

## Batch 069 — Server deployment package

Create the reproducible server installation for the designated WireGuard/proxy host.

**Acceptance:** A clean server can be installed, migrated, configured, and verified from documented inputs.

## Batch 070 — Windows USB package

Create the complete Windows user package.

**Acceptance:** It runs from the USB without development tools and opens the correct local map.

## Batch 071 — Ubuntu USB package

Create the complete Ubuntu user package.

**Acceptance:** It runs from the USB without development tools and opens the same package and classifications.

## Batch 072 — Browser compatibility

Verify supported browser versions and required local-server behavior.

**Acceptance:** Unsupported environments fail clearly rather than partially loading.

## Batch 073 — Package integrity and recovery

Verify startup behavior for missing, altered, partial, and incompatible local packages.

**Acceptance:** No corrupted package is used silently.

## Batch 074 — USB backup procedure

Define how the active package and any approved USB-local state are backed up before replacement.

**Acceptance:** A failed or damaged USB can be reconstructed from authoritative server data and published packages.

## Batch 075 — Operational documentation

Create concise operator instructions for starting the application, classifying buildings, hiding Other, checking updates, installing a package, rolling back, and reporting failures.

**Milestone 8 exit gate:** The complete system operates on the real server, Windows USB, and Ubuntu USB.

---

# Milestone 9 — Production hardening and version 1 acceptance

**Purpose:** Verify failure behavior before county-wide classification becomes dependent on the system.

## Batch 076 — Power-loss test

Interrupt classification writes, package generation, package download, and package installation.

**Acceptance:** SQLite remains consistent and the previous package remains usable.

## Batch 077 — Network-loss test

Disconnect WireGuard during startup, navigation, classification, update checking, and saving.

**Acceptance:** Offline rendering continues; write status remains truthful.

## Batch 078 — Source-schema drift test

Simulate renamed fields, missing fields, changed geometry types, duplicated IDs, and incomplete official responses.

**Acceptance:** The candidate is rejected without altering accepted data.

## Batch 079 — Building identity stress test

Test renumber, redraw, split, merge, disappearance, and reappearance scenarios.

**Acceptance:** Clear mappings transfer automatically and ambiguous mappings require explicit review.

## Batch 080 — Large classification-set performance

Test rendering and lookup after a substantial fraction of the county is marked Other.

**Acceptance:** Hiding Other materially thins the map without degrading interaction.

## Batch 081 — Full refresh rehearsal

Run a complete synthetic refresh from detection through USB package installation and rollback.

**Acceptance:** Every state and artifact is accounted for.

## Batch 082 — Version 1 acceptance

Verify the approved charter and V1 scope line by line.

**Acceptance:** No County Field Map behavior is present; the application performs the intended building-classification workflow.

## Batch 083 — Version 1 release

Create the reproducible release, release manifest, database backup, server package, Windows package, Ubuntu package, and operator documentation.

**Milestone 9 exit gate:** Kane Condo version 1 is ready for sustained county-wide classification.

---

# 3. Decision gates that must not be bypassed

Implementation must stop for explicit approval at these points:

1. After Batch 006: project meaning and system boundaries.
2. After Batch 015: database ownership and seed import.
3. After Batch 025: offline package format.
4. After Batch 033: generated package integrity and performance.
5. After Batch 042: read-only map usability.
6. After Batch 050: server persistence and security.
7. After Batch 059: actual classification workflow.
8. After Batch 068: refresh and package replacement.
9. After Batch 075: real cross-platform operation.
10. Before Batch 083: final production release.

No later milestone should be used to conceal an unresolved defect in an earlier milestone.

# 4. Recommended immediate next action

The next authorized work should be **Batch 001 only: Project charter**.

It is documentation, not code. After the charter is reviewed and committed, proceed to Batch 002. The first code batch is Batch 007 and must not begin until Milestone 0 is complete and explicitly approved.
