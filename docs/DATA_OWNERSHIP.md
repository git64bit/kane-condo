# Kane Condo Data Ownership Contract

**Document status:** Proposed Batch 003 data-ownership contract  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `55250d9`  
**Depends on:** `docs/PROJECT_CHARTER.md`, `docs/USER_WORKFLOW.md`  
**Implementation authorization:** None. This document defines data authority, ownership, derivation, retention, and transfer boundaries. It does not authorize schema implementation, data copying, migration work, server deployment, or application development.

## 1. Purpose

Kane Condo depends on several kinds of data that have different owners and different lifecycles.

This document prevents them from being mixed together.

It defines:

- which data is official source evidence;
- which data is accepted project reference data;
- which identities belong to Kane Condo;
- which records are authoritative;
- which files are derived products;
- which data may exist only as local workstation preferences;
- what survives an official county refresh;
- what may be regenerated;
- what must never be silently overwritten;
- what must remain outside Git.

The controlling principle is:

> Official county data describes the map. Kane Condo data records the project’s decisions about buildings.

## 2. Ownership categories

Kane Condo recognizes six primary data-ownership categories:

1. **Official source evidence**
2. **Accepted canonical county data**
3. **Kane Condo project identity**
4. **Kane Condo classification data**
5. **Derived offline products**
6. **Local non-authoritative user state**

These categories may reference one another, but they must remain logically and operationally distinct.

## 3. Authority hierarchy

When two representations disagree, authority is determined by the following hierarchy:

1. **Kane Condo authoritative SQLite/GeoPackage database**
   - authoritative for accepted county releases;
   - authoritative for project building identities;
   - authoritative for current classifications;
   - authoritative for classification history;
   - authoritative for refresh and promotion history.

2. **Preserved official source evidence**
   - authoritative evidence of what the external source delivered;
   - not automatically accepted as current project data.

3. **Published offline package**
   - authoritative only as a signed or hashed snapshot of a particular accepted database state;
   - not authoritative for new edits after publication.

4. **USB-local cache or preferences**
   - never authoritative for county releases or confirmed classifications unless a later approved offline-editing contract explicitly says otherwise.

5. **Browser-rendered appearance**
   - never a source of record;
   - color alone does not constitute a saved classification.

## 4. Official source evidence

### 4.1 Definition

Official source evidence is the preserved material retrieved from Kane County or another approved official source.

It may include:

- source profile used for retrieval;
- endpoint identity;
- source metadata;
- object-ID inventory;
- retrieved feature data;
- response manifests;
- retrieval timestamps;
- source-reported edit dates;
- byte lengths;
- cryptographic hashes;
- validation logs.

### 4.2 Ownership

Official source evidence belongs to the external source in origin, but Kane Condo owns the preserved project copy and its chain of custody.

The project must preserve enough evidence to answer:

- what source was contacted;
- when it was contacted;
- what was retrieved;
- whether retrieval was complete;
- whether the preserved bytes changed;
- which candidate and accepted release used the evidence.

### 4.3 Storage

Official source evidence remains in the controlled external data area on the server infrastructure.

It must not be committed to Git.

Git may contain:

- source-profile definitions;
- validation rules;
- schema definitions;
- test fixtures small enough for source control;
- documentation.

Git must not contain:

- full county harvests;
- production GeoPackages;
- generated map packages;
- project-owner classification databases;
- server backups.

### 4.4 Immutability

Once a source harvest is registered by content hash, its preserved source files are immutable.

A later source check creates a new harvest. It does not modify the prior evidence.

### 4.5 Acceptance boundary

Retrieved source evidence is not automatically accepted county data.

It must pass the approved sequence:

1. complete retrieval;
2. validation;
3. candidate construction;
4. comparison;
5. identity reconciliation;
6. explicit promotion.

## 5. Accepted canonical county data

### 5.1 Definition

Accepted canonical county data is the normalized, validated county geography currently approved for Kane Condo use.

It includes:

- Kane County boundary;
- roads;
- Fox River;
- creeks and approved water geometry;
- official building footprints;
- accepted source-release identities;
- normalized attributes;
- geometry hashes;
- provenance references.

### 5.2 Authority

