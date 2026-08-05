# Database Tests

Database tests use Python's standard `unittest` runner unless a later approved decision changes the test framework.

Run them from the repository root:

```bash
bash database/run-tests.sh
```

Tests must be deterministic and use temporary databases or small synthetic fixtures. They must not require production county data, private credentials, network access, or write access to an accepted database.
