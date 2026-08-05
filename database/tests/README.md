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
