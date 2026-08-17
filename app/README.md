# Kane Condo local browser application

Batch 034 established the local read-only application shell and validated package-open boundary.
Batch 035 adds only the full-county opening view. It does not add pan/zoom, LOD rendering,
hit testing, classification controls, editing, or contact with the future private Kane Condo API.

## Local-origin contract

Run the application against one externally generated Milestone 3 render package:

```bash
bash app/kane-local.sh /path/to/render-package
```

The server binds to `127.0.0.1:8765` by default and serves:

- the versioned browser shell at `/`;
- a generated local configuration at `/config.json`;
- the selected external package under `/package/`.

An alternate loopback port may be selected with `--port`. Non-loopback bind addresses are rejected.
The package remains external generated data and is not copied into Git.

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

## Batch 035 full-county opening view

After package validation succeeds, the browser loads the already-validated `county-overview.json` component.
It requires the Batch 027 overview format/version, EPSG:4326, Kane County identity, the same accepted county-boundary release recorded in the package manifest, internally consistent exact fit metadata, and valid closed exterior rings.

The map uses the exact accepted source bounds from the overview's `fit.bounds` field. A small deterministic padding is added to the SVG view box, and `preserveAspectRatio="xMidYMid meet"` keeps the complete county extent visible as the browser viewport changes size. The simplified exterior rings are used only for this overview drawing; they do not replace the exact source bounds.

Batch 035 does not decode roads, water, or building LOD containers and does not add navigation behavior. Those remain later Milestone 4 batches.

## Acceptance environment

The development/processing orchestrator is not the Kane Condo user workstation. Batch 035 acceptance on the orchestrator is headless: run the repository/app tests and verify the bounded source changes. Do not require a desktop browser on the orchestrator, do not ask the user to open an orchestrator loopback URL from another machine, and do not require workstation USB access.

Physical browser, Windows/Ubuntu workstation, and USB-runtime acceptance is reserved for Milestone 4 Batch 042 unless an earlier batch explicitly defines a target-workstation test. Lack of browser or accessible USB hardware on the orchestrator is therefore not a Batch 035 failure.

## Tests

```bash
bash app/run-tests.sh
```

The committed standard-library test suite continues to verify loopback-only serving, external-package routing, generated configuration, HEAD behavior, disabled directory listings, and path isolation. It also checks that the permanent browser shell contains the Batch 035 SVG map viewport. When Node.js is available, the same suite executes the exported browser overview validation, view-box fitting, path-generation, and incompatible-release cases directly from `app/app.js`; absence of Node.js skips only that browser-logic probe and does not add a runtime dependency.

Production county data is never committed.
