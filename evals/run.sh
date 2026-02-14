#!/bin/bash
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || true
export $(grep -v '^#' .env | xargs)
python3 evals/run_evals.py --request-delay-seconds 3.5 "$@"