Accepted canonical county data is authoritative only inside the Kane Condo SQLite/GeoPackage database.

The original source harvest remains preserved as evidence, but the canonical database defines which validated release the project currently accepts.

### 5.3 Release immutability

An accepted county release is immutable.

When newer official data is promoted:

- a new accepted release is created;
- the prior release remains identifiable;
- the prior release is marked superseded rather than overwritten;
- historical project states remain reproducible.

### 5.4 Geometry ownership

Kane Condo does not own or edit official county geometry as project-authored truth.

The project may:

- normalize geometry;
- validate geometry;
- simplify geometry for derived rendering;
- index geometry;
- associate geometry with project identities;
- reject invalid source geometry;
- preserve historical versions.

The project must not present a manually redrawn official footprint as though it were the county’s original feature.

If future project-authored geometry corrections are required, they must belong to a separately identified project layer with explicit provenance.

## 6. Kane Condo project building identity

### 6.1 Purpose

Official building identifiers may change across source releases.

Kane Condo therefore requires a project-owned building identity that remains independent of any one county `FPId` or other source identifier.

The project identity is the stable owner of manual classification history.

### 6.2 Ownership

Kane Condo owns:

- the project building identifier;
- its creation event;
- its lifecycle state;
- its mappings to official source footprints;
- reconciliation decisions across releases;
- split, merge, replacement, and retirement relationships.

### 6.3 Initial creation

During the first accepted import, each accepted official building footprint receives or maps to one deterministic Kane Condo project building identity.

The initial relationship may be one-to-one, but the data model must not assume that one-to-one relationships remain permanent.

### 6.4 Source mappings

A project building identity may map over time to:

- one official footprint;
- a replacement official footprint;
- multiple footprints after a split;
- one resulting footprint after a merge;
- no current footprint when the source removes the building;
- a later reappearing footprint after review.

Mappings must include:

- source release;
- source feature identity;
- mapping type;
- mapping confidence or decision basis when needed;
- effective time or release;
- whether the mapping was automatic or explicitly reviewed.

### 6.5 Identity invariants

The following must remain true:

1. A county source-ID change alone does not create a new project building automatically.
2. A geometry redraw alone does not erase classification history.
3. A removed official footprint does not delete the project identity.
4. A split does not silently copy a classification to every resulting footprint without an approved rule or review.
5. A merge does not silently discard conflicting classifications.
6. Ambiguity is recorded as ambiguity rather than resolved by guesswork.

### 6.6 Retirement

A project building identity may become inactive or retired, but it is not physically deleted merely because the current official release no longer contains a matching footprint.

Retirement preserves:

- prior classifications;
- prior source mappings;
- reconciliation history;
- auditability.

## 7. Kane Condo classification data

### 7.1 Definition

Classification data records the project’s current decision about a project building identity.

Allowed current states are:

- Unclassified;
- Other;
- Condominium;
- Apartments.

### 7.2 Authority

The authoritative current classification resides in the server-side SQLite/GeoPackage database.

A browser color, local cache, offline snapshot, exported file, or screenshot is not authoritative.

### 7.3 Default state

Unclassified is the default.

A project building with no explicit current-classification record is interpreted as Unclassified.

This avoids creating hundreds of thousands of redundant records at initial import.

An explicit return to Unclassified is still recorded in classification history even if the resulting current state can be represented by removal or deactivation of the explicit current-classification row.

### 7.4 Classification ownership

A classification belongs to the Kane Condo project building identity.

It does not belong directly to:

- an official release;
- a source `FPId`;
- a map tile;
- a County Field Map cell;
- a screen coordinate;
- a browser session;
- a USB filename.

### 7.5 Current state and history

The database must distinguish:

- the current authoritative classification;
- the append-only history of classification events.

A change event should be capable of recording:

- project building identity;
- previous state;
- new state;
- event time;
- actor or workstation identity if later required;
- request identity;
- server transaction result;
- correction or undo relationship;
- optional future evidence or note fields if approved.

The exact schema is deferred, but the ownership distinction is fixed.

### 7.6 History retention

Classification history is append-only.

Corrections and undo actions create new events. They do not delete or rewrite prior events.

