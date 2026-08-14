# Water level-of-detail payload

Batch 029 defines deterministic water levels of detail for the coordinated accepted Kane County
Fox River and creek releases. The generated water layer is derived data and remains outside Git.

## Source semantics and level membership

The accepted source profiles preserve only `OBJECTID`. They do not preserve stream names,
hydrologic order, drainage area, or another official importance class. Batch 029 therefore does
not invent creek classes.

The levels are:

- `overview`: every accepted Fox River feature, with no creeks;
- `context`: every Fox River feature plus enough longest creek features to cover 60% of total
  accepted creek coordinate-length score;
- `detail`: every accepted Fox River and creek feature.

Creeks are ranked from longest to shortest by deterministic coordinate-length score, with source
identity as the tie breaker. The sets are monotonic. Fox River geometry is never removed from a
level, so major water remains available from county scale onward.

## Geometry detail

All coordinates remain EPSG:4326.

- `overview` simplifies Fox River geometry with tolerance `water_extent / 2048`;
- `context` simplifies Fox River and selected creeks with tolerance `water_extent / 8192`;
- `detail` uses zero tolerance and retains the exact accepted source coordinates.

Line simplification retains component endpoints. Polygon simplification retains every source ring,
keeps rings closed, and never replaces a valid source ring with a degenerate result. Features are
never clipped to chunk boundaries. Internal chunking therefore cannot create a geometric seam at a
chunk edge.

## Flat container

The conventional generated file is `water-lod.krf`. It follows the Batch 025 flat-container
direction without defining the final package manifest.

The file contains:

1. ASCII magic `KCRW029\n`;
2. one unsigned 64-bit big-endian canonical-index byte length;
3. one canonical UTF-8 JSON index;
4. contiguous zlib-compressed canonical JSON record chunks.

Chunks contain at most 256 whole features. Chunk offsets are relative to the payload area. Each
chunk records bounds, feature count, compressed and uncompressed lengths, payload SHA-256, and
canonical-record SHA-256. Records use deterministic 16-bit Morton ordering only as an invisible
storage detail; it is not a user-facing grid.

The index records both accepted source-release identities, full water bounds, level definitions,
counts, simplification tolerances, vertex counts, and chunk inventory. It contains no timestamp or
machine-specific value, so the same accepted database produces identical bytes.

## Coordinated water context

Fox River and creeks are read together from the same authoritative GeoPackage build. Generation
fails if either dataset has zero or multiple accepted releases, if release counts disagree with
stored rows, or if accepted geometry hashes/bounds are inconsistent.

## Explicit exclusions

Batch 029 does not implement a renderer, zoom thresholds, styling, roads, buildings,
classification, package manifest, deployment behavior, or browser code. It does not use County
Field Map sectors, cells, grids, or the rejected VOID mask.

Later package and renderer batches decide when each level becomes visible. Batch 029 guarantees
that Fox River is available at overview scale, creek detail increases monotonically, and the detail
level contains the complete exact accepted water context.
