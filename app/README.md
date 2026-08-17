# Kane Condo local browser application

Batch 034 establishes only the local read-only application shell and package-open boundary.
It does not render the county map, decode LOD chunks, hit-test buildings, edit classifications,
or contact the future private Kane Condo API.

## Local-origin contract

Run the application against one externally generated Milestone 3 render package:

```bash
bash app/kane-local.sh /path/to/render-package
```

The server binds to `127.0.0.1:8765` by default and serves:

- the versioned browser shell at `/`;
- a generated local configuration at `/config.json`;
- the selected external package under `/package/`.

An alternate loopback port may be selected with `--port`. Non-loopback bind addresses are rejected.
The package remains external generated data and is not copied into Git.

## Batch 034 startup behavior

The browser loads `/config.json`, then `render-package-manifest.json`. Before declaring the package ready it verifies:

- the local runtime configuration format/version;
- the exact Batch 032 manifest format/version and field inventory;
- the five required component roles, filenames, formats, versions, byte lengths, and SHA-256 values;
- the manifest's base-geometry, classification, and package-content self-identities;
- the byte length and SHA-256 of every required local component;
- the internal format/version of the two small JSON components.

The user interface reports precise configuration, compatibility, missing-resource, length, and hash errors.
A valid package reaches `Local package ready`; an invalid package never reaches ready state.

Component hashing intentionally reads the complete five-component package in Batch 034. Efficient byte-range LOD access and map rendering are later Milestone 4 batches and are not preimplemented here.

## Tests

```bash
bash app/run-tests.sh
```

The committed test suite uses only Python's standard library and verifies loopback-only serving, external-package routing, generated configuration, HEAD behavior, disabled directory listings, and path isolation.
Browser package-validation acceptance is exercised against a generated disposable package; production county data is never committed.
