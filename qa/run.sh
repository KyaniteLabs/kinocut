#!/usr/bin/env bash
set -euo pipefail

QA_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${QA_RUNNER_PYTHON:-python3}" "$QA_DIR/runner.py" "$@"
