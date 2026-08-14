# Classification snapshot payload

Batch 031 defines a compact deterministic offline classification snapshot for the current Kane Condo building geometry. The generated snapshot is derived data and remains outside Git.

## Identity contract

Every snapshot record is keyed only by Kane Condo `building_key`. County building identifiers and internal numeric `project_building_id` values are not emitted.

Generation reads the accepted building release and requires every accepted footprint to have exactly one confirmed mapping to an active project building, matching the Batch 030 building-LOD identity contract. The snapshot records:

- accepted building-release key and content SHA-256;
- current render-building count; and
- `render_identity_sha256`, the SHA-256 of canonical JSON for the lexicographically sorted list of current render `building_key` values.

This fingerprint lets later package validation reject a classification snapshot built for a different building-identity state without inspecting geometry.

## Classification state

The four Kane Condo states remain:

- `unclassified`;
- `other`;
- `condominium`;
- `apartments`.

`unclassified` is the default and is never stored as an explicit snapshot record. The `records` array contains only current explicit classifications as compact two-item arrays:

`[building_key, classification]`

Records are sorted by `building_key`. The snapshot also records per-class counts and a SHA-256 over the canonical explicit-record array.

Explicit classifications belonging to project identities that are not represented by the current accepted building release are not copied into the render snapshot. They remain authoritative in the GeoPackage and are counted as `non_rendered_explicit_count`; they are not deleted or changed.

## File

The conventional generated file is `classification-snapshot.json`. It is canonical UTF-8 JSON with no timestamp, machine-specific path, geometry, or checksum sidecar. Rebuilding from the same authoritative state produces identical bytes.

Replacing this small file can change offline classification rendering without regenerating `buildings-lod.krf`.

## Explicit exclusions

Batch 031 does not include geometry, colors, filters, hit testing, renderer behavior, server APIs, package manifests, roads, water, browser code, or deployment behavior. It does not use County Field Map sectors, cells, grids, or the rejected VOID mask.
