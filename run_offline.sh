#!/bin/bash
set -e

source .venv/bin/activate
USE_LLM=0 uvicorn backend.app:app --host 0.0.0.0 --port 8000
