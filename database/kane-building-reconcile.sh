#!/usr/bin/env bash

set -euo pipefail

DATABASE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

export PYTHONDONTWRITEBYTECODE=1

exec python3 "$DATABASE_DIR/tools/kane_building_reconcile.py" "$@"
