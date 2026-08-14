#!/usr/bin/env bash
set -euo pipefail

RENDER_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s "$RENDER_DIR/tests" -p 'test_*.py' -v
