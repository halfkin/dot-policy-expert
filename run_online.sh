#!/bin/bash
set -e

source .venv/bin/activate

if [ ! -f .env ]; then
  echo ".env file not found. Copy .env.example to .env and set your keys." >&2
  exit 1
fi

set -a
source .env
set +a

uvicorn backend.app:app --host 0.0.0.0 --port 8000
