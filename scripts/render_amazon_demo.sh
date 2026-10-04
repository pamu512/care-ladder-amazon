#!/usr/bin/env bash
# Remux the Amazon demo the same way the OpenCV pack shipped docs/demo/*.mp4:
# live local UI captures + VO, then ffmpeg. Does not claim a trained fall model.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
BASE="http://${HOST}:${PORT}"
export BASE
export CARE_LADDER_ALLOW_INSECURE_LOCAL="${CARE_LADDER_ALLOW_INSECURE_LOCAL:-1}"
export FRAMES="${FRAMES:-$ROOT/docs/demo/frames}"
export VO="${VO:-$ROOT/docs/demo/vo}"
OUT="${OUT:-$ROOT/docs/demo/care-ladder-amazon-demo.mp4}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  UVICORN="$ROOT/.venv/bin/uvicorn"
else
  PY="python3"
  UVICORN="uvicorn"
fi

if ! curl -sf --max-time 1 "$BASE/plan" >/dev/null; then
  echo "starting API on $BASE"
  "$UVICORN" care_ladder.api.app:app --host "$HOST" --port "$PORT" --log-level warning &
  api_pid=$!
  trap 'kill "$api_pid" 2>/dev/null || true' EXIT
  for _ in $(seq 1 50); do
    curl -sf --max-time 1 "$BASE/plan" >/dev/null && break
    sleep 0.2
  done
fi

if ! command -v node >/dev/null; then
  echo "error: node is required to capture frames" >&2
  exit 1
fi

CAPTURE_DIR="${CAPTURE_DIR:-/tmp/care-ladder-demo-capture}"
mkdir -p "$CAPTURE_DIR"
if [[ ! -d "$CAPTURE_DIR/node_modules/puppeteer-core" ]]; then
  (cd "$CAPTURE_DIR" && npm install --silent --no-fund --no-audit puppeteer-core@24)
fi

cp "$ROOT/scripts/capture_amazon_demo_frames.mjs" "$CAPTURE_DIR/capture_amazon_demo_frames.mjs"
export ROOT PY
(cd "$CAPTURE_DIR" && node ./capture_amazon_demo_frames.mjs)

# Title card (shot 2)
ffmpeg -y -f lavfi -i "color=c=0x1a1f1a:s=1280x720:d=1" \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='Care Ladder for Alexa+':fontcolor=0xf4efe4:fontsize=48:x=(w-text_w)/2:y=h/2-40,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='same project, significant in-window update':fontcolor=0xc9c2b2:fontsize=22:x=(w-text_w)/2:y=h/2+30" \
  -frames:v 1 "$FRAMES/shot02_title.png"

# Shot 8 split: Fire TV + sim log
"$PY" - "$FRAMES" <<'PY'
from pathlib import Path
import textwrap
import cv2
import numpy as np
frames = Path(__import__("sys").argv[1])
left = cv2.imread(str(frames / "shot08_firetv.png"))
if left is None:
    raise SystemExit("missing shot08_firetv.png")
h, w = 720, 1280
left = cv2.resize(left, (640, 720))
right = np.full((720, 640, 3), (18, 20, 18), np.uint8)
log = (frames / "shot08_sim.log").read_text(errors="replace")
lines = []
for raw in log.splitlines():
    lines.extend(textwrap.wrap(raw, 78) or [""])
y = 36
cv2.putText(right, "alexa_sim (MCP client)", (24, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 220, 200), 1, cv2.LINE_AA)
for line in lines[:28]:
    cv2.putText(right, line[:90], (18, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 200, 180), 1, cv2.LINE_AA)
    y += 22
    if y > 690:
        break
out = np.concatenate([left, right], axis=1)
cv2.imwrite(str(frames / "shot08_split.png"), out)
ui = cv2.imread(str(frames / "shot10_ui.png"))
tv = cv2.imread(str(frames / "shot10_firetv.png"))
if ui is None or tv is None:
    raise SystemExit("missing shot10 frames")
ui = cv2.resize(ui, (640, 720))
tv = cv2.resize(tv, (640, 720))
cv2.imwrite(str(frames / "shot10_split.png"), np.concatenate([ui, tv], axis=1))
print("wrote split frames")
PY

# Stitch stills to VO durations
"$PY" - "$FRAMES" "$VO" "$OUT" <<'PY'
import subprocess, sys
from pathlib import Path
frames, vo, out = map(Path, sys.argv[1:])
shots = [
    ("shot01_ui.png", "shot01.wav"),
    ("shot02_title.png", "shot02.wav"),
    ("shot03_allclear.png", "shot03.wav"),
    ("shot04_soft_ok.png", "shot04.wav"),
    ("shot05_needs_human.png", "shot05.wav"),
    ("shot06_acked.png", "shot06.wav"),
    ("shot07_occluded.png", "shot07.wav"),
    ("shot08_split.png", "shot08.wav"),
    ("shot09_gate.png", "shot09.wav"),
    ("shot10_split.png", "shot10.wav"),
]
work = frames / "_work"
work.mkdir(exist_ok=True)
clips = []
for i, (png, wav) in enumerate(shots, 1):
    img = frames / png
    audio = vo / wav
    if not img.is_file() or not audio.is_file():
        raise SystemExit(f"missing {img} or {audio}")
    clip = work / f"{i:02d}.mp4"
    subprocess.check_call([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(img),
        "-i", str(audio),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        "-shortest", "-r", "15", "-s", "1280x720",
        str(clip),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    clips.append(clip)
    print("clip", clip.name)
lst = work / "concat.txt"
lst.write_text("".join(f"file '{c}'\n" for c in clips))
subprocess.check_call([
    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
    "-c", "copy", str(out),
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("wrote", out)
PY

ffprobe -hide_banner "$OUT"
ls -lh "$OUT"
echo "regenerate: CARE_LADDER_ALLOW_INSECURE_LOCAL=1 ./scripts/render_amazon_demo.sh"
