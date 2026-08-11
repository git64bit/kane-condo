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

Batch 014 tests default Unclassified state, explicit current classifications, append-only history, correction, undo, idempotent event keys, stale-state rejection, and classification commands.

Batch 015 tests exact donor identity enforcement, accepted-release and feature-total contracts, clean target creation, geometry and provenance transfer, deterministic project-identity seeding, zero explicit classifications, rejected donor-table exclusion, audit generation, overwrite refusal, donor immutability, and the public seed-import command.

Batch 016 tests the exact five-profile registry, strict JSON parsing, donor provenance, endpoint and service/layer identity, requested fields, geometry, exact-ID pagination, coordinated water updates, deterministic canonical hashing, malformed registries, and the public source-profile command.

Batch 017 tests read-only accepted-release loading, bounded metadata and object-ID checks, all four source-status outcomes, data-versus-schema edit timestamps, schema and geometry drift, fixed-count enforcement, inventory changes, status precedence, coordinated water reporting, database immutability, and the public source-status command.

Batch 018 tests complete external building harvests, exact object-ID paging, end-of-harvest source rechecks, deterministic canonical candidates, requested-field and stable-identity enforcement, polygon validation, tamper and symlink rejection, offline revalidation, provenance-only candidate registration, idempotence, accepted-release preservation, and the public building-candidate command.

Batch 019 tests complete external road harvests, exact object-ID paging, LineString and MultiLineString normalization, explicit null-geometry exclusion evidence, end-of-harvest source rechecks, deterministic canonical candidates, tamper and symlink rejection, provenance-only candidate registration, idempotence, accepted-road preservation, and the public road-candidate command.

Batch 020 tests coordinated Fox River and creek harvesting, complete exact-ID inventories, line/polygon geometry contracts, missing-geometry rejection, end-of-harvest source rechecks, canonical group identity, tamper and symlink rejection, all-or-nothing provenance registration, partial-group rejection, idempotence, accepted-water preservation, and the public water-candidate command.

Batch 021 tests complete county-boundary harvesting, exact single-object identity, Polygon and MultiPolygon geometry, accepted Kane County identity, deterministic gross-bounds guards, end-of-harvest metadata and inventory rechecks, canonical staged evidence, tamper and symlink rejection, stale-reference rejection, provenance-only registration, idempotence, accepted-boundary preservation, and the public boundary-candidate command.

Batch 022 tests deterministic read-only candidate comparison for buildings, roads, coordinated water, and the county boundary; exhaustive building change categories, source-inventory additions/removals, road null-geometry exclusions, registered-candidate identity, deterministic comparison hashing and output, tamper rejection, database immutability, and the public candidate-comparison command.

Batch 023 tests clear project-identity continuity, geometry redraw, exact-geometry renumbering, additions, disappearances, reappearance, classified-building preservation, split/merge/complex ambiguity isolation, deterministic plans, external candidate-database construction, artifact tamper and symlink rejection, accepted-database immutability, idempotence, and the public building-reconciliation command.

Batch 024 tests the append-only promotion-history migration, full five-source promotion preparation, release supersession/acceptance, authoritative database immutability during prepare, active-state SHA staleness rejection, exact rollback backup identity, atomic activation, successful post-promotion verification, automatic rollback after synthetic post-verification failure, manual rollback, immutable promotion events, artifact tamper/layout rejection, idempotence, and the public promotion command.
