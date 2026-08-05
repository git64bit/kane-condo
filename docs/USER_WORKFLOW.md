# Kane Condo User Workflow

**Document status:** Proposed Batch 002 user-workflow contract  
**Project:** Kane Condo  
**Repository:** `git64bit/kane-condo`  
**Baseline commit:** `c43f00d`  
**Depends on:** `docs/PROJECT_CHARTER.md`  
**Implementation authorization:** None. This document defines user-visible behavior and does not authorize application development.

## 1. Purpose of this document

This document defines how a project owner uses Kane Condo from application startup through building classification, correction, filtering, update inspection, and shutdown.

It defines user-visible behavior only. It does not select the rendering library, offline package format, server technology, API protocol, database schema, or deployment mechanism.

The controlling rule is:

> Navigation, inspection, filtering, and update checking must never classify or modify a building automatically.

## 2. Normal operating conditions

Kane Condo is operated by one active user at a time from a Windows or Ubuntu workstation.

The user starts the application from the shared project USB drive. The offline county map package is stored locally on that USB drive. A private Kane Condo server may be reachable through the project’s WireGuard/proxy network.

The application must distinguish these two independent capabilities:

1. **Map availability** — whether the accepted offline county map can be opened and rendered.
2. **Editing availability** — whether an authoritative building-classification change can be saved.

The map remains usable when the private server is unavailable. Editing availability depends on the approved runtime topology and must always be reported truthfully.

## 3. Startup workflow

### 3.1 Launch

The user starts Kane Condo using the approved workstation launcher.

The application performs local checks before presenting the map:

- application version is readable;
- offline map-package manifest is present;
- package format is supported;
- required package components exist;
- recorded hashes or integrity checks pass;
- county-data release identity is readable;
- classification snapshot identity is readable.

### 3.2 Successful startup

When the local package is valid, the application opens with:

- the complete Kane County outline fitted to the map area;
- major roads and major water visible for orientation;
- no grid, sector, cell, or tile boundary;
- current connection and save capability shown without blocking map use;
- current local package identity available for inspection.

The initial view is navigational. No building is selected and no editing control is active.

### 3.3 Local package failure

If the local package is missing, incomplete, altered, incompatible, or unreadable, the application must not display a partial map as though it were valid.

It must report:

- the failed component or compatibility condition;
- the active application version;
- the expected package version when known;
- whether a previously retained package is available;
- the approved recovery action.

A local package failure must not initiate an automatic destructive replacement.

## 4. County navigation

### 4.1 Continuous map behavior

The county is presented as one continuous geographic surface.

The user may:

- pan in any direction;
- zoom in and out continuously;
- return to the full-county view;
- use roads, water, and creeks for orientation;
- move between rural, suburban, industrial, and municipal areas without opening sectors or cells.

Internal chunks, tiles, indexes, or levels of detail must remain invisible.

### 4.2 Progressive detail

The renderer changes visible detail according to zoom and screen usefulness.

The expected progression is:

1. **County overview**
   - complete county outline;
   - Fox River and major water;
   - interstate, highway, and principal-road structure;
   - no mass of tiny building footprints.

2. **Regional view**
   - more road detail;
   - principal creeks and secondary water;
   - very large building footprints may begin to appear when visually useful.

3. **Local view**
   - progressively more roads and water;
   - building footprints appear according to usable on-screen size;
   - large buildings appear before small buildings.

4. **Neighborhood view**
   - complete local roads and creeks;
   - all buildings in the visible area;
   - inspection is available;
   - editing remains disabled until the maximum editing scale.

5. **Maximum editing view**
   - exact building footprints;
   - precise building hit testing;
   - classification controls may become available if authoritative saving is available.

The user does not select these bands. Normal zooming moves between them.

### 4.3 Navigation has no side effects

The following actions must never change any classification:

- opening the application;
- zooming;
- panning;
- returning to the county overview;
- loading a new map area;
- changing visible layers;
- selecting or deselecting a building for inspection;
- checking for updates;
- losing or regaining the server connection.

## 5. Building visibility and colors

Every building is rendered according to its current project classification:

| Classification | Color | Initial visibility |
|---|---|---|
| **Unclassified** | Gray | Shown |
| **Other** | Red | Shown |
| **Condominium** | Green | Shown |
| **Apartments** | Yellow | Shown |

Unclassified is the default state for every building that has no explicit project classification.

A missing, unavailable, or unrecognized classification value must display as Unclassified rather than being silently omitted.

## 6. Visibility filters

The user may independently show or hide:

- Unclassified;
- Other;
- Condominium;
- Apartments.

Filter changes are local view preferences. They do not modify the database or classification history.

When a class is hidden:

- buildings in that class are not drawn;
- they are not selected by pointer hit testing;
- their stored classifications remain unchanged;
- showing the class again restores them immediately.

The principal working filter is **Other**.

