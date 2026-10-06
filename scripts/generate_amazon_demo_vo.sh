#!/usr/bin/env bash
# Cartesia Sonic TTS for the Amazon remux. Spoken tokens only.
# Voices: narrator Ricardo, Alexa Camille, neighbor Connie.
# TTS expansions only: "Alexa Plus", "M C P". Refuse to invent audio
# without CARTESIA_API_KEY. Skip when wavs already exist.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${VO:-$ROOT/docs/demo/vo}"
LINES="${LINES:-$ROOT/docs/demo/vo_lines.tsv}"
mkdir -p "$OUT"

if [[ ! -f "$LINES" ]]; then
  echo "error: missing $LINES" >&2
  exit 1
fi

need=()
while IFS=$'\t' read -r clip speaker text; do
  [[ -z "${clip:-}" || "$clip" == \#* ]] && continue
  [[ -f "$OUT/${clip}.wav" ]] || need+=("${clip}.wav")
done < "$LINES"

if [[ -z "${CARTESIA_API_KEY:-}" ]]; then
  if [[ ${#need[@]} -eq 0 && "${FORCE:-}" != "1" ]]; then
    echo "CARTESIA_API_KEY unset; using existing VO wavs in $OUT"
    echo "VO wavs in $OUT"
    exit 0
  fi
  echo "BLOCKER: CARTESIA_API_KEY missing. Refusing to invent VO audio." >&2
  echo "Place beat wavs from $LINES in $OUT, or set the key and rerun." >&2
  exit 2
fi

NARRATOR="${CARTESIA_NARRATOR:-8499aae3-022c-4d55-8283-0c2e8adbefb4}"
ALEXA="${CARTESIA_ALEXA:-55deba52-bc73-4481-ab69-9c8831c8a7c3}"
NEIGHBOR="${CARTESIA_NEIGHBOR:-8d8ce8c9-44a4-46c4-b10f-9a927b99a853}"
MODEL="${CARTESIA_MODEL:-sonic-3.6}"
VERSION="${CARTESIA_VERSION:-2026-08-14}"

voice_for() {
  case "$1" in
    A) echo "$ALEXA" ;;
    G) echo "$NEIGHBOR" ;;
    *) echo "$NARRATOR" ;;
  esac
}

while IFS=$'\t' read -r clip speaker text; do
  [[ -z "${clip:-}" || "$clip" == \#* ]] && continue
  dest="$OUT/${clip}.wav"
  if [[ -f "$dest" && "${FORCE:-}" != "1" ]]; then
    echo "skip existing $dest"
    continue
  fi
  voice="$(voice_for "$speaker")"
  echo "tts $clip ($speaker)"
  tmp="$(mktemp)"
  code="$(curl -sS -o "$tmp" -w '%{http_code}' \
    -X POST 'https://api.cartesia.ai/tts/bytes' \
    -H "Authorization: Bearer ${CARTESIA_API_KEY}" \
    -H "Cartesia-Version: ${VERSION}" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({
      "model_id": sys.argv[1],
      "transcript": sys.argv[2],
      "voice": {"id": sys.argv[3]},
      "language": "en",
      "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100},
    }))' "$MODEL" "$text" "$voice")")"
  if [[ "$code" != "200" ]]; then
    echo "Cartesia TTS failed $clip HTTP $code" >&2
    head -c 400 "$tmp" >&2 || true
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$dest"
done < "$LINES"

echo "VO wavs in $OUT"
