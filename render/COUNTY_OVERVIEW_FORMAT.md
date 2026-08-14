# County overview payload

Batch 027 defines a small deterministic overview payload for the accepted Kane County boundary.
It is generated from the authoritative GeoPackage and remains a derived artifact.

## File

The generator writes one canonical UTF-8 JSON file, conventionally `county-overview.json`.
No timestamp or machine-specific value is embedded, so the same accepted database produces the same bytes.
The generator replaces the requested output path directly; it does not create archives or checksum sidecars.

The payload contains:

- format key `kane-condo-county-overview` and version `1`;
- EPSG:4326 county identity and accepted boundary-release identity;
- exact accepted boundary bounds and center for immediate full-county viewport fitting;
- simplified exterior boundary rings for overview drawing;
- source and output vertex counts plus the deterministic simplification tolerance.

Interior polygon rings are intentionally omitted because this payload is an overview outline, not an authoritative replacement for the source geometry. Exact bounds always come from the accepted source geometry, not from the simplified outline.

## Simplification

Each exterior ring is simplified deterministically with Ramer-Douglas-Peucker. The tolerance is the larger county extent dimension divided by `2048`. Closed rings remain closed and retain at least three distinct vertices.

This tolerance is a Batch 027 overview rule only. It does not define road, water, or building level-of-detail thresholds.

## Boundaries

This payload does **not** define the final render-package manifest or flat-container framing. Later Milestone 3 batches may embed the canonical overview payload into the selected flat container without changing its geographic meaning.

County Field Map sectors, cells, grids, and the rejected VOID mask are not inputs and must not appear in the output.
