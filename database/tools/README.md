# Database Tools

This directory contains controlled server-side commands for Kane Condo database work.

## GeoPackage command

`kane_db.py` supports:

```text
init      Create a new GeoPackage and apply every migration
validate  Validate the GeoPackage header, schema, integrity, and migration identity
info      Report the database and migration identity as JSON
```

Use:

```bash
bash database/kane-db.sh --help
```

## Administrative provenance command

`kane_provenance.py` supports:

```text
record    Record one source-release descriptor and preserved source-file identities
trace     Trace one release through its dataset, agency, county, harvest, and files
validate  Validate administrative provenance
```

Use:

```bash
bash database/kane-provenance.sh --help
```

## County-boundary command

`kane_boundary.py` supports:

```text
import    Store one Polygon or MultiPolygon GeoJSON feature for an existing boundary release
info      Report the accepted or named stored boundary and its source lineage
validate  Validate boundary registration, geometry, bounds, hashes, and release association
```

Use:

```bash
bash database/kane-boundary.sh --help
```

## Roads-and-water command

`kane_map_layers.py` supports:

```text
import    Atomically store one or more RELEASE_KEY GEOJSON pairs
info      Report accepted or named stored road and water releases
validate  Validate registration, geometry, source order, hashes, bounds, and lineage
```

Use:

```bash
bash database/kane-map-layers.sh --help
```

`kane_geometry.py` provides strict EPSG:4326 line and polygon normalization and GeoPackage binary encoding/decoding for county boundary, roads, water, and later spatial migrations.

All commands use Python's standard library. They run on server-side Linux infrastructure, keep production data outside Git, and do not move processing onto Windows or Ubuntu user workstations.
