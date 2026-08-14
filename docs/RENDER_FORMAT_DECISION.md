# Batch 025 render-format decision

## Decision

Kane Condo selects a **single flat-file render container** for the Milestone 3 offline render package.

The container stores one canonical byte-range index followed by compressed chunk payloads in one replaceable file. The final package schema, level-of-detail structure, manifest format, and production chunking rules remain future Milestone 3 work.

This decision selects the **container format only**. It does not freeze a production chunk size. The 256-record benchmark result is retained as the current development reference for detailed geometry because it produced the best close-scale/hit-test behavior, but Batches 027–030 must choose chunking appropriate to overview and level-of-detail layers.

## Evidence identity

The decision is based on the canonical real-data Batch 025 development benchmark produced on the Linux orchestrator.

- Accepted SSOT: `8446dec1345625d28437748b77bdbe377033b61e`
- Benchmark report SHA-256: `cf1f07a1972c2bcdb750d306a98b567f2cd3483144cded8e60e630eca1c16817`
- Authoritative database SHA-256: `164200d4d7262874dcc03239c8258446a4d7bb81ce84daf46dc4937d6c97fe86`
- Canonical staging record count: `236556`
- Canonical staging SHA-256: `943671bad375b6492fe0efdec55397dc5c2959593c8d9d7c1e750781181242b0`
- Measurement context: `development-orchestrator`
- Filesystem: `ext4`
- Cache policy: warm-cache/index-open and warm query measurements; no cold-start claim
- Physical USB and workstation deployment validation: deferred until application completion

The benchmark reused the established Milestone 2 validators and required the exact accepted identities for buildings, county boundary, roads, creeks, and Fox River. All validators passed.

## Correctness equivalence

The three candidates carried identical compressed chunk payloads and were required to return complete results. For all tested chunk sizes (`256`, `512`, and `2048` records):

- all candidates contained the full `236556` canonical records;
- every viewport result identity hash was exactly equal across directory, SQLite, and flat candidates;
- exact building hit testing returned identical project-building identities;
- malformed/truncated indexes and payload tampering were rejected;
- classification values were not embedded in base geometry;
- changing external classification overlays changed resolved colors while base artifact hashes remained unchanged.

The format choice therefore does not trade away dataset correctness.

## Measured comparison

The benchmark intentionally used no weighted composite score.

### 256-record benchmark chunks

| Candidate | Package bytes | Warm index-open median | Hit-test median | Replacement units |
|---|---:|---:|---:|---:|
| Directory | 56,955,650 | 4.042 ms | 62.503 ms | 927 |
| SQLite | 57,593,856 | 19.443 ms | 62.682 ms | 1 |
| **Flat** | **56,921,446** | **3.073 ms** | **62.509 ms** | **1** |

Selected viewport medians at this chunk size:

| View | Directory | SQLite | Flat |
|---|---:|---:|---:|
| County overview | 5422.076 ms | 6003.451 ms | **5256.716 ms** |
| Dense buildings | **545.123 ms** | 574.483 ms | 574.088 ms |
| Medium buildings | 96.367 ms | 98.704 ms | **95.225 ms** |
| Sparse buildings | 30.419 ms | 31.489 ms | **28.669 ms** |
| Road-heavy | 349.593 ms | 398.461 ms | **338.737 ms** |
| Water-heavy | **57.564 ms** | 57.960 ms | 57.822 ms |
| Editing-scale building | 75.611 ms | **69.486 ms** | 74.881 ms |

The candidates are close on detailed query latency, while the flat format combines that performance with one-file replacement and the smallest package.

### Chunk-size sensitivity

| Chunk size | Candidate | Package bytes | Warm index-open median | Hit-test median |
|---:|---|---:|---:|---:|
| 512 | Directory | 56,489,274 | 2.089 ms | 81.555 ms |
| 512 | SQLite | 56,819,712 | 16.966 ms | 81.220 ms |
| 512 | **Flat** | **56,472,164** | **1.507 ms** | **81.026 ms** |
| 2048 | Directory | 56,140,856 | 0.563 ms | 180.111 ms |
| 2048 | SQLite | 56,287,232 | 15.366 ms | 180.912 ms |
| 2048 | **Flat** | **56,136,585** | **0.430 ms** | **176.726 ms** |

Smaller chunks substantially improve detailed and hit-test access at the cost of more index entries and somewhat slower full-county reads. Because later batches add dedicated overview and progressive level-of-detail representations, Batch 025 does not convert this sensitivity test into a permanent chunk-size contract.

## Why the flat container is selected

### Against the directory candidate

The directory candidate performs well, but its replacement unit count grows directly with chunk count: `927` files at 256 records/chunk, `465` at 512, and `118` at 2048. A refresh therefore requires coordinated replacement of a multi-file tree rather than one atomic package component. The flat candidate gives comparable or better measured performance while retaining a single replacement unit.

### Against the SQLite candidate

SQLite also provides one-file replacement and correct results, but it was the largest candidate at every tested chunk size and had materially slower warm index-open measurements (`15–19 ms` versus approximately `0.4–3.1 ms` for flat). It also adds an SQLite runtime dependency where the flat format needs only ordinary seek/read operations plus the same zlib/JSON payload decoding used by the other candidates. The benchmark did not show a query-performance advantage large enough to offset those costs.

### Cross-platform implications

The selected flat container uses ordinary byte seek/read operations and a documented custom index reader. Those primitives are available on both Windows and Ubuntu. Exact application bundling and physical deployment validation are intentionally deferred until the application exists; Batch 025 does not claim workstation performance acceptance.

## Classification independence

The benchmark confirmed that the base render container does not contain classification values. Two different external classification overlays produced different resolved outputs while the base flat artifact hash remained unchanged. This satisfies the requirement that classification colors can change without regenerating all base geometry and leaves Batch 031 free to define the compact classification snapshot separately.

## Consequences for later batches

- Batch 026 may audit the VOID mask without changing this container decision.
- Batches 027–030 should generate overview and level-of-detail payloads for the selected flat container.
- Production chunk sizes remain open until those LOD access patterns are measured.
- Batch 031 remains responsible for the independent classification snapshot.
- Batch 032 remains responsible for package manifest/versioning/integrity rules; this decision does not preempt that schema.
- Batch 033 remains responsible for reproducible package generation.
- Physical Windows/Ubuntu and USB performance acceptance remains deferred to the application-stage performance work.

## Rejected alternatives

- **Directory tree:** rejected as the primary container because multi-file replacement complexity is unnecessary given equivalent correctness and comparable performance from a single file.
- **SQLite container:** rejected as the primary render container because the real-data benchmark showed higher package size and substantially slower index-open time without a compensating query advantage.

## Status

**Accepted Batch 025 decision: single flat-file render container.**

No full renderer is implemented by this batch.
