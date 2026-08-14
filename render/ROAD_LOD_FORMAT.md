# Road level-of-detail payload

Batch 028 defines deterministic road levels of detail for the accepted Kane County road release.
The generated road layer is derived data and remains outside Git.

## Source limitation and selection rule

The accepted road source profile preserves only `OBJECTID`. It does not preserve a road name,
route number, ownership, functional class, or pavement class. Batch 028 therefore does **not**
claim that it can identify officially classified "major roads".

Instead, the two broad-scale levels are selected from the accepted network by a deterministic
coordinate-length score. Features are ranked from longest to shortest, with source identity as
the tie breaker:

- `orientation` includes enough longest features to cover 35% of total accepted coordinate-length score;
- `context` includes enough longest features to cover 75%;
- `detail` contains 100% of accepted road features.

The sets are monotonic: `orientation` is a subset of `context`, which is a subset of `detail`.
This gives broad county views a sparse orienting road skeleton without inventing unavailable
source semantics.

## Geometry detail

All road coordinates remain EPSG:4326.

- `orientation` uses Ramer-Douglas-Peucker tolerance `road_extent / 2048`;
- `context` uses tolerance `road_extent / 8192`;
- `detail` uses zero tolerance and retains the exact accepted source coordinates.

Simplification is performed independently for each complete LineString component and always
retains its endpoints. Features are never clipped to chunk boundaries. Consequently, internal
chunking cannot introduce a geometric seam at a chunk edge.

## Flat container

The conventional generated file is `roads-lod.krf`. It follows the Batch 025 flat-container
direction without defining the final package manifest.

The file contains:

1. ASCII magic `KCRD028\n`;
2. one unsigned 64-bit big-endian canonical-index byte length;
3. one canonical UTF-8 JSON index;
4. contiguous zlib-compressed canonical JSON record chunks.

Chunk offsets are relative to the start of the payload area. Each chunk contains at most 256
whole road features and records its bounds, compressed and uncompressed lengths, payload SHA-256,
and canonical-record SHA-256. Records are spatially ordered by deterministic 16-bit Morton order,
but that ordering is an invisible storage detail and is not a user-facing grid.

The index records accepted release identity, road bounds, level definitions, counts, simplification
tolerances, vertex counts, and chunk inventory. It contains no timestamp or machine-specific value,
so the same accepted database produces identical bytes.

## Explicit exclusions

Batch 028 does not implement a renderer, zoom thresholds, road styling, water, buildings,
classification, package manifest, deployment behavior, or browser code. It does not use County
Field Map sectors, cells, grids, or the rejected VOID mask.

Later package and renderer batches decide when each level becomes visible. Batch 028 only guarantees
that a sparse orientation representation exists, context adds detail monotonically, and the detail
level contains the complete exact accepted road network.
