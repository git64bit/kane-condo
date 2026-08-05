# Database Tests

Database tests use Python's standard `unittest` runner.

Run them from the repository root:

```bash
bash database/run-tests.sh
```

Tests are deterministic and use temporary databases or small synthetic fixtures. They do not require production county data, private credentials, network access, or write access to an accepted database.

Batch 008 tests the GeoPackage 1.4.0 header, required core tables, required spatial-reference rows, SQLite integrity, foreign keys, exact migration SHA-256 identity, overwrite refusal, tamper detection, and the public database command.
