#!/usr/bin/env bash
# One-story Amazon demo: uvicorn → /firetv/ → alexa_sim → TV updates.
#
# Soft OK ("don't worry") resolves the incident on the TV.
# A second sim (needs-human) stays on notify so the caregiver can Acknowledge.
#
# Usage:
#   ./scripts/amazon_demo_path.sh              # start server, print URL, run both paths
#   CHECK=1 ./scripts/amazon_demo_path.sh      # assert API only, then stop a server we started
#   PORT=8010 HOST=127.0.0.1 ./scripts/amazon_demo_path.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
BASE="http://${HOST}:${PORT}"
# Opt-out only when binding loopback. Hosted/shared APIs must set CARE_LADDER_API_TOKEN.
if [[ "${HOST}" == "127.0.0.1" || "${HOST}" == "localhost" || "${HOST}" == "::1" ]]; then
  export CARE_LADDER_ALLOW_INSECURE_LOCAL="${CARE_LADDER_ALLOW_INSECURE_LOCAL:-1}"
fi
CHECK="${CHECK:-0}"
# ponytail: single-household demo; upgrade if a second household shares the store.
HOUSEHOLD="amazon-demo-1"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  UVICORN="$ROOT/.venv/bin/uvicorn"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
  if command -v uvicorn >/dev/null 2>&1; then
    UVICORN="uvicorn"
  else
    echo "error: uvicorn not found; run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
  fi
else
  echo "error: python3 not found" >&2
  exit 1
fi

started_server=0
pid=""

cleanup() {
  if [[ "$started_server" == "1" && -n "${pid}" ]]; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
}

latest_incident() {
  "$PY" - "$BASE" "$HOUSEHOLD" <<'PY'
import json, sys, urllib.request
base, hh = sys.argv[1], sys.argv[2]
listing = json.loads(urllib.request.urlopen(base + "/incidents", timeout=5).read())
mine = [i for i in listing if i.get("household_id") == hh]
if not mine:
    raise SystemExit("no amazon-demo-1 incident yet")
iid = mine[-1]["id"]
full = json.loads(urllib.request.urlopen(base + "/incidents/" + iid, timeout=5).read())
print(json.dumps({
    "id": full["id"],
    "status": full["status"],
    "tools": [e["tool"] for e in full.get("events") or []],
    "reply": next(
        (e.get("detail", {}).get("reply_raw") for e in reversed(full.get("events") or [])
         if e.get("tool") == "alexa_checkin" and e.get("detail", {}).get("reply_raw")),
        "",
    ),
}))
PY
}

wait_for_api() {
  local i
  for i in $(seq 1 50); do
    if "$PY" - "$BASE" <<'PY'
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/plan", timeout=1)
PY
    then
      return 0
    fi
    sleep 0.2
  done
  echo "error: API did not come up at ${BASE}" >&2
  return 1
}

if ! "$PY" - "$BASE" <<'PY'
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/plan", timeout=1)
PY
then
  echo "Starting Care Ladder on ${BASE}"
  "$UVICORN" care_ladder.api.app:app --host "$HOST" --port "$PORT" --log-level warning &
  pid=$!
  started_server=1
  if [[ "$CHECK" == "1" ]]; then
    trap cleanup EXIT
  fi
  wait_for_api
else
  echo "Reusing already-running API at ${BASE}"
fi

echo
echo "Fire TV:  ${BASE}/firetv/"
echo "MCP:      POST ${BASE}/mcp"
echo
echo "Device truth: prefer a Fire TV stick (Silk) or the official simulator."
echo "Browser at 1280×720 is the fallback if a stick is not in the room."
echo "Video order: calm product first (shots 3–7), MCP proof mid-late (shot 8)."
echo "Never open the tape on a terminal wall of JSON."
echo

if [[ "$CHECK" != "1" ]]; then
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${BASE}/firetv/" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "${BASE}/firetv/" || true
  fi
  echo "Open ${BASE}/firetv/ now. The TV polls /incidents — keep it visible."
  echo
fi

echo "== Path 1 · soft OK — sim --answer \"don't worry\" → TV resolves =="
"$PY" -m care_ladder.mcp_server.alexa_sim --url "$BASE" --answer "don't worry"
soft="$(latest_incident)"
echo "TV poll: ${soft}"
"$PY" - "$soft" <<'PY'
import json, sys
row = json.loads(sys.argv[1])
assert row["status"] == "resolved", row
assert "don't worry" in (row.get("reply") or ""), row
assert "resolve" in row["tools"], row
print("ok: same incident resolved on the store Fire TV polls")
PY

echo
echo "== Path 2 · needs-human — TV stays notify → Acknowledge on the TV =="
"$PY" -m care_ladder.mcp_server.alexa_sim --url "$BASE" --answer "I'm okay but I think I'm hurt"
human="$(latest_incident)"
echo "TV poll: ${human}"
"$PY" - "$human" <<'PY'
import json, sys
row = json.loads(sys.argv[1])
assert row["status"] != "resolved", row
assert "notify_caretaker" in row["tools"], row
assert "hurt" in (row.get("reply") or "").lower(), row
print("ok: notify stays up — click Acknowledge on Fire TV to close the loop")
PY

echo
echo "Acknowledge: on /firetv/ press Acknowledge (or POST ${BASE}/incidents/<id>/ack)."
if [[ "$CHECK" != "1" && "$started_server" == "1" ]]; then
  echo "Server still running (pid ${pid}) at ${BASE} — Ctrl-C in that job or kill ${pid} when done."
  trap - EXIT
fi
