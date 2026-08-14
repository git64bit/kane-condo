# Reproducible render-package build

Batch 033 defines the production build entry point for a complete Kane Condo offline render package. It composes the accepted Batch 027–032 generators without changing their geographic or classification contracts.

## One-command build

`kane-render-package.sh build DATABASE PACKAGE_DIRECTORY` rebuilds the complete package from the authoritative GeoPackage. The destination contains exactly:

1. `county-overview.json`;
2. `roads-lod.krf`;
3. `water-lod.krf`;
4. `buildings-lod.krf`;
5. `classification-snapshot.json`;
6. `render-package-manifest.json`.

The build does not reuse previously generated component files. County overview, roads, water, buildings, and classification state are regenerated directly from the same authoritative database, then the Batch 032 manifest is generated from those staged bytes.

## Staging, validation, and promotion

A build is first written to a temporary sibling directory. The complete staged package is validated against the authoritative database before any published package is changed. Only a fully valid staged directory is promoted.

Components are never copied one at a time into the published package. When replacing an existing package, the old complete directory is renamed to a hidden rollback path and the new complete directory is renamed into the destination. If the second rename fails, the old package is restored. Stale staging directories are discarded on the next build; an interrupted promotion is recovered from the rollback directory before new work begins.

This contract prevents a failed component generator or integrity check from exposing a mixed old/new package. Promotion changes the visible component set by directory rename, not by incremental file replacement.

## Reproducibility

All five component payloads are deterministic for an identical authoritative database state. Repeated builds therefore require byte-identical component files.

The Batch 032 manifest field `created_at` remains the only intentionally variable package metadata. `package_content_sha256` excludes that timestamp. `kane-render-package.sh compare DATABASE FIRST SECOND` validates both packages and requires:

- byte-identical county overview, road, water, building, and classification components;
- identical manifest content after removing only `created_at`; and
- identical `package_content_sha256`.

If both builds use the same explicit `--created-at`, the manifest bytes are identical as well. Different creation times are permitted only because that field was explicitly isolated by Batch 032.

## Classification independence

`classification-snapshot.json` remains a distinct component. Batch 033 does not merge classification state into building geometry. Later operational replacement can therefore update classification state without changing the base building LOD, subject to manifest/integrity validation.

## Explicit exclusions

Batch 033 does not implement renderer behavior, UI, browser code, classification editing, deployment, USB testing, or physical workstation validation. It does not modify authoritative database state and does not use County Field Map sectors, cells, grids, or the rejected VOID mask.
