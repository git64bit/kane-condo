# Kane Condo local browser application

Batch 034 established the local read-only application shell and validated package-open boundary. Batch 035 added the full-county opening view. Batch 036 added continuous browser-side pan and zoom. Batch 037 adds only progressive road rendering. It does not add water, buildings, hit testing, classification controls, editing, or contact with the future private Kane Condo API.

## Local-origin contract

Run the application against one externally generated Milestone 3 render package:

```bash
bash app/kane-local.sh /path/to/render-package
```

The current development/workstation server binds to `127.0.0.1:8765` by default and serves the browser shell, generated local configuration, and selected external package. The package remains generated external data and is not copied into Git. Application behavior remains in HTML, CSS, and browser JavaScript; the local host is only a delivery mechanism.

## Package-open behavior

The browser validates the Batch 032 manifest and all five required component byte lengths and SHA-256 values before opening the map. Batch 037 extends the validator with an optional in-memory component callback so the already verified `roads-lod.krf` bytes can be handed directly to the renderer rather than fetched again.

## Full-county opening and navigation

The map uses exact source bounds from `county-overview.json` for the opening view. Dragging pans, wheel/trackpad input zooms around the pointer, reset restores the county fit, and resize preserves the current geographic view. Navigation mutates only transient SVG viewport state and has no data side effects.

## Batch 037 progressive roads

The browser consumes the existing Batch 028 `roads-lod.krf` container without changing its format. It validates:

- `KCRD028` magic, format/version, and EPSG:4326;
- Kane County and accepted road-release identity against the validated manifest;
- canonical JSON index structure and monotonic `orientation`, `context`, `detail` levels;
- contiguous chunk framing and level feature counts;
- compressed and decompressed SHA-256 values;
- canonical JSON records and supported LineString/MultiLineString geometry.

Renderer LOD thresholds are deterministic browser constants based only on Batch 036 zoom ratio:

- zoom below `4x`: `orientation`;
- zoom `4x` through less than `16x`: `context`;
- zoom `16x` or greater: `detail`.

The visible road path is replaced only after the requested LOD has fully decoded. The previous level therefore remains visible during a transition. Chunk boundaries remain a storage detail and are never exposed as map partitions.

Road chunk decompression uses the browser `DecompressionStream("deflate")` API. Python does not parse or decompress road data, and no server API is involved.

## Acceptance environment

The development/processing orchestrator is not the Kane Condo user workstation. Batch 037 acceptance on the orchestrator is headless: run the repository/app tests and verify the bounded source changes. Do not require a desktop browser on the orchestrator, do not ask the user to open an orchestrator loopback URL from another machine, and do not require workstation USB access.

Physical browser, Windows/Ubuntu workstation, and USB-runtime acceptance is reserved for Milestone 4 Batch 042 unless an earlier batch explicitly defines a target-workstation test.

## Tests

```bash
bash app/run-tests.sh
```

The standard-library suite continues to verify the loopback/static-serving boundary and headless acceptance rule. When Node.js is available it also builds a disposable three-level zlib KRF in memory and exercises browser KRF parsing, decompression, hashes, record validation, LOD thresholds, exact-detail completeness, road path generation, and existing county/navigation math. Absence of Node.js skips only that browser probe and does not add a runtime dependency.

Production county data is never committed.