### 7.7 No automatic classification

No official source attribute, geometry size, building shape, parcel class, algorithmic inference, or prior County Field Map state may silently become an authoritative Kane Condo classification.

Automated systems may later suggest candidates if separately approved, but only an approved classification action changes the authoritative state.

## 8. Refresh ownership and classification survival

### 8.1 Refresh sequence

A county building refresh operates on official source releases and source mappings before it affects project classifications.

The required conceptual order is:

1. harvest new official source evidence;
2. validate candidate release;
3. compare with accepted release;
4. reconcile official footprints to project building identities;
5. isolate ambiguous identity cases;
6. preserve existing classifications;
7. promote only after required review and validation;
8. publish a new offline package.

### 8.2 Clear one-to-one continuity

When a new official footprint clearly represents the same project building, the existing project identity and classification continue unchanged.

### 8.3 Added official footprint

A newly added official footprint normally creates a new project building identity with default Unclassified state.

It must not inherit a nearby building’s classification merely because it is spatially close.

### 8.4 Removed official footprint

When an official footprint disappears:

- its project building identity remains;
- its classification history remains;
- its current status becomes a reconciliation or retirement matter;
- the classification is not silently deleted.

### 8.5 Geometry change

A clear geometry redraw does not change the project classification.

The new official footprint maps to the existing project building identity.

### 8.6 Split

When one official footprint becomes multiple footprints:

- the original project identity remains historically valid;
- resulting project-identity treatment requires an explicit rule or review;
- a Condominium, Apartments, or Other state is not blindly duplicated.

### 8.7 Merge

When multiple official footprints become one:

- prior project identities and histories remain preserved;
- conflicting classifications require explicit reconciliation;
- the merged footprint must not silently choose one prior state.

### 8.8 Ambiguity

Ambiguous cases belong to a dedicated reconciliation process.

They must not be represented as:

- generic orange map warnings;
- County Field Map contradictions;
- automatic data loss;
- forced county-wide reinspection.

Only buildings affected by real identity ambiguity require review.

## 9. Derived offline render package

### 9.1 Definition

The offline render package is a generated, read-optimized representation of one accepted county database state.

It may include:

- county overview geometry;
- road levels of detail;
- water levels of detail;
- building geometry partitions or tiles;
- spatial indexes;
- classification snapshot;
- package manifest;
- release identities;
- compatibility metadata;
- hashes.

### 9.2 Ownership

Kane Condo owns the generated package, but it is derived data.

The package is not the authoritative source for:

- official county provenance;
- project building identity;
- current classification history;
- refresh reconciliation.

### 9.3 Regeneration

A render package may be regenerated from the authoritative accepted database and approved package-generation process.

If regenerated from the same authoritative state and build version, it should be reproducible to the extent defined by the later package contract.

### 9.4 Package identity

Every package must identify:

- package format version;
- accepted database release or build identity;
- official source release identities;
- classification snapshot identity;
- creation time;
- component inventory;
- component hashes;
- minimum compatible application version.

### 9.5 Package immutability

A published package is immutable.

A newer package receives a new identity. It does not modify the retained prior package in place.

### 9.6 Local activation

The USB may contain:

- one active package;
- one retained prior package for rollback;
- additional staged package data during verified installation.

Activation status is local operational state. It does not alter which county release the server has accepted.

## 10. Offline classification snapshot

### 10.1 Purpose

The classification snapshot allows the offline renderer to color buildings when the server is unavailable.

### 10.2 Authority

The snapshot is authoritative only as a published representation of a specific server classification state at a specific time.

It is not authoritative for later changes.

### 10.3 Contents

The snapshot should contain only the information needed for offline rendering and inspection, such as:

- project building identity;
- classification state;
- snapshot identity;
- generation time;
- authoritative database version.

It should not duplicate full classification history unless a later approved offline requirement needs it.

### 10.4 Staleness

When connected, the application must be able to distinguish:

- local snapshot state;
- current server state;
- whether a newer snapshot or package exists.

The application must not silently claim that an old snapshot is current.

## 11. Local non-authoritative user state

### 11.1 Permitted local state

The workstation or USB may retain small user-interface preferences, subject to later approval, such as:

