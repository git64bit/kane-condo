# Kane Condo local browser application

Batch 034 established the local read-only application shell and validated package-open boundary. Batch 035 added the full-county opening view. Batch 036 added continuous browser-side pan and zoom. Batch 037 added progressive road rendering. Batch 038 added progressive water rendering. Batch 039 added progressive building rendering. Batch 040 adds only offline classification colors. It does not add visibility filters, hit testing, editing, or contact with the future private Kane Condo API.

## Local-origin contract

Run the application against one externally generated Milestone 3 render package:

```bash
bash app/kane-local.sh /path/to/render-package
```

The current development/workstation server binds to `127.0.0.1:8765` by default and serves the browser shell, generated local configuration, and selected external package. The package remains generated external data and is not copied into Git. Application behavior remains in HTML, CSS, and browser JavaScript; the local host is only a delivery mechanism.

## Package-open behavior

The browser validates the Batch 032 manifest and all five required component byte lengths and SHA-256 values before opening the map. Batch 037 extended the validator with an optional in-memory component callback. Batches 038–040 reuse that same boundary so already verified road, water, building, and classification-snapshot bytes are handed directly to browser logic rather than fetched again.

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

## Batch 038 progressive water

The browser consumes the existing Batch 029 `water-lod.krf` container without changing its format. It validates:

- `KCRW029` magic, format/version, and EPSG:4326;
- Kane County identity and both accepted `water-fox-river` and `water-creeks` releases against the validated manifest;
- canonical JSON index structure and monotonic `overview`, `context`, `detail` levels;
- every-level Fox River completeness, overview creek exclusion, and exact-detail completeness;
- contiguous chunk framing, compressed/decompressed SHA-256 values, canonical JSON records, and level/dataset counts;
- Polygon/MultiPolygon geometry for Fox River and LineString/MultiLineString geometry for creeks.

Water uses the same deterministic zoom thresholds as roads: below `4x` uses `overview`, `4x` through less than `16x` uses `context`, and `16x` or greater uses `detail`. Fox River polygons and creek lines are rendered as separate SVG paths. The previous complete water level remains visible until the requested level has fully decoded, so chunking remains invisible.

Water chunk decompression uses the browser `DecompressionStream("deflate")` API. Python does not parse or decompress water data, and no server API is involved.

## Batch 039 progressive buildings

The browser consumes the existing Batch 030 `buildings-lod.krf` container without changing its format. It validates:

- `KCBD030` magic, format/version, and EPSG:4326;
- Kane County identity and the accepted `buildings` release against the validated manifest;
- the project identity contract requiring `building_key` / `kane-condo-project-building`;
- canonical JSON index structure and monotonic `context`, `neighborhood`, `editing` levels;
- complete accepted building inventory at neighborhood and editing levels;
- zero simplification and exact source vertex preservation at editing level;
- contiguous chunk framing and compressed/decompressed SHA-256 values;
- canonical records, unique `building_key` values, and Polygon/MultiPolygon geometry with valid closed rings.

Building thresholds are deterministic browser constants based only on Batch 036 zoom ratio: below `8x` uses `context`, `8x` through less than `32x` uses `neighborhood`, and `32x` or greater uses `editing`. The visible building path is replaced only after the requested level has fully decoded, so the previous complete level remains visible and chunk/Morton boundaries remain invisible.

Batch 039 preserved each decoded record's project-owned `building_key`. Batch 040 uses that identity only for the validated offline classification join; no source attribute or footprint geometry is interpreted as a classification.

Building chunk decompression uses the browser `DecompressionStream("deflate")` API. Python does not parse or decompress building data, and no server API is involved.

## Batch 040 classification colors

The browser consumes the already package-validated Batch 031 `classification-snapshot.json` bytes in memory. It requires the exact four-class contract and sparse default semantics: `unclassified` is the default, while explicit records contain only `other`, `condominium`, or `apartments` keyed by `building_key`.

The snapshot must match the package manifest and building KRF on accepted building release identity and render-building count. Its `render_identity_sha256`, explicit count, and explicit-record SHA-256 must match the manifest's classification compatibility metadata. Records must be strictly sorted, unique, and use valid project building keys.

Visible building geometry remains controlled by Batch 039 LOD selection. Within each decoded level, geometry is grouped into four SVG paths by project `building_key`: Unclassified gray, Other red, Condominium green, and Apartments yellow. A missing or unrecognized lookup value resolves only to Unclassified gray. The snapshot does not change geometry, LOD thresholds, package data, or authoritative state.

Batch 040 adds no visibility controls; those belong to Batch 041.

## Acceptance environment

The development/processing orchestrator is not the Kane Condo user workstation. Batch 040 acceptance on the orchestrator is headless: run the repository/app tests and verify the bounded source changes. Do not require a desktop browser on the orchestrator, do not ask the user to open an orchestrator loopback URL from another machine, and do not require workstation USB access.

Physical browser, Windows/Ubuntu workstation, and USB-runtime acceptance is reserved for Milestone 4 Batch 042 unless an earlier batch explicitly defines a target-workstation test.

## Tests

```bash
bash app/run-tests.sh
```

The standard-library suite continues to verify the loopback/static-serving boundary and headless acceptance rule. When Node.js is available it also builds a disposable three-level zlib KRF in memory and exercises browser road/water/building KRF parsing, decompression, hashes, record validation, LOD thresholds, project building identity, Batch 031 classification snapshot compatibility, sparse default behavior, four-class path grouping, and existing county/navigation math. Absence of Node.js skips only that browser probe and does not add a runtime dependency.

Production county data is never committed.
