# Render-package manifest and integrity

Batch 032 defines the versioned integrity manifest for the Kane Condo offline render package. The manifest inventories the derived components created by Batches 027 through 031 and verifies that they belong to the same accepted authoritative database state.

## Components

The manifest contains exactly five component roles, in this order:

1. `county_overview` — `county-overview.json`;
2. `roads` — `roads-lod.krf`;
3. `water` — `water-lod.krf`;
4. `buildings` — `buildings-lod.krf`;
5. `classification_snapshot` — `classification-snapshot.json`.

Each component record contains its role, conventional filename, component format/version, byte length, and SHA-256. Absolute source paths are never written to the manifest.

Before a component is admitted, Batch 032 validates its format header/index and internal payload inventory. Flat-container chunks must be contiguous, zlib-decodable, canonical JSON, and match their recorded compressed/uncompressed lengths and SHA-256 hashes. The county overview and classification snapshot must satisfy their canonical JSON contracts.

## Authoritative database identity

The manifest records:

- authoritative GeoPackage byte length and SHA-256;
- Kane County identity; and
- the exactly one accepted release key, content SHA-256, and feature count for county boundary, roads, Fox River, creeks, and buildings.

Component source-release metadata must match this accepted-release inventory. A component from another database state is rejected even when the component itself is structurally valid.

## Building/classification compatibility

The building LOD `editing` level is scanned for Kane Condo `building_key` identities. Batch 032 computes the same canonical sorted-building-key SHA-256 contract used by the Batch 031 classification snapshot.

The classification snapshot is accepted only when its building count and `render_identity_sha256` match the building LOD exactly. The manifest records that compatibility identity, explicit classification count, and explicit-record SHA-256 separately from base geometry.

## Stable content identities

The manifest records three identities:

- `base_geometry_sha256`: SHA-256 of the four base-geometry component descriptors;
- `classification_snapshot_sha256`: SHA-256 of the small independently replaceable classification component;
- `package_content_sha256`: SHA-256 of authoritative database identity, all component descriptors, and classification compatibility metadata.

`package_content_sha256` deliberately excludes `created_at`. A classification-only replacement changes classification and package content identity without changing `base_geometry_sha256`.

## Creation time

`created_at` is UTC RFC3339 with whole-second precision, for example `2026-08-14T19:55:00Z`. It is the only intentionally time-varying manifest field. The command may accept an explicit creation time for deterministic tests and Batch 033 reproducibility analysis; normal generation uses current UTC.

## Validation

`kane-package-manifest.sh validate` revalidates the authoritative database and all five components, then reconstructs the expected manifest using its recorded `created_at`. Missing, altered, swapped, truncated, structurally invalid, release-incompatible, or building-identity-incompatible components are rejected before use.

## Explicit exclusions

Batch 032 does not rebuild geometry, define renderer behavior, define zoom thresholds, edit classifications, publish a package, or perform physical deployment testing. It does not use County Field Map sectors, cells, grids, or the rejected VOID mask.
