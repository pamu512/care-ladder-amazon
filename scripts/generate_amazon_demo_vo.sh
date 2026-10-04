#!/usr/bin/env bash
# Cartesia Sonic TTS for the Amazon remux. Spoken tokens only; claims match the VO script.
# Shot 10 may say we trained on Kaggle datasets. No slug, weights path, or accuracy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${VO:-$ROOT/docs/demo/vo}"
mkdir -p "$OUT"

need=()
for n in $(seq -w 1 10); do
  [[ -f "$OUT/shot${n}.wav" ]] || need+=("shot${n}.wav")
done
if [[ -z "${CARTESIA_API_KEY:-}" ]]; then
  if [[ ${#need[@]} -eq 0 && "${FORCE:-}" != "1" ]]; then
    echo "CARTESIA_API_KEY unset; using existing VO wavs in $OUT"
    echo "VO wavs in $OUT"
    exit 0
  fi
  echo "BLOCKER: CARTESIA_API_KEY missing. Refusing to invent VO audio." >&2
  echo "Place shot01.wav through shot10.wav in $OUT, or set the key and rerun." >&2
  exit 2
fi

VOICE="${CARTESIA_VOICE:-8499aae3-022c-4d55-8283-0c2e8adbefb4}"
MODEL="${CARTESIA_MODEL:-sonic-3.6}"
VERSION="${CARTESIA_VERSION:-2026-08-14}"

# ponytail: ten fixed VO lines from docs/demo-video-script-amazon.md. TTS expansions
# (Alexa Plus, M C P, outcome requires acknowledgment) do not change the claims.
# Spoken VO never says the syllable "ack". Shots 9 to 10 stay spoken, not a spec dump.
shots=(
  "Before this update, Care Ladder already watched the room with OpenCV and climbed a careful ladder: notice, ask, then call. But it asked through a speaker stub, and the caregiver watched from a web console."
  "This is the same project, significantly updated for Alexa Plus. Alexa Plus is the primary surface. The camera still triggers everything. What changed is what happens next."
  "Fire TV is the supporting surface: a calm living-room dashboard. Silhouette only, no live video feed, and a remote-friendly layout that works with just the D-pad."
  "When OpenCV sees four minutes of stillness, Alexa Plus checks in. Soft reassurance, don't worry, is a clear OK even without the word okay. The ladder stands down. The transcript is the real line plus the intent label."
  "The same check-in does not treat every utterance as binary OK. Okay-but-hurt stays on the TV as needs a human. The ladder does not clear."
  "A human closes the loop. Caregiver notify lands on Alexa mobile. The acknowledgment is on the audit trail, not a silent read receipt. A caregiver outcome is recorded only after that acknowledgment."
  "Cover the camera and Care Ladder does not panic. Occlusion reads as privacy, not distress. It asks the resident to move the blanket, and if there is no answer it informs the primary contact on exactly that basis. No distress is ever claimed."
  "Under the hood, the Alexa Plus path runs on a self-hosted M C P server, Streamable HTTP, current spec, exposing care-flow tools. Slash mcp and writes need a bearer token. JSON polls stay open so the TV can refresh. This simulated Alexa Plus agent is an M C P client driving the real ladder. The TV is watching the same incident, not a second demo glued on."
  "Two things this system will not do. It will not claim to be medical. And it will not call emergency services on its own. Emergency stays off, and locked, in this build."
  "Same project. Alexa Plus is primary. Fire TV is supporting. The caregiver is on Alexa mobile. We trained on Kaggle datasets. This is not a medical device. Care Ladder."
)

for i in "${!shots[@]}"; do
  n="$(printf '%02d' $((i + 1)))"
  dest="$OUT/shot${n}.wav"
  if [[ -f "$dest" && "${FORCE:-}" != "1" ]]; then
    echo "skip existing $dest"
    continue
  fi
  echo "tts shot${n}"
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
    }))' "$MODEL" "${shots[$i]}" "$VOICE")")"
  if [[ "$code" != "200" ]]; then
    echo "Cartesia TTS failed shot${n} HTTP $code" >&2
    head -c 400 "$tmp" >&2 || true
    rm -f "$tmp"
    exit 1
  fi
  mv "$tmp" "$dest"
done

echo "VO wavs in $OUT"
