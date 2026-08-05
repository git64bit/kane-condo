# Kane Condo Runtime Topology

**Document status:** Proposed Batch 004 runtime-topology contract  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `b2c3e23`  
**Depends on:** `docs/PROJECT_CHARTER.md`, `docs/USER_WORKFLOW.md`, `docs/DATA_OWNERSHIP.md`  
**Implementation authorization:** None. This document assigns runtime responsibilities and communication boundaries. It does not authorize server installation, API development, database implementation, local-launcher changes, or application coding.

## 1. Purpose

Kane Condo must combine two operational requirements:

1. The county map must render from the USB even when the private server is unavailable.
2. Authoritative classification, source refresh, validation, reconciliation, and package production require a real server.

This document defines the runtime components, assigns each responsibility to one component, and resolves whether Version 1 supports offline editing.

The controlling rule is:

> Map rendering is local and offline. Authoritative processing and classification persistence are server functions.

## 2. Approved topology

Kane Condo uses four runtime zones:

1. **Development and processing infrastructure**
2. **Private Kane Condo application server**
3. **Shared project USB**
4. **Windows or Ubuntu user workstation**

The user experiences one browser application, but the system is deliberately divided between local rendering and private server authority.

## 3. Version 1 offline-editing decision

Version 1 does **not** support offline classification editing.

When the private server is unavailable:

- the accepted county map remains fully viewable;
- panning and zooming remain available;
- classification colors from the published local snapshot remain available;
- visibility filters remain available;
- building inspection remains available;
- authoritative classification controls are disabled;
- no local pending-classification journal is created;
- no classification is represented as saved.

This decision is intentional.

It avoids:

- conflicting copies of classification state;
- uncertain replay order;
- duplicate submissions;
- stale-building identity writes;
- USB-loss risk for unsynchronized decisions;
- ambiguity about whether a pending local change survived;
- premature synchronization machinery.

The single-user operating model makes server-required editing practical. A future offline-editing feature may be proposed separately, but it is outside Version 1 and requires an explicit contract revision.

## 4. Runtime zones

### 4.1 Development and processing infrastructure

The development and processing environment includes the Proxmox container or other designated server-side systems used for:

- source-code development;
- tests;
- official-source harvesting;
- database construction;
- spatial processing;
- source comparison;
- identity reconciliation;
- offline-package generation;
- cross-platform builds;
- release packaging.

This environment:

- does not function as the user workstation;
- does not require a desktop browser for normal development;
- does not perform classification through the user interface;
- does not host the active USB map as the user runtime;
- does not make the Windows or Ubuntu workstation perform development work.

Development and heavy processing remain on Linux infrastructure.

### 4.2 Private Kane Condo application server

The application server is reachable only through the approved WireGuard/proxy network.

It owns the authoritative operational services:

- SQLite/GeoPackage access;
- classification reads and writes;
- classification history;
- project-building identity;
- server health and compatibility status;
- official-source update checks;
- refresh-job control;
- candidate processing status;
- reconciliation status;
- accepted release status;
- offline-package publication metadata;
- package download or retrieval service;
- backup and recovery operations.

The application server may invoke or coordinate heavier processing on the orchestrator or another designated processing host. The browser does not need to know which internal host performs a job.

The application server must not expose the authoritative SQLite/GeoPackage file directly to the browser or workstation filesystem.

### 4.3 Shared project USB

The USB is the portable user-runtime medium.

It contains the approved local runtime assets, including:

- browser application files;
- local launcher or static-serving runtime;
- active offline county render package;
- active package manifest;
- published classification snapshot;
- retained prior package for rollback when required;
- approved local configuration;
- optional non-authoritative user-interface preferences;
- approved local diagnostic logs.

The USB does not contain the live authoritative project database.

The USB must remain reconstructable from:

- the versioned repository;
- accepted server data;
- published render packages;
- approved runtime builds.

### 4.4 Windows or Ubuntu workstation

The workstation is the user application environment.

It performs:

