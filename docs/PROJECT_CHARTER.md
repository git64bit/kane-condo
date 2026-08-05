# Kane Condo Project Charter

**Document status:** Proposed Batch 001 project contract  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `a320d4d`  
**Implementation authorization:** None. This document defines the project and does not authorize coding, migration work, data copying, or server changes.

## 1. Project identity

Kane Condo is a Kane County building-classification application.

Its operational object is the **individual building footprint**. The application is not a county cell classifier, a general geographic information system, or an extension of County Field Map.

The project exists to identify and preserve three meaningful states among Kane County building footprints:

- buildings classified as **Condominium**;
- buildings classified as **Apartments**;
- buildings classified as **Other** so they can be removed from the active visual workload.

Every building begins as **Unclassified**.

## 2. Primary purpose

The application must allow a project owner to work through Kane County building footprints, classify obvious non-target buildings as Other, and progressively thin the visible map until likely condominium and apartment buildings can be identified and classified.

The principal working pattern is elimination:

1. Open the full Kane County map.
2. Pan and zoom through the county.
3. At editing scale, select an individual building.
4. Classify obvious houses, factories, commercial structures, government installations, utility structures, and other non-target buildings as **Other**.
5. Hide Other buildings.
6. Continue working through the remaining Unclassified buildings.
7. Classify confirmed target buildings as **Condominium** or **Apartments**.
8. Correct classifications when better information becomes available.

Classification is deliberate. Opening the map, panning, zooming, inspecting an area, or selecting a building for inspection must never change data automatically.

## 3. User and operating model

Kane Condo is designed for one active user at a time.

- One USB drive is shared among the project owners.
- Concurrent editing is not supported or required.
- Multi-user locking, merge resolution, and simultaneous-write conflict handling are outside the project.
- The application is used from local Windows or Ubuntu workstations.
- Workstations are user environments, not development or heavy-processing environments.
- Development, source harvesting, database preparation, validation, comparison, and package production occur on designated server infrastructure.

The single-user model does not reduce the requirement for reliable persistence, audit history, backup, or recovery.

## 4. Map experience

The application must present Kane County as one continuous, zoomable map.

On startup:

- the full county outline is fitted to the available map area;
- the user is not asked to choose a sector, grid, or working cell;
- the map behaves as one uninterrupted geographic surface.

The visible geographic content is limited to:

- Kane County boundary;
- roads;
- water bodies and creeks;
- building footprints.

The renderer may vary detail according to zoom and screen usefulness. The internal storage may be partitioned for performance, but no partition, tile boundary, sector, or classification grid may be visible or operationally meaningful to the user.

Roads and water provide continuous geographic orientation. Building footprints appear progressively as the map approaches useful local scales. Exact building geometry must be available at the editing scale.

Building classification is available only at the maximum approved editing scale, where an individual footprint can be selected without ambiguity.

## 5. Classification model

The four visible building states are:

| State | Meaning | Color |
|---|---|---|
| **Unclassified** | No project classification has been assigned | Gray |
| **Other** | The building is not currently relevant as a condominium or apartment target | Red |
| **Condominium** | The building has been classified as condominium property | Green |
| **Apartments** | The building has been classified as apartment property | Yellow |

Unclassified is the starting and default state.

The interface must allow each state to be shown or hidden independently. Hiding a class affects only rendering and selection; it must not alter the stored classification.

The ability to hide Other is central to the application. It is the mechanism by which completed elimination work progressively reduces the remaining visual workload.

## 6. Data authority and persistence

SQLite, using a GeoPackage where spatial storage is required, is the authoritative data foundation.

Authoritative project data includes:

- accepted official county source releases;
- source provenance and validation history;
- project-owned building identities;
- mappings between project identities and official building footprints;
- current building classifications;
- classification history;
- source-refresh and promotion history.

Manual classifications belong to the Kane Condo project, not directly to a temporary official-source identifier.

A later county release may redraw, renumber, split, merge, remove, or replace building footprints. Such changes must not silently erase an existing Condominium, Apartments, or Other classification.

JSON or similar text files may be used for small manifests, diagnostics, or data interchange, but they are not the authoritative classification database.

