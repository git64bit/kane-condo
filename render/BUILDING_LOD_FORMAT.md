# Building level-of-detail payload

Batch 030 defines deterministic building levels of detail for the accepted Kane County building release. The generated building layer is derived data and remains outside Git.

## Project identity

Every generated building record is keyed by Kane Condo `building_key`, the project-owned identity used by classification operations. County `FPId` remains only source provenance and is not the classification join key.

Package generation requires every footprint in the accepted building release to have exactly one confirmed mapping to an active project building. An absent or ambiguous mapping rejects the build rather than guessing which project identity should receive future classification state.

## Progressive selection

The accepted building source contains descriptive attributes, but Batch 030 does not infer building use, importance, or classification from them. Progressive appearance is based only on deterministic footprint geometry area computed from accepted EPSG:4326 coordinates.

The levels are:

- `context`: the largest footprints, selected in descending area order until at least 35% of total accepted footprint-area score is represented;
- `neighborhood`: 100% of accepted buildings with simplified geometry;
- `editing`: 100% of accepted buildings with exact accepted source geometry.

Thus large footprints are available before small footprints, while every accepted building is available by neighborhood scale. The renderer will decide the actual visibility thresholds in a later batch.

## Geometry detail

All coordinates remain EPSG:4326.

- `context` uses Ramer-Douglas-Peucker ring tolerance `building_extent / 8192`;
- `neighborhood` uses tolerance `building_extent / 32768`;
- `editing` uses zero tolerance and preserves exact accepted Polygon/MultiPolygon coordinates.

Closed rings remain closed and retain at least three distinct vertices. Whole building features are never clipped at internal chunk boundaries.

## Flat container

The conventional generated file is `buildings-lod.krf`. It follows the Batch 025 flat-container direction without defining the final package manifest.

The file contains:

1. ASCII magic `KCBD030\n`;
2. one unsigned 64-bit big-endian canonical-index byte length;
3. one canonical UTF-8 JSON index;
4. contiguous zlib-compressed canonical JSON record chunks.

Each chunk contains at most 512 whole building features and records bounds, compressed and uncompressed lengths, payload SHA-256, and canonical-record SHA-256. Records are ordered spatially using deterministic 16-bit Morton order. This is an invisible storage index, not a user-visible grid.

The index records accepted building-release identity, county identity, project-identity contract, building bounds, level definitions, counts, simplification tolerances, vertex counts, and chunk inventory. It contains no timestamp or machine-specific value, so the same accepted database produces identical bytes.

## Explicit exclusions

Batch 030 does not include classifications, classification colors, filters, hit testing, renderer behavior, zoom thresholds, roads, water, package manifest, browser code, or deployment behavior. It does not use County Field Map sectors, cells, grids, or the rejected VOID mask.

Batch 031 may generate a classification snapshot keyed by the same `building_key` without regenerating this base geometry.