- last map position;
- last zoom;
- visibility-filter settings;
- panel state;
- preferred window behavior;
- last successfully opened package identity.

### 11.2 Non-authority

Local preference state must never determine:

- official release acceptance;
- project building identity;
- authoritative classification;
- classification history;
- update promotion;
- source validation.

### 11.3 Safe deletion

Local preferences should be safely deletable without losing county data or classifications.

Resetting preferences must not reset the project.

### 11.4 Pending edits

No USB-local pending-classification journal is authorized by this document.

Until Batch 004 resolves runtime topology:

- authoritative editing requires confirmed server persistence;
- an unavailable server disables authoritative classification changes;
- the application must not silently create an unsynchronized local classification database.

If offline editing is later approved, the pending journal must receive a separate ownership, reconciliation, failure, and backup contract.

## 12. Server database ownership

### 12.1 Server role

The server-side SQLite/GeoPackage database is the operational source of truth.

It owns:

- accepted releases;
- source and harvest provenance;
- project building identity;
- source mappings;
- current classifications;
- classification history;
- refresh comparisons;
- reconciliation decisions;
- promotion history;
- package publication records.

### 12.2 Transaction boundary

Changes to authoritative records occur through controlled server transactions.

The browser must not write directly to the database file.

### 12.3 Database file handling

The authoritative database file must not be:

- opened for writes from multiple uncontrolled processes;
- copied to the USB as a live editable database;
- committed to Git;
- edited manually as a routine workflow;
- replaced in place without candidate validation and rollback protection.

### 12.4 Backups

Backups of the authoritative database are authoritative recovery artifacts.

They must preserve:

- database content;
- migration state;
- project identities;
- classifications;
- history;
- release provenance;
- reconciliation decisions.

Backup and restore procedures are defined later, but the ownership requirement is fixed.

## 13. USB ownership

### 13.1 USB contents

The project USB is a transport and user-runtime medium.

It may contain:

- browser application;
- local launcher or static server;
- active offline render package;
- retained prior package;
- package manifests;
- non-authoritative preferences;
- approved diagnostic logs;
- installation staging files.

### 13.2 USB is not the sole authority

Loss, damage, or corruption of the USB must not destroy:

- project classifications;
- project identities;
- accepted release history;
- official source evidence.

Those remain recoverable from server authority and backups.

### 13.3 Shared ownership

The USB is shared among project owners, but only one user operates it at a time.

Physical possession of the USB does not alter data authority.

## 14. Git repository ownership

### 14.1 Git owns project definitions

The `kane-condo` repository owns versioned project materials such as:

- documentation;
- migration definitions;
- source profiles;
- validation rules;
- application source;
- server source;
- tests;
- build scripts;
- small synthetic fixtures;
- package-format specifications;
- operational instructions.

### 14.2 Git does not own production data

The repository must not contain:

- production county harvests;
- accepted production GeoPackages;
- project classification databases;
- production database backups;
- generated county render packages;
- USB deployment packages;
- secrets;
- WireGuard keys;
- server credentials;
- large temporary source or delivery ZIP files.

### 14.3 Reproducibility

Git should contain enough definitions and tooling to reproduce accepted database structures, validation behavior, application builds, and package builds when provided the controlled external data inputs.

## 15. Logs and diagnostics

### 15.1 Operational logs

Logs may record:

- source checks;
- harvesting;
- validation;
- candidate comparison;
- promotion;
- package generation;
- API failures;
- application integrity failures.

### 15.2 Authority

Logs support diagnosis and audit but do not replace authoritative database records.

A successful-looking log line does not override a failed transaction.

### 15.3 Privacy and minimization

Logs should avoid unnecessary personal information.

Because the project is single-user, extensive user surveillance or activity telemetry is not required.

## 16. Deletion and retention rules

### 16.1 Never silently delete

The following must not be silently deleted:

- accepted release identities;
- preserved source evidence referenced by an accepted release;
- project building identities;
- source mappings;
- classification history;
- promotion history;
- required backups;
- package manifests for active or retained rollback packages.

### 16.2 Regenerable data

The following may be regenerated after integrity checks:

