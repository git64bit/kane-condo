#!/usr/bin/env bash
set -euo pipefail

RENDER_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$RENDER_DIR/tools/kane_road_lod.py" "$@"