- local application launch;
- browser display;
- local map rendering;
- pan and zoom interaction;
- local package integrity checks;
- building hit testing;
- visibility filtering;
- user classification input;
- private API requests;
- package download, staging, verification, and activation through an approved mechanism.

The workstation does not perform:

- project development;
- source harvesting;
- database migration;
- county-wide comparison;
- spatial identity reconciliation;
- render-package generation;
- authoritative database backup;
- authoritative SQLite writes outside the API.

## 5. Local application serving

### 5.1 Requirement

The browser application and offline map package must be served from the USB through a local origin.

The browser must not depend on the private server to load the base map application or county geometry.

### 5.2 Local static server

A small local static server or equivalent approved launcher may serve:

- application HTML;
- JavaScript;
- CSS;
- package manifests;
- local map chunks or tiles;
- local classification snapshot;
- local static assets.

Its role is strictly local delivery and launch support.

It is not the authoritative Kane Condo backend.

### 5.3 TrivialHTTP status

The prior TrivialHTTP project may be evaluated as a donor for local static serving and browser launch.

Kane Condo does not depend on TrivialHTTP’s former County Field Map write API.

If TrivialHTTP is reused, its permitted role is limited to functions such as:

- bind to loopback only;
- serve files from the USB application root;
- launch the approved start URL;
- prevent path traversal;
- support Windows and Ubuntu runtime packaging.

No decision to copy, modify, or rebuild TrivialHTTP is authorized by this document.

The final local-serving mechanism remains an implementation decision after the topology and salvage documents are complete.

## 6. Browser application origin and API origin

The browser application runs from the local USB origin.

The authoritative API runs from a separate private-network origin.

Conceptually:

```text
Local browser application:
http://127.0.0.1:<local-port>/

Private Kane Condo API:
https://<private-kane-condo-host>/
```

Exact hostnames, ports, certificates, and proxy paths are deferred.

The separation is mandatory:

- local application availability does not depend on API availability;
- API failure does not remove the map;
- local package failure is distinguishable from API failure;
- API compatibility can be checked independently.

## 7. Startup sequence

The approved startup sequence is:

1. User launches Kane Condo from the USB.
2. The local runtime serves the application and active map package.
3. The browser validates the local package manifest and required components.
4. The full county outline opens from local data.
5. The application begins rendering local roads, water, and buildings according to zoom.
6. In parallel, the application checks the private API when network access is available.
7. The interface reports one of:
   - server connected and compatible;
   - server unavailable;
   - server reachable but incompatible;
   - server reachable but degraded.
8. Editing is enabled only when the server confirms compatibility and authoritative write availability.

A slow or unavailable private server must not delay the initial local county view beyond the time required to validate and open the local package.

## 8. Local rendering data flow

Local rendering uses only USB-resident published artifacts.

The flow is:

```text
Active package manifest
    -> local package validation
    -> local spatial chunk or tile selection
    -> local geometry decode
    -> local classification snapshot lookup
    -> browser rendering
```

The private API is not queried for every road, creek, building, pan, zoom, or draw operation.

This prevents network latency from becoming map latency.

## 9. Classification read behavior

### 9.1 Offline baseline

The published local classification snapshot provides the offline map colors.

It represents a declared server classification state at package or snapshot publication time.

### 9.2 Connected verification

When connected, the browser may request current server classification data for:

- the selected building;
- a small visible working set;
- a newer classification snapshot identity;
- reconciliation after a confirmed write.

The server does not need to resend the entire county classification set for every connection.

### 9.3 Authority display

The interface must distinguish when displayed classification data comes from:

- the local published snapshot;
- current server confirmation;
- a pending user choice;
- a confirmed server write.

The local snapshot must not be described as current when the server reports a newer classification state.

## 10. Classification write behavior

The approved Version 1 write flow is:

1. User reaches the editing scale.
2. User selects one exact project building.
3. Browser retrieves or confirms the current authoritative classification when connected.
4. User deliberately selects a different class.
5. Browser shows the proposed value as Pending.
6. Browser submits the change to the private API.
7. Server validates:
   - API compatibility;
   - request identity;
   - project building identity;
   - current building lifecycle state;
   - allowed classification;
   - stale-state or request conflict condition;
   - database transaction availability.