- derived render tiles or chunks;
- simplified overview geometry;
- classification snapshots;
- generated package archives;
- temporary candidate databases;
- temporary staging directories.

### 16.3 Temporary data

Temporary data must have:

- a defined owner;
- a defined lifecycle;
- a cleanup rule;
- no possibility of being mistaken for accepted data.

## 17. Data transfer boundaries

### 17.1 Official source to server

The server retrieves official evidence into controlled staging storage.

No workstation participates in harvesting or validation.

### 17.2 Server to authoritative database

Only validated and promoted candidate data enters the accepted database.

### 17.3 Authoritative database to offline package

Package generation reads accepted data and produces immutable derived artifacts.

### 17.4 Server to USB

Only complete, versioned, verified packages are transferred for activation.

### 17.5 Browser to server

The browser submits deliberate classification actions and approved update-control actions through the server interface.

It does not submit map-navigation events as project data.

### 17.6 Server to browser

The server returns:

- confirmed classification state;
- save result;
- compatibility status;
- update status;
- candidate summaries;
- review requirements;
- package publication status.

## 18. Failure ownership

### 18.1 Source failure

A source failure belongs to the harvest/candidate process. It does not invalidate the currently accepted county release.

### 18.2 Candidate failure

A candidate failure leaves the accepted database unchanged.

### 18.3 Classification-write failure

A write failure leaves the prior authoritative classification in force.

### 18.4 Package-generation failure

A package-generation failure leaves the active USB package unchanged.

### 18.5 USB failure

A USB failure is recovered from server authority and published packages. It does not redefine authoritative project state.

### 18.6 Browser failure

A browser crash does not imply that a Pending or Saving classification succeeded.

Only confirmed server state is authoritative.

## 19. Prohibited data coupling

Kane Condo must not couple classification ownership to:

- County Field Map cells;
- grid coordinates;
- viewport position;
- map chunk filenames;
- tile coordinates;
- current zoom;
- building color;
- one official source release;
- one source `FPId`;
- one workstation;
- one browser profile;
- one USB path.

These may be useful references or indexes, but they cannot own the classification.

## 20. Core data invariants

The following invariants govern all later design and implementation:

1. Official source evidence is preserved separately from accepted data.
2. A harvested source is not accepted merely because retrieval succeeded.
3. Accepted releases are immutable and superseded rather than overwritten.
4. Project building identity is independent of one official identifier.
5. Classification belongs to the project building identity.
6. Unclassified is the default.
7. Classification history is append-only.
8. Corrections do not erase prior decisions.
9. Official refreshes do not silently erase classifications.
10. Ambiguous split and merge cases require explicit reconciliation.
11. The offline package is derived and regenerable.
12. The offline snapshot is not newer than its declared identity.
13. The USB is not the sole source of truth.
14. Local preferences are safely deletable.
15. Browser appearance is not authoritative data.
16. Navigation does not create project records.
17. Git contains definitions and source, not production data.
18. Failed candidates, writes, or packages leave the last accepted state usable.

## 21. Deferred ownership decisions

This contract intentionally defers:

- the exact database schema;
- server technology;
- API protocol;
- authentication identity;
- whether classification notes or evidence are stored;
- whether an actor identity is required in classification history;
- whether offline editing is allowed;
- pending-journal ownership if offline editing is approved;
- exact backup retention periods;
- exact source-evidence retention periods;
- package signing in addition to hashing;
- long-term archival storage;
- project-authored geometry corrections;
- future parcel or address datasets.

Deferred decisions may refine this contract but may not violate its invariants.

## 22. Acceptance checklist

Batch 003 is accepted when the project owner confirms that this document correctly separates:

- official source evidence;
- accepted canonical county data;
- project building identity;
- current classification;
- classification history;
- offline render packages;
- offline classification snapshots;
- local preferences;
- server authority;
- USB runtime data;
- Git-managed definitions;
- backups and recovery artifacts.

Approval also confirms that:

- classifications survive normal source refreshes;
- source-ID changes do not automatically create or destroy project identity;
- splits and merges are not guessed;
- no County Field Map cell owns a building classification;
- production data and large generated artifacts remain outside Git.

Approval of this document does not authorize implementation.
