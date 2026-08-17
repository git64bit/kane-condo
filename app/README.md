# Kane Condo local browser application

Batch 034 established the local read-only application shell and validated package-open boundary.
Batch 035 added the fitted full-county opening view. Batch 036 adds only continuous browser-side
pan and zoom. It does not add road, water, or building LOD rendering, hit testing,
classification controls, editing, or contact with the future private Kane Condo API.

## Local-origin contract

Run the application against one externally generated Milestone 3 render package:

```bash
bash app/kane-local.sh /path/to/render-package
```

The current development/workstation server binds to `127.0.0.1:8765` by default and serves:

- the versioned browser shell at `/`;
- a generated local configuration at `/config.json`;
- the selected external package under `/package/`.

An alternate loopback port may be selected with `--port`. Non-loopback bind addresses are rejected.
The package remains external generated data and is not copied into Git. Application behavior remains
in HTML, CSS, and browser JavaScript; the local host is only a delivery mechanism.

## Package-open behavior

The browser loads `/config.json`, then `render-package-manifest.json`. Before opening the map it verifies:

- the local runtime configuration format/version;
- the exact Batch 032 manifest format/version and field inventory;
- the five required component roles, filenames, formats, versions, byte lengths, and SHA-256 values;
- the manifest's base-geometry, classification, and package-content self-identities;
- the byte length and SHA-256 of every required local component;
- the internal format/version of the two small JSON components.

The user interface reports precise configuration, compatibility, missing-resource, length, and hash errors.
An invalid package never opens a county map.

## Full-county opening view

After package validation succeeds, the browser loads the already-validated `county-overview.json` component.
It requires the Batch 027 overview format/version, EPSG:4326, Kane County identity, the same accepted county-boundary release recorded in the package manifest, internally consistent exact fit metadata, and valid closed exterior rings.

The opening map uses the exact accepted source bounds from the overview's `fit.bounds` field. A small deterministic padding is added to the SVG view box, and `preserveAspectRatio="xMidYMid meet"` keeps the complete county extent visible. The simplified exterior rings are used only for overview drawing; they do not replace the exact source bounds.

## Batch 036 continuous navigation

Navigation changes only the SVG geographic `viewBox` held in browser memory:

- primary-pointer drag pans continuously;
- mouse-wheel or trackpad-wheel input zooms around the pointer's geographic position;
- `Reset county view` restores the exact Batch 035 fitted opening view;
- browser resize preserves the current geographic center and zoom because it does not replace the current `viewBox`;
- pointer navigation uses SVG `preserveAspectRatio="xMidYMid meet"` geometry, including any letterbox margins.

The navigation code performs no fetches, API calls, local/session storage writes, IndexedDB writes,
or package mutations. Panning and zooming therefore have no data side effects. Numeric zoom limits are
only guards against degenerate floating-point extents; they do not define a semantic editing scale or LOD policy.

Batch 036 still renders only the county outline. Roads begin in Batch 037.

## Acceptance environment

The development/processing orchestrator is not the Kane Condo user workstation. Batch 036 acceptance on the orchestrator is headless: run the repository/app tests and verify the bounded source changes. Do not require a desktop browser on the orchestrator, do not ask the user to open an orchestrator loopback URL from another machine, and do not require workstation USB access.

Physical browser, Windows/Ubuntu workstation, and USB-runtime acceptance is reserved for Milestone 4 Batch 042 unless an earlier batch explicitly defines a target-workstation test. Lack of browser or accessible USB hardware on the orchestrator is therefore not a Batch 036 failure.

## Tests

```bash
bash app/run-tests.sh
```

The standard-library suite continues to verify the loopback server and package-serving boundary. It also verifies that the permanent shell exposes the navigation control and that the Batch 036 navigation section contains no network or browser-persistence operations. When Node.js is available, the suite directly exercises overview validation, viewport letterboxing math, continuous pan transforms, pointer-anchored zoom, reset behavior, and resize-invariant geographic center calculations from `app/app.js`. Absence of Node.js skips only that browser-math probe and does not add a runtime dependency.

Production county data is never committed.
