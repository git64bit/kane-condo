# Seed Contracts

This directory contains small, versioned identity contracts for approved external seed databases.

`kane-offline-map-0911eeef.json` identifies the accepted donor GeoPackage produced from donor commit `0911eeefeafbb18c58af0618200ba9edead29bdc`. It records the exact donor byte length, SHA-256, accepted source-release identities, and expected canonical feature totals.

The donor GeoPackage itself remains outside Git and is always opened read-only. A seed contract is evidence and validation configuration; it is not county data.
