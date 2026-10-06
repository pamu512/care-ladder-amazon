#!/usr/bin/env bash
# Edge-tts VO for the 15-beat Amazon remux. US English Neural voices only.
#
#   ./scripts/generate_amazon_demo_vo_edge.sh
#   LINE=b03 ./scripts/generate_amazon_demo_vo_edge.sh
#   FORCE=1 ./scripts/generate_amazon_demo_vo_edge.sh
#
# Final wavs land in docs/demo/vo/edge/.
# Narrator: en-US-BrianMultilingualNeural  rate -5%
# Alexa:    en-US-AvaNeural
# Neighbor: en-US-EmmaMultilingualNeural
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VO="${VO:-$ROOT/docs/demo/vo/edge}"
export LINES="${LINES:-$ROOT/docs/demo/vo_lines.tsv}"
export ANOOP="${ANOOP:-$ROOT/docs/demo/vo/anoop}"
export FORCE="${FORCE:-0}"
export LINE="${LINE:-}"

if [[ -x /tmp/chatterbox-venv/bin/python ]] && /tmp/chatterbox-venv/bin/python -c "import edge_tts" 2>/dev/null; then
  PY="/tmp/chatterbox-venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]] && "$ROOT/.venv/bin/python" -c "import edge_tts" 2>/dev/null; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

mkdir -p "$VO"
"$PY" "$ROOT/scripts/edge_vo.py" --selfcheck
exec "$PY" "$ROOT/scripts/edge_vo.py"
