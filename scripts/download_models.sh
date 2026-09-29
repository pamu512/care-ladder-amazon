#!/usr/bin/env bash
# Download the OpenCV Zoo MediaPipe person-detection ONNX (12 MB, Apache-2.0).
# The file is NOT committed (see .gitignore); CI/judges run this once.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS=(
  "person_detection_mediapipe_2023mar.onnx|https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/person_detection_mediapipe/person_detection_mediapipe_2023mar.onnx"
  "pose_estimation_mediapipe_2023mar.onnx|https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/pose_estimation_mediapipe/pose_estimation_mediapipe_2023mar.onnx"
)

mkdir -p "$ROOT/models"
for entry in "${MODELS[@]}"; do
  NAME="${entry%%|*}"; URL="${entry#*|}"
  MODEL="$ROOT/models/$NAME"
  if [[ -s "$MODEL" ]]; then
    echo "already present: $NAME ($(du -h "$MODEL" | cut -f1))"
    continue
  fi
  curl -sL "$URL" -o "$MODEL"
  SIZE=$(wc -c < "$MODEL")
  if (( SIZE < 1000000 )); then
    echo "error: $NAME too small ($SIZE bytes) — LFS pointer?" >&2
    rm -f "$MODEL"
    exit 1
  fi
  echo "downloaded: $NAME ($(du -h "$MODEL" | cut -f1))"
done
