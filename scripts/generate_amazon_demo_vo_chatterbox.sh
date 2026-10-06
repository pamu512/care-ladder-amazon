#!/usr/bin/env bash
# Chatterbox VO for the 15-beat Amazon remux. Cheap per-line regen.
#
#   ./scripts/generate_amazon_demo_vo_chatterbox.sh
#   LINE=b03 ./scripts/generate_amazon_demo_vo_chatterbox.sh
#   FORCE=1 TAKES=3 ./scripts/generate_amazon_demo_vo_chatterbox.sh
#
# Final wavs land in docs/demo/vo/chatterbox/. Edge-tts is reference-only.
# If docs/demo/vo/anoop/<clip>.wav exists, it overrides narrator TTS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VO="${VO:-$ROOT/docs/demo/vo/chatterbox}"
export LINES="${LINES:-$ROOT/docs/demo/vo_lines.tsv}"
export ANOOP="${ANOOP:-$ROOT/docs/demo/vo/anoop}"
export FORCE="${FORCE:-0}"
export TAKES="${TAKES:-3}"
export LINE="${LINE:-}"
export DEVICE="${DEVICE:-cpu}"

if [[ -x /tmp/chatterbox-venv/bin/python ]]; then
  PY="/tmp/chatterbox-venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]] && "$ROOT/.venv/bin/python" -c "from chatterbox.tts import ChatterboxTTS" 2>/dev/null; then
  PY="$ROOT/.venv/bin/python"
else
  echo "error: chatterbox-tts not found. pip install chatterbox-tts edge-tts" >&2
  exit 1
fi

mkdir -p "$VO"
exec "$PY" "$ROOT/scripts/chatterbox_vo.py"
