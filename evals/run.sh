#!/bin/bash
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || true
export $(grep -v '^#' .env | xargs)

SUITE="${1:-loomo}"

case "$SUITE" in
  loomo)
    echo "Running Loomo eval suite (58 questions)..."
    python3 evals/eval_loomo.py --request-delay-seconds 1.5 "${@:2}"
    ;;
  legacy)
    echo "Running legacy eval suite (79 questions)..."
    python3 evals/run_evals.py --request-delay-seconds 3.5 "${@:2}"
    ;;
  *)
    echo "Usage: $0 [loomo|legacy] [extra args...]"
    echo "  loomo  — Active 58-question Loomo customer-facing KB suite (default)"
    echo "  legacy — Older 79-question internal KB suite"
    exit 1
    ;;
esac
