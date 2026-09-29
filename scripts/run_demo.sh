#!/usr/bin/env bash
# Start Care Ladder FastAPI (Alexa+ MCP + Fire TV caregiver dashboard).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/uvicorn" ]]; then
  UVICORN="$ROOT/.venv/bin/uvicorn"
elif command -v uvicorn >/dev/null 2>&1; then
  UVICORN="uvicorn"
else
  echo "error: uvicorn not found; run: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
# Opt-out only when binding loopback. Hosted/shared APIs must set CARE_LADDER_API_TOKEN.
if [[ "${HOST}" == "127.0.0.1" || "${HOST}" == "localhost" || "${HOST}" == "::1" ]]; then
  export CARE_LADDER_ALLOW_INSECURE_LOCAL="${CARE_LADDER_ALLOW_INSECURE_LOCAL:-1}"
fi

echo "Care Ladder demo API: http://${HOST}:${PORT}"
echo "  Fire TV:  http://${HOST}:${PORT}/firetv/"
echo "  MCP:      POST http://${HOST}:${PORT}/mcp  (Streamable HTTP)"
echo "  Alexa+ sim: python -m care_ladder.mcp_server.alexa_sim --url http://${HOST}:${PORT}"
echo "  POST /demo/run  {\"fixture\":\"alexa_path_a_soft_ok\"}"
echo "  GET  /incidents/{id}  — incident timeline"
echo "Reserved phones only (NPA-555-01XX); emergency fail-closed; simulated call / speaker."

exec "$UVICORN" care_ladder.api.app:app --host "$HOST" --port "$PORT"