8. Server commits the classification and history in one transaction.
9. Server returns the authoritative result.
10. Browser shows Saved and applies the authoritative color.
11. The browser may update an in-memory session cache.
12. The published USB classification snapshot remains unchanged until a later snapshot or package publication.

The browser never writes directly into the SQLite/GeoPackage file.

## 11. Server-unavailable behavior

When the private API becomes unavailable:

- the local map continues rendering;
- the current viewport remains;
- current visibility filters remain;
- the local snapshot remains visible;
- selected-building inspection remains available;
- new classification writes are disabled;
- a Pending but unsubmitted choice is not treated as saved;
- a Saving request without confirmation is reported as unresolved or failed;
- the browser does not create an undisclosed local queue.

If connectivity returns, the application rechecks server health and compatibility before re-enabling editing.

## 12. API compatibility

The local application and private server must exchange compatibility metadata before authoritative operations.

Compatibility status should include:

- client application version;
- API version;
- database schema version;
- project identity model version;
- active server release identity;
- minimum supported client;
- package-format compatibility where relevant.

The browser may render its local map when the API is incompatible, but it must disable writes that cannot be performed safely.

## 13. Update-check topology

### 13.1 User-facing action

The browser exposes update status and a deliberate Check for updates action.

### 13.2 Server-side execution

The browser request asks the private server to:

- return recent source-check status;
- or initiate an approved lightweight source check.

The browser does not contact Kane County ArcGIS endpoints directly.

### 13.3 Reasons

Centralized source checks provide:

- one source profile registry;
- one provenance trail;
- one validation implementation;
- one accepted-release comparison point;
- no browser cross-origin dependency;
- no duplicate downloads from multiple workstations;
- no workstation processing burden.

## 14. Refresh-job topology

Heavy refresh work occurs on server-side infrastructure.

The conceptual flow is:

```text
Browser request or scheduled server action
    -> application server creates or reports job
    -> processing host checks official source
    -> candidate evidence is harvested
    -> candidate database is built
    -> candidate is validated
    -> accepted release is compared
    -> project identities are reconciled
    -> ambiguity is reported
    -> approved candidate is promoted
    -> render package is generated
    -> package is published
    -> browser reports Ready to install
```

The browser monitors state but does not remain responsible for the job’s execution.

Closing the browser must not corrupt or cancel server processing unless the user explicitly invokes an approved cancellation action.

## 15. Package publication topology

The processing infrastructure generates a complete immutable offline package.

The private server publishes:

- package identity;
- manifest;
- byte length;
- cryptographic hashes;
- compatibility metadata;
- accepted database release identity;
- classification snapshot identity;
- download or retrieval location;
- publication state.

Only a complete validated package is reported as Ready to install.

Partial generation directories are not published.

## 16. Package transfer and activation

### 16.1 Responsibility split

The server publishes the package.

The workstation or approved local helper:

- obtains the package;
- stages it on the USB;
- verifies the manifest and hashes;
- confirms compatibility;
- activates it atomically;
- retains the prior package for rollback;
- verifies that the new package opens successfully.

### 16.2 Browser limitation

A normal browser cannot be assumed to replace arbitrary USB files safely.

Therefore, final package installation may require:

- a local companion launcher;
- a dedicated updater executable;
- or a deliberate manual procedure.

The exact mechanism is deferred to the deployment milestones.

The topology requirement is that installation remains a local USB operation after receiving a server-published package.

### 16.3 No automatic replacement

Source detection or package publication does not automatically replace the active USB package.

Activation requires a deliberate approved installation action.

## 17. Classification snapshot publication

Classification changes may accumulate on the server without regenerating base county geometry.

The server may publish a newer compact classification snapshot independently of a full geometry package when the eventual package format supports this safely.

The topology permits:

```text
Stable base geometry package
+
Replaceable classification snapshot
```

The exact publication cadence is deferred.

A newer snapshot must declare compatibility with the active base geometry and project-building identity set.

## 18. WireGuard and proxy boundary

