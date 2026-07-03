#!/usr/bin/env bash
# Versioned, validation-gated build. See .harness/engine/build.py.
#   bash scripts/build.sh              normal build
#   bash scripts/build.sh --strict     submission build (markers = errors)
#   bash scripts/build.sh --force      build despite validation errors
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
exec python3 .harness/engine/build.py "$@"
