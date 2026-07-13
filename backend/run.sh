#!/usr/bin/env bash
# Start the EDEN backend. Reads config from backend/.env (all optional).
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn app.main:app --host "${EDEN_HOST:-0.0.0.0}" --port "${EDEN_PORT:-8000}" --reload