The authoritative API is available only through the approved private network path.

The network boundary must provide:

- encrypted transport;
- private host reachability;
- no direct public exposure of the API;
- controlled proxy routing;
- server identity verification;
- explicit authentication for authoritative writes.

Exact WireGuard peers, proxy configuration, certificates, and credentials are operational secrets and remain outside Git.

The repository may contain templates and documentation without secrets.

## 19. Authentication model boundary

The project is single-user operationally, but the server must still distinguish authorized project access from unauthenticated traffic.

Version 1 does not require a multi-user role system.

The minimum required security properties are:

- unauthorized clients cannot write classifications;
- unauthorized clients cannot trigger refresh promotion;
- API requests are attributable to the approved project client or credential;
- credentials are not embedded in public repository content;
- local map rendering does not require authentication.

The exact authentication mechanism is deferred to the server technology and network batch.

## 20. Concurrency model

The approved operating model permits one active classification user at a time.

The server still uses SQLite transactions and request identities to prevent:

- duplicate submissions;
- accidental replay;
- partial history writes;
- stale state from being reported as saved.

No collaborative live-editing protocol is required.

Administrative refresh processing and user classification may occur near the same time, but promotion rules must prevent a refresh from invalidating an in-flight building write.

The exact maintenance-window or transaction strategy is deferred to implementation design.

## 21. Backup ownership

Authoritative backups are server-side.

The server infrastructure must back up:

- authoritative SQLite/GeoPackage data;
- project building identities;
- current classifications;
- classification history;
- migration state;
- accepted release history;
- reconciliation decisions;
- package-publication records.

The USB is not an authoritative database backup.

The active and prior offline packages may be archived for deployment recovery, but they do not replace database backups.

## 22. Logging topology

### 22.1 Server logs

Server-side logs may record:

- API health;
- classification transaction results;
- source checks;
- refresh jobs;
- validation failures;
- promotions;
- package publication;
- backup operations.

### 22.2 Local logs

The USB or workstation may retain bounded diagnostic logs for:

- launcher failures;
- local package integrity failures;
- browser startup failures;
- API connection status;
- package installation and rollback.

### 22.3 Authority

Logs are diagnostic evidence. They do not override database transaction state or package manifests.

## 23. Failure isolation

### 23.1 Private server failure

Effect:

- offline rendering continues;
- authoritative editing stops;
- update checks stop;
- active local package remains unchanged.

### 23.2 Processing-host failure

Effect:

- active server database and USB package remain usable;
- current refresh job fails or pauses;
- no candidate is promoted partially.

### 23.3 Local static-server failure

Effect:

- browser application cannot load locally;
- authoritative server data remains safe;
- USB runtime may be repaired or replaced.

### 23.4 Active package failure

Effect:

- application reports integrity failure;
- no partial map is treated as valid;
- retained prior package or reconstruction procedure is used.

### 23.5 API incompatibility

Effect:

- map remains locally viewable;
- authoritative writes are disabled;
- exact compatibility mismatch is reported.

### 23.6 USB loss

Effect:

- no authoritative classification history is lost;
- USB is reconstructed from repository builds and published server packages.

### 23.7 Workstation loss

Effect:

- no authoritative project data is lost;
- another approved Windows or Ubuntu workstation can use the shared USB.

## 24. Component responsibility matrix

| Responsibility | Development/processing infrastructure | Private application server | USB/local runtime | Browser/workstation |
|---|---:|---:|---:|---:|
| Source-code development | Owns | No | No | No |
| Official-source harvesting | Owns or executes | Coordinates/reports | No | No |
| Candidate database construction | Owns or executes | Coordinates/reports | No | No |
| Validation and comparison | Owns or executes | Coordinates/reports | No | No |
| Project-identity reconciliation | Owns or executes | Stores/reports | No | Reviews approved cases |
| Authoritative SQLite/GeoPackage | No direct user role | Owns | No | No |
| Classification transaction | No | Owns | No | Requests |
| Classification history | No | Owns | Snapshot only if published | Displays |
| Base map rendering | No | No | Supplies data | Owns execution |
| Pan and zoom | No | No | Supplies assets | Owns |
| Visibility filters | No | No | May store preference | Owns |
| Update status | Executes underlying work | Owns status | May cache last known status | Displays/requests |
| Package generation | Owns or executes | Publishes | No | No |
| Package download | No | Serves | Receives | Initiates or assists |
| Package verification | Generates hashes | Publishes hashes | Stores manifest | Executes locally |
| Package activation | No | No | Owns active package | Initiates through approved method |
| Rollback | No | Records publication | Owns retained prior package | Initiates |
| Authoritative backup | Processing support | Owns | No | No |