As obvious non-target buildings are marked Other, the user can hide Other and progressively reduce the visible workload. Gray Unclassified buildings then become the principal remaining work population, while confirmed green Condominium and yellow Apartments buildings remain available according to their filters.

At least one building class must remain visible. If the interface permits all classes to be hidden, it must make the resulting empty-building view explicit rather than appearing to have lost data.

## 7. Building inspection below editing scale

At neighborhood scale, a visible building may be inspected without being editable.

An inspection action may:

- highlight the building;
- show its project building identity;
- show its current classification;
- show available official-source attributes;
- show whether editing requires additional zoom;
- offer a deliberate action to zoom to editing scale.

Inspection must not:

- assign a class;
- create a history event;
- save a record;
- recenter repeatedly without user intent;
- expose another nearby building as though it were selected.

If precise hit testing is not reliable at the current scale, the application must require additional zoom instead of guessing.

## 8. Entering editing scale

Editing becomes possible only at the approved maximum editing scale.

The threshold must be based on reliable footprint selection, not merely on a cosmetic percentage label.

At editing scale:

- the exact selected footprint is visually distinct;
- neighboring buildings remain visible for context;
- the application identifies the selected project building;
- the current classification is explicit;
- saving capability is explicit;
- no classification is preselected as a pending change merely because the building was clicked.

The map may gently recenter the selected building when that improves classification work, but the user must remain able to pan away, deselect it, or select another building.

No persistent local grid appears around the building.

## 9. Classification workflow

### 9.1 Select a building

The user clicks one exact visible building at editing scale.

The application:

1. identifies the project building;
2. highlights only the selected footprint;
3. displays the current classification;
4. displays whether authoritative saving is available;
5. exposes the four classification choices only when editing is allowed.

Selection alone does not create a change.

### 9.2 Choose a classification

The user deliberately chooses one of:

- Unclassified;
- Other;
- Condominium;
- Apartments.

The chosen value becomes a proposed change only when it differs from the current authoritative value.

If the user chooses the existing value, the application performs no write and creates no redundant history event.

### 9.3 Save lifecycle

A classification change must pass through visible states:

1. **Current** — the authoritative classification before the change.
2. **Pending** — the user has chosen a different classification, but it is not yet authoritative.
3. **Saving** — the application has submitted the change.
4. **Saved** — the server confirmed the transaction and returned the authoritative result.
5. **Failed** — the transaction was rejected, interrupted, or could not be confirmed.

The map may preview the pending color, but it must visually distinguish Pending from Saved.

A building must not be presented as authoritatively reclassified until the save confirmation is received.

### 9.4 Successful save

After a successful save:

- the selected building uses the new authoritative color;
- the current classification display updates;
- the server-provided modification identity or timestamp is retained;
- the classification history contains the change;
- active filters are applied immediately.

If the building is changed to Other while Other is hidden, it may disappear after confirmation. The application must make this outcome understandable and must not appear to have lost the save.

A brief saved confirmation may remain visible without interrupting continued work.

### 9.5 Failed save

When saving fails:

- the application reports that the change is not authoritative;
- the prior authoritative classification remains recoverable and explicit;
- the error is distinguishable from a local rendering failure;
- the user may retry after the cause is resolved;
- no false Saved state is shown.

The application must not silently queue a local write unless the later runtime-topology contract explicitly authorizes a pending-change journal.

## 10. Primary elimination workflow

The normal high-volume workflow is:

1. Navigate to a local area.
2. Zoom to editing scale.
3. Identify an obvious non-target building.
4. Select the exact footprint.
5. Mark it Other.
6. Receive Saved confirmation.
7. Continue to the next obvious non-target building.
8. Hide Other when useful.
9. Work through the increasingly sparse set of Unclassified buildings.
10. Mark confirmed targets Condominium or Apartments.

The interface should eventually support efficient repetition, but speed must not be achieved by restoring cell-based bulk classification or automatic classification.

Any future keyboard shortcut or rapid-classification aid must:

- operate on one explicitly selected building;
- display the pending class;
- preserve the save lifecycle;
- support correction;
- avoid changing hidden or unselected buildings.

## 11. Correcting a classification

A classified building may later be corrected.

The correction workflow is the same as the initial classification workflow:

1. show the building’s current authoritative classification;
2. select a different classification deliberately;
3. submit the change;
4. receive confirmation;
5. retain the prior value in append-only history.

Returning a building to Unclassified is a valid correction. It does not delete classification history.

A correction must never overwrite or remove the historical record of the previous classification.

## 12. Undo behavior

A deliberate undo may be offered for the most recent confirmed classification action.

Undo must:

- identify the exact building and prior state;
- create a new authoritative classification event;
- preserve both the original action and the reversal in history;
- require server confirmation;
- fail truthfully if the authoritative state has changed since the action.

Undo is not equivalent to deleting history.

The detailed undo contract belongs to the later server/API milestone.

## 13. Server-unavailable workflow

The offline map remains usable when the Kane Condo server cannot be reached.

