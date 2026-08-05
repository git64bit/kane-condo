# Database Tests

Database tests use Python's standard `unittest` runner.

Run them from the repository root:

```bash
bash database/run-tests.sh
```

Tests are deterministic and use temporary databases or small synthetic fixtures. They do not require production county data, private credentials, network access, or write access to an accepted database.

Batch 008 tests the GeoPackage 1.4.0 header, required metadata, migration identity, overwrite refusal, and public database command.

Batch 009 tests administrative provenance, preserved source-file identities, release lineage, one accepted release per dataset, and provenance commands.

Batch 010 tests county-boundary GeoPackage registration, Polygon and MultiPolygon storage, holes, exact bounds and hashes, source-file association, malformed input rejection, tamper detection, and boundary commands.

Batch 011 tests immutable road and water GeoPackage registration, line and polygon geometry, source order, atomic multi-release import, exact source evidence, tamper detection, bounds, and public map-layer commands.

Batch 012 tests immutable official building-release storage, Polygon and MultiPolygon geometry, holes, declared source identity, exact source evidence, source order, hashes, bounds, tamper detection, and public building commands.

Batch 013 tests deterministic project-owned building identities, one-to-one initial mappings, source-release independence, future split/merge mapping capacity, tamper detection, coverage validation, and public identity commands.
