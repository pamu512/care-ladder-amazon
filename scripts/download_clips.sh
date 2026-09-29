#!/usr/bin/env bash
# Download demo/eval clips (real fall footage + pedestrian negative control).
# Sizes ~40 MB total. See clips/README.md for attribution and licenses.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIPS="$ROOT/clips"
mkdir -p "$CLIPS"

fetch() {
  local name="$1" url="$2" min_bytes="$3"
  if [[ -s "$CLIPS/$name" && $(wc -c < "$CLIPS/$name") -gt $min_bytes ]]; then
    echo "already present: $name"
    return
  fi
  echo "downloading: $name"
  curl -sL --max-time 300 "$url" -o "$CLIPS/$name"
  local size=$(wc -c < "$CLIPS/$name")
  if (( size <= min_bytes )); then
    echo "error: $name too small ($size bytes)" >&2
    rm -f "$CLIPS/$name"
    exit 1
  fi
}

# KU Leuven Advise fall-simulation dataset (research use, attributed in clips/README.md)
fetch kul_fall_1.avi "https://iiw.kuleuven.be/onderzoek/advise/datasets/fall-1" 1000000
fetch kul_fall_2.avi "https://iiw.kuleuven.be/onderzoek/advise/datasets/fall-2" 1000000
# OpenCV sample (Apache-2.0) — pedestrians, negative control
fetch vtest.avi "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi" 1000000

echo "clips ready in $CLIPS"
