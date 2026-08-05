#!/usr/bin/env bash
set -euo pipefail

DATABASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

export PYTHONDONTWRITEBYTECODE=1

python3 -m unittest discover \
  -s "$DATABASE_DIR/tests" \
  -p 'test_*.py' \
  -v