## 7. Offline rendering requirement

The county map must remain usable from the USB when the processing server or private network is unavailable.

Offline capability includes:

- opening the accepted county map;
- panning and zooming;
- rendering accepted roads, water, creeks, and buildings;
- applying the available classification snapshot;
- showing and hiding classification categories;
- inspecting the version and identity of the local map package.

The offline rendering package is a derived product of the authoritative database. It is not itself the authoritative county database.

The exact offline package format and local serving mechanism are deferred to later approved decisions and benchmarks.

## 8. Server processing requirement

A real server reachable through the project’s WireGuard/proxy network performs the essential work that does not belong on the USB workstation.

Server responsibilities include:

- official-source availability checks;
- complete source harvesting;
- source validation;
- candidate database construction;
- release comparison;
- project-building identity reconciliation;
- safe candidate promotion;
- classification persistence;
- classification history;
- offline render-package generation;
- package publication;
- backup and recovery.

The browser application must not perform county-wide harvesting, database migration, spatial reconciliation, or render-package generation.

The exact server technology, API design, authentication method, and offline-editing policy are deferred to later approved project-contract documents.

## 9. Data refresh requirement

Data freshness must be visible from inside Kane Condo.

The application must report:

- which accepted county releases the current map uses;
- when official sources were last checked;
- whether newer source data appears available;
- whether a candidate is being processed;
- whether validation succeeded or failed;
- whether building-identity review is required;
- whether a new offline package is ready;
- which package is currently installed.

Detection of a newer official source must not automatically replace accepted data.

A candidate update becomes usable only after complete harvesting, validation, comparison, classification reconciliation, package generation, and explicit promotion according to the approved refresh workflow.

Review must be limited to real ambiguity introduced by changed official building data, especially where existing project identities or classifications may be affected. The project must not create a generic county-wide warning layer unrelated to this purpose.

## 10. Relationship to County Field Map

County Field Map and Kane Condo are separate applications with separate purposes.

County Field Map classified geographic cells and identified void areas. Kane Condo classifies buildings.

The completed County Field Map result may be evaluated as an upstream preparation aid for reducing irrelevant exported geometry. It must not appear in the Kane Condo user interface or become part of Kane Condo’s classification model.

Kane Condo must not contain:

- visible county-sector grids;
- 16×16 or 8×8 classification grids;
- discovered, muted, or undiscovered cell states;
- Mute controls;
- cell completion logic;
- automatic classification caused by navigation;
- writes to County Field Map sector ledgers;
- building-cell contradiction overlays;
- a generic orange review layer.

## 11. Explicit exclusions

The following are outside the current project contract unless later added through an approved scope change:

- concurrent multi-user editing;
- public Internet access;
- public-facing map publication;
- state-wide or national scope;
- jurisdictions outside Kane County;
- parcel ownership research;
- address search;
- tax-record integration;
- unit-count estimation;
- automatic legal determination of condominium status;
- automatic apartment classification;
- generalized property-management functions;
- statistical dashboards;
- mobile-device support;
- editing official county geometry;
- editing roads, water, or county boundaries;
- replacing County Field Map;
- reintroducing a persistent classification grid.

## 12. Success condition

Kane Condo succeeds when a project owner can:

1. open the complete Kane County outline from the USB;
2. navigate one continuous offline map;
3. use roads and water for orientation;
4. see building footprints progressively at useful zoom levels;
5. select one exact building only at the approved editing scale;
6. classify it as Other, Condominium, Apartments, or return it to Unclassified;
7. receive truthful confirmation of whether the classification was saved;
8. hide Other buildings and observe the map progressively thin;
9. preserve classifications across official county-data refreshes;
10. see data freshness and update status from inside the application;
11. continue viewing the accepted map when the server is unavailable;
12. install or roll back a validated offline map package without losing the prior working package.

## 13. Change control

This charter is the controlling statement of project purpose.

Later design documents may define workflows, ownership, runtime topology, salvage boundaries, and Version 1 scope, but they may not contradict this charter without an explicit charter revision approved and committed by the project owner.

No implementation is authorized until Milestone 0 is complete and explicitly approved.