The user may continue to:

- open the accepted local map;
- pan and zoom;
- inspect visible buildings;
- view the local classification snapshot;
- apply visibility filters;
- inspect the local package and release identities.

The application must visibly report that the server is unavailable.

Until the runtime-topology contract explicitly decides otherwise:

- authoritative editing is unavailable;
- classification controls are disabled or clearly marked unavailable;
- no classification is claimed to be saved;
- no silent local queue is created;
- update checking and package publication are unavailable.

This is the safe default. Batch 004 may later authorize and define a USB-local pending-change journal, but this document does not assume one.

## 14. Reconnection workflow

When the server becomes reachable again, the application may refresh:

- server health;
- API compatibility;
- current classification state for the selected building;
- accepted county-release status;
- update availability;
- package status.

Reconnection itself must not:

- submit an unapproved classification;
- replay browser clicks;
- alter filters;
- replace the local map package automatically;
- discard the user’s current map location.

If a pending-change journal is later approved, its reconciliation behavior must be defined separately before implementation.

## 15. Update-status workflow

### 15.1 Passive status

The application should make the following information available without obstructing normal map use:

- local map-package version;
- accepted county-data release identity;
- classification snapshot identity;
- last successful source check;
- server reachability;
- whether a newer validated package is available.

### 15.2 Check for updates

The user may deliberately request a current update check when the server is reachable.

The result must distinguish:

- Up to date;
- New source detected;
- Processing;
- Review required;
- Ready to install;
- Installed;
- Failed;
- Server unavailable.

A source check does not install data.

### 15.3 Candidate processing

Heavy work occurs on the server. The application only reports:

- current processing stage;
- candidate source identities;
- comparison counts;
- validation result;
- whether project-building identity review is required;
- whether a complete package is ready.

The browser must remain usable while server processing continues.

### 15.4 Review required

Review is limited to changed official building data that may affect existing Kane Condo identities or classifications.

Examples include:

- one classified footprint splitting into several;
- multiple classified footprints merging;
- a classified footprint disappearing;
- a replacement footprint with no reliable identity match.

The application must not create a generic county-wide warning layer merely because official geometry intersects an old County Field Map cell state.

### 15.5 Installation

Installation of a validated offline package is a separate, deliberate operation.

The detailed installation workflow is deferred, but the user must be able to determine:

- which package is installed;
- which package is available;
- whether integrity checks passed;
- whether the prior package is retained;
- whether rollback is available.

Detection, processing, promotion, publication, download, installation, and activation are distinct states.

## 16. Closing the application

Before closing, the application must truthfully report whether:

- no classification action is in progress;
- a save is still awaiting confirmation;
- the server is unavailable;
- the local package remains valid;
- an update is available but not installed.

Closing the browser must not be treated as a successful save.

If a classification is still Pending or Saving, the application should warn the user that the proposed change may not be authoritative.

The application must not perform a new classification merely to finalize shutdown.

## 17. Recovery expectations

After reopening the application:

- confirmed classifications are recovered from authoritative server data when connected;
- the offline snapshot provides the last published classifications when disconnected;
- map filters may use approved local preferences;
- no classification is reconstructed from visual color alone;
- no incomplete save is assumed successful;
- the local map package reports its exact identity.

Database restoration, package rollback, and USB reconstruction are defined in later milestones.

## 18. User-visible invariants

The following statements must always remain true:

1. A map-navigation action never changes a building.
2. A building click never classifies it.
3. A hidden building remains classified.
4. A pending color is not presented as a saved classification.
5. A failed save does not become authoritative.
6. An unavailable server does not disable offline rendering.
7. An update check does not install an update.
8. A detected source change does not replace accepted data.
9. An official footprint change does not silently erase a project classification.
10. A correction preserves history.
11. No County Field Map grid or cell state appears.
12. The user can identify the active local map package and data release.

## 19. Deferred workflow decisions

This document intentionally leaves the following for later approved documents:

- whether offline classification changes may be journaled locally;
- the exact numeric editing threshold;
- the exact selection and recentering presentation;
- keyboard shortcuts or rapid-classification controls;
- whether map position and filter preferences persist locally;
- package installation automation;
- detailed ambiguous-identity review screens;
- server authentication and session behavior;
- classification notes, evidence, or confidence fields;
- address or parcel-assisted navigation.

Deferring these decisions does not weaken the required user-visible invariants.

## 20. Acceptance checklist

Batch 002 is accepted when the project owner confirms that this document correctly defines:

- startup and package validation;
- full-county opening behavior;
- continuous map navigation;
- progressive detail;
- building visibility and filters;
- inspection below editing scale;
- deliberate building selection;
- the classification save lifecycle;
- the Other-elimination workflow;
- correction and undo expectations;
- server-unavailable behavior;
- update-status behavior;
- shutdown and recovery;
- actions that must never change data.

Approval of this document does not authorize implementation.
