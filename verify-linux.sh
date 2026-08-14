#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

export PYTHONDONTWRITEBYTECODE=1

python3 "$ROOT_DIR/tools/verify_repository.py" "$ROOT_DIR"
bash "$ROOT_DIR/database/run-tests.sh"
bash "$ROOT_DIR/render/run-tests.sh"

printf '%s\n' 'Kane Condo verification completed successfully.'
