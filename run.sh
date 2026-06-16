#!/usr/bin/env bash
# Local dev launcher (no gh required). Delegates to the extension entrypoint.
# Usage: ./run.sh [ORG]
set -euo pipefail
cd "$(dirname "$0")"
exec ./gh-recon "$@"
