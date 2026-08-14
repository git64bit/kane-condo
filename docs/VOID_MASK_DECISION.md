# Batch 026 VOID-mask decision

## Decision

Kane Condo **rejects the historical County Field Map VOID mask** for the Milestone 3 render-package pipeline.

The historical `muted` practical-cell state is retained only as external audit provenance. It must not suppress package content, omit chunks, clip geometry, decide feature visibility, define geographic truth, or appear in the Kane Condo interface.

Batches 027–030 must derive overview and level-of-detail content directly from accepted Kane Condo geometry and the selected flat render-container design.

## Evidence identity

The decision is based on the completed Batch 026 real-data audit against accepted SSOT `bb28ee0c668b2759be474e03e65db1f26f44e5ee`.

- Audit report SHA-256: `364e1fc008cdf767ea74587075135811b9d5c75cbd8ab7a3b9cf814cc72bc0ee`
- Authoritative database SHA-256: `164200d4d7262874dcc03239c8258446a4d7bb81ce84daf46dc4937d6c97fe86`
- Historical donor commit: `0911eeefeafbb18c58af0618200ba9edead29bdc`
- Historical donor archive SHA-256: `19506566f787b11a02036dce8bf800a33b0a64219046c5e0b89d474b862f09d2`
- Historical practical cells: `262144`
- Historical muted/VOID-candidate cells: `189439`

The audit verified exact coordinate equivalence with maximum absolute coordinate delta `0.0`. No accepted audited feature fell outside the legacy grid envelope. The rejection is therefore not caused by projection drift or grid misalignment.

## Accepted geometry conflicting with muted cells

| Dataset | Accepted features | Features intersecting muted cells | Mixed discovered/muted features |
|---|---:|---:|---:|
| Buildings | 208,324 | 3,630 | 1,775 |
| Roads | 27,675 | 1,301 | 908 |
| Creeks | 555 | 526 | 396 |
| Fox River | 1 | 1 | 1 |

Boundary touches were counted as intersections. Using muted cells as a package-suppression mask would therefore omit accepted buildings and roads and would break accepted water continuity.

## Consequences

The historical VOID result must not be used to:

- exclude buildings, roads, creeks, or Fox River geometry;
- clip accepted geometry to historical cell boundaries;
- omit flat-container chunks because a historical cell is muted;
- define package coverage or geographic truth;
- expose sectors, inspection cells, practical cells, or VOID state in the Kane Condo interface;
- key classifications or project-building identity to the historical grid.

Later spatial chunking remains an internal implementation detail and must not inherit County Field Map cell boundaries. Batch 031 classification snapshots remain keyed by Kane Condo project-building identity.

No routine VOID re-audit is required because the mask has no approved operational use. Reconsidering that decision would require a new explicitly authorized batch with new evidence.

## Status

**Accepted Batch 026 decision: reject the historical VOID mask.**
