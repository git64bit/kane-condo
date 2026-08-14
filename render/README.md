# Kane Condo render-package benchmark

Batch 025 evaluates **container formats only** against the accepted Kane County database. It does not implement the renderer, level of detail, a browser application, the classification snapshot, the final package manifest, or visible grid/cell behavior.

The fixed benchmark compares three containers carrying identical compressed chunk payloads:

- a directory tree with one file per chunk;
- one SQLite file containing index rows and chunk payloads;
- one flat file with an embedded canonical index and byte-range payloads.

Development sensitivity is measured at 256, 512, and 2048 records per benchmark chunk. Morton ordering exists only inside the benchmark to make spatial access repeatable; it is not a user-facing grid and does not choose the final package chunking scheme.

## Measurement discipline

The benchmark first runs the established Milestone 2 database validators, then requires the exact five accepted dataset identities and complete confirmed project-building coverage. Viewport reads consume every intersecting chunk with no cap and must return exactly the same record identities from all three candidates. Building hit tests use exact polygon tests and must return the same project-building identities.

Startup is deliberately named **warm startup/index-open**. Candidates are generated immediately before timing and no operating-system cache eviction is attempted, so Batch 025 does not claim a cold-start result.

The viewport set is deterministic and data-derived: county overview, dense/medium/sparse building regimes, road-heavy, water-heavy, and editing-scale building views. Hit testing uses up to 128 deterministic buildings spanning benchmark Morton order. Its median and p95 are descriptive functional/performance probes, not a claim about a stable production latency distribution.

Classification colors are resolved from ephemeral external `building_key -> classification` mappings. Different overlays must produce different resolved colors while the base candidate artifact hashes remain unchanged.

There is **no weighted score** and the measurement stage cannot select a format automatically. Windows/Ubuntu compatibility and replacement complexity are reported as a non-scored matrix and objective file/replacement-unit counts.

## Development benchmark environment

Batch 025 is a development-time format decision. The benchmark runs on the Linux orchestrator against the real accepted Kane County database and records the workspace path, filesystem type, mount point, device major/minor identity, and warm-cache policy as descriptive measurement metadata.

Physical USB testing, Windows workstation testing, Ubuntu workstation deployment testing, and deployment rehearsal are explicitly deferred until the application is complete. Batch 025 does not require runtime hardware to accept an intermediate development decision.

Run the real-data benchmark in a disposable exact-SSOT checkout:

```bash
bash render/kane-render-benchmark.sh measure \
  /root/kane-condo-data/database/kane-condo.gpkg \
  /root/kane-condo-data/render-benchmark/batch-025
```

The command writes exactly one canonical `benchmark-report.json` plus an external `benchmark-report.json.sha256`. Standard output is only a concise path/SHA result object; it is not a second copy of the report.

The measured Batch 025 decision is recorded in `docs/RENDER_FORMAT_DECISION.md`. Generated benchmark candidates and reports remain external artifacts and are not committed to the repository.
