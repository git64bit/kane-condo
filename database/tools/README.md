# Database Tools

This directory contains controlled server-side commands for Kane Condo database work.

## Current command

`kane_db.py` supports:

```text
init      Create a new GeoPackage and apply every migration
validate  Validate the GeoPackage header, core schema, integrity, and migration identity
info      Report the database and migration identity as JSON
```

Use the repository entry point:

```bash
bash database/kane-db.sh --help
```

The implementation uses Python's standard library and opens validated databases read-only. It never places production data in Git and never moves processing onto Windows or Ubuntu user workstations.

Later approved batches extend this command with administrative provenance, seed import, refresh, reconciliation, promotion, and package-generation functions.