## 25. Data-path summary

### 25.1 Map path

```text
Accepted server database
    -> server-side package generator
    -> published immutable package
    -> USB active package
    -> local static server
    -> browser renderer
```

### 25.2 Classification path

```text
User selects exact building
    -> browser submits deliberate change
    -> private API validates
    -> SQLite transaction commits current state and history
    -> authoritative response returns
    -> browser displays Saved
    -> later snapshot publication updates offline colors
```

### 25.3 Refresh path

```text
Official Kane County source
    -> processing infrastructure
    -> preserved source evidence
    -> candidate database
    -> validation and comparison
    -> project-identity reconciliation
    -> promotion
    -> package generation
    -> private publication
    -> deliberate USB installation
```

## 26. Prohibited topology

Kane Condo must not use any topology in which:

- the browser writes directly to the GeoPackage file;
- the production GeoPackage is edited from the USB;
- Windows or Ubuntu workstations perform county harvesting;
- the map requires live network tile retrieval;
- every pan or zoom queries the private server;
- the private server is required merely to open the county outline;
- the browser silently queues offline classifications;
- the USB is the sole copy of authoritative classifications;
- source detection automatically activates a package;
- the API is publicly exposed without the private-network boundary;
- TrivialHTTP or another static server impersonates the authoritative backend;
- a classification is inferred from a tile, cell, or screen location.

## 27. Deferred topology decisions

This contract intentionally defers:

- exact private server software;
- exact processing-host relationship;
- exact API path structure;
- exact local static server or launcher;
- exact package format;
- exact package updater mechanism;
- exact authentication mechanism;
- exact proxy hostname and certificate arrangement;
- whether classification snapshots publish independently of geometry packages;
- classification snapshot frequency;
- server maintenance-window behavior during promotion;
- local preference storage format;
- diagnostic-log retention;
- future offline-editing support.

These decisions may refine implementation but may not violate the approved topology.

## 28. Runtime invariants

The following must remain true:

1. The full accepted map can open from USB without the private server.
2. Roads, water, and buildings render from local data.
3. Private-server latency does not control pan and zoom latency.
4. Authoritative editing requires a compatible reachable server in Version 1.
5. No silent offline edit queue exists in Version 1.
6. The browser never writes directly to SQLite/GeoPackage.
7. The USB never becomes the sole classification authority.
8. Workstations do not perform development or county-wide processing.
9. Source refresh occurs on server-side infrastructure.
10. A refresh job continues independently of the browser session.
11. Only complete validated packages are published.
12. Package activation is deliberate and local.
13. A server failure does not remove the current map.
14. A package failure does not alter authoritative server data.
15. API incompatibility disables writes but not local map viewing.
16. The private API is not publicly exposed.
17. TrivialHTTP, if reused, is only a local static-serving component.
18. County Field Map write behavior is not part of Kane Condo.

## 29. Acceptance checklist

Batch 004 is accepted when the project owner confirms:

- rendering remains local and offline;
- the private server owns authoritative SQLite/GeoPackage operations;
- workstations are user environments only;
- the orchestrator and processing hosts perform development and heavy processing;
- Version 1 editing requires server connectivity;
- no local pending-classification journal is included;
- a local static server or launcher may serve USB assets;
- TrivialHTTP is not the authoritative backend;
- update checks and refresh jobs run server-side;
- package publication and USB activation are separate;
- the API is private through WireGuard/proxy;
- each major operation has one clear owner.

Approval of this document does not authorize implementation.
