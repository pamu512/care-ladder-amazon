#!/usr/bin/env bash
# Remux the Amazon demo: live local captures + VO, then ffmpeg.
# VO dir and output path are env vars so a later Cartesia swap is
# re-time + re-render, not a remux of locked audio.
#
#   VO=docs/demo/vo/chatterbox OUT=docs/demo/care-ladder-amazon-demo.mp4 \
#     CARE_LADDER_ALLOW_INSECURE_LOCAL=1 ./scripts/render_amazon_demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
BASE="http://${HOST}:${PORT}"
export BASE
export CARE_LADDER_ALLOW_INSECURE_LOCAL="${CARE_LADDER_ALLOW_INSECURE_LOCAL:-1}"
export FRAMES="${FRAMES:-$ROOT/docs/demo/frames}"
export VO="${VO:-$ROOT/docs/demo/vo/chatterbox}"
OUT="${OUT:-$ROOT/docs/demo/care-ladder-amazon-demo.mp4}"
CONTACT="${CONTACT:-$ROOT/docs/demo/care-ladder-amazon-demo-contact-sheet.png}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  UVICORN="$ROOT/.venv/bin/uvicorn"
else
  PY="python3"
  UVICORN="uvicorn"
fi
export PY ROOT

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

echo "story from live API + family FSM"
"$PY" "$ROOT/scripts/amazon_demo_story.py"

CAPTURE_DIR="${CAPTURE_DIR:-/tmp/care-ladder-demo-capture}"
mkdir -p "$CAPTURE_DIR"
if [[ ! -d "$CAPTURE_DIR/node_modules/puppeteer-core" ]]; then
  (cd "$CAPTURE_DIR" && npm install --silent --no-fund --no-audit puppeteer-core@24)
fi
cp "$ROOT/scripts/capture_amazon_demo_frames.mjs" "$CAPTURE_DIR/capture_amazon_demo_frames.mjs"
(cd "$CAPTURE_DIR" && node ./capture_amazon_demo_frames.mjs)

"$PY" "$ROOT/scripts/check_amazon_demo_copy.py" "$FRAMES/story.json"

"$PY" - "$FRAMES" "$VO" "$OUT" "$CONTACT" <<'PY'
import hashlib
import subprocess
import sys
import wave
from pathlib import Path

frames, vo, out, contact = map(Path, sys.argv[1:])
work = frames / "_work"
work.mkdir(parents=True, exist_ok=True)

BEATS = [
    ("b01", ["b01.wav"], ["b01_map.png"]),
    ("b02", ["b02.wav"], ["b02_battery.png", "b02_call.png"]),
    ("b03", ["b03.wav"], ["b03_title.png"]),
    ("b04", ["b04.wav"], ["b04_ladder.png"]),
    ("b05", ["b05.wav"], ["b05_cue.png"]),
    ("b06", ["b06.wav"], ["b06_notify.png", "b06_apl.png"]),
    ("b07", ["b07a.wav", "b07b.wav"], ["b07_defer.png"]),
    ("b08", ["b08a.wav", "b08b.wav", "b08c.wav"], ["b08_split.png"]),
    ("b09", ["b09.wav"], ["b09_silent.png"]),
    ("b10", ["b10a.wav", "b10b.wav"], ["b10_neighbor.png"]),
    ("b11", ["b11a.wav", "b11b.wav"], ["b11_going.png", "b11_okay.png", "b11_status.png"]),
    ("b12", ["b12.wav"], ["b12_routine.png", "b12_roster.png"]),
    ("b13", ["b13.wav"], ["b13_firetv.png"]),
    ("b14", ["b14.wav"], ["b14_arch.png", "b14_pytest.png"]),
    ("b15", ["b15.wav"], ["b15_close.png"]),
]

# Music: silent on the mum open; ducked mid-tape; back for resolution.
MUSIC_GAIN = {
    "b01": 0.0,
    "b02": 0.07,
    "b03": 0.08,
    "b04": 0.08,
    "b05": 0.07,
    "b06": 0.08,
    "b07": 0.07,
    "b08": 0.07,
    "b09": 0.06,
    "b10": 0.07,
    "b11": 0.10,
    "b12": 0.10,
    "b13": 0.09,
    "b14": 0.08,
    "b15": 0.09,
}


def dur(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def gap(key: str, lo: float, hi: float) -> float:
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return lo + (h % 1000) / 1000.0 * (hi - lo)


def ff(*args):
    subprocess.check_call(
        ["ffmpeg", "-y", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def concat_audio(wavs: list[Path], dest: Path, beat: str) -> None:
    if len(wavs) == 1:
        ff("-i", str(wavs[0]), "-c", "copy", str(dest))
        return
    inputs = []
    labels = []
    filt = []
    idx = 0
    n_lab = 0
    for i, w in enumerate(wavs):
        inputs += ["-i", str(w)]
        filt.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[a{n_lab}]")
        labels.append(f"[a{n_lab}]")
        idx += 1
        n_lab += 1
        if i < len(wavs) - 1:
            g = gap(f"{beat}-{i}", 0.30, 0.50)
            if beat in {"b01", "b11"}:
                g = gap(f"{beat}-{i}", 0.80, 1.15)
            inputs += ["-f", "lavfi", "-t", f"{g:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
            filt.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono,volume=0[g{i}]"
            )
            labels.append(f"[g{i}]")
            idx += 1
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    ff(*inputs, "-filter_complex", ";".join(filt), "-map", "[out]", str(dest))


music = vo / "music.wav"
clips = []
still_for_sheet = []
total = 0.0
inter = []
for i, (beat, wav_names, pngs) in enumerate(BEATS):
    wavs = [vo / n for n in wav_names]
    for w in wavs:
        if not w.is_file():
            raise SystemExit(f"missing VO {w}")
    png_paths = []
    for n in pngs:
        p = frames / n
        if not p.is_file():
            raise SystemExit(f"missing frame {p}")
        png_paths.append(p)
    still_for_sheet.append(png_paths[0])
    beat_wav = work / f"{beat}.wav"
    concat_audio(wavs, beat_wav, beat)
    d = dur(beat_wav)
    if i == 0:
        g = 0.0
    elif beat == "b02":
        g = gap("after-b01", 0.85, 1.15)
    else:
        g = gap(f"after-{BEATS[i-1][0]}", 0.28, 0.62)
    inter.append(g)
    total += d + g

# Fit under 180s: first shrink gaps, then a light atempo if speech is long.
speech = sum(dur(work / f"{b}.wav") for b, _, _ in BEATS)
if speech + sum(inter) > 176.5:
    scale = max(0.12, (176.5 - speech) / max(sum(inter), 0.01))
    if scale < 1:
        inter = [g * min(1.0, scale) for g in inter]
        print("scaled inter-beat gaps by", round(min(1.0, scale), 3))
if speech + sum(inter) > 176.5:
    rate = min(1.12, (speech + sum(inter)) / 174.0)
    print("atempo", round(rate, 3), "to fit 3:00")
    for beat, _, _ in BEATS:
        src = work / f"{beat}.wav"
        tmp = work / f"{beat}_fit.wav"
        ff("-i", str(src), "-af", f"atempo={rate:.4f}", str(tmp))
        tmp.replace(src)

for i, (beat, _w, pngs) in enumerate(BEATS):
    beat_wav = work / f"{beat}.wav"
    d = dur(beat_wav)
    png_paths = [frames / n for n in pngs]
    share = d / len(png_paths)
    parts = []
    offset = 0.0
    for j, png in enumerate(png_paths):
        slen = share if j < len(png_paths) - 1 else max(0.2, d - offset)
        still = work / f"{beat}_{j}.mp4"
        ff(
            "-loop", "1", "-i", str(png),
            "-f", "lavfi", "-t", f"{slen:.3f}", "-i", "anullsrc=r=44100:cl=mono",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-crf", "18", "-b:v", "1200k",
            "-c:a", "aac", "-b:a", "96k",
            "-t", f"{slen:.3f}", "-r", "15", "-s", "1280x720",
            str(still),
        )
        parts.append(still)
        offset += slen
    vis = work / f"{beat}_vis.mp4"
    if len(parts) == 1:
        parts[0].replace(vis) if False else ff("-i", str(parts[0]), "-c", "copy", str(vis))
    else:
        lst = work / f"{beat}_vis.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(vis))
    g = inter[i]
    if g > 0.05:
        pad = work / f"{beat}_pad.wav"
        ff(
            "-i", str(beat_wav),
            "-af", f"adelay={int(g*1000)}|{int(g*1000)},apad=pad_dur=0.02",
            str(pad),
        )
        beat_wav = pad
        ff(
            "-i", str(vis),
            "-vf", f"tpad=start_duration={g:.3f}:color=0x1E1C18",
            "-an",
            str(work / f"{beat}_vpad.mp4"),
        )
        vis = work / f"{beat}_vpad.mp4"
    mixed = work / f"{beat}_mix.mp4"
    mg = MUSIC_GAIN[beat]
    if music.is_file() and mg > 0:
        ff(
            "-i", str(vis),
            "-i", str(beat_wav),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex",
            (
                f"[2:a]volume={mg:.3f}[m];"
                f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            ),
            "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-r", "15", "-s", "1280x720",
            str(mixed),
        )
    else:
        ff(
            "-i", str(vis),
            "-i", str(beat_wav),
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-r", "15", "-s", "1280x720",
            str(mixed),
        )
    clips.append(mixed)
    print("clip", beat, f"{dur(beat_wav):.2f}s")

lst = work / "concat.txt"
lst.write_text("".join(f"file '{c}'\n" for c in clips))
ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out))
print("wrote", out)

# Contact sheet: one frame per beat (first still of each beat).
n = len(still_for_sheet)
cols = 5
rows = (n + cols - 1) // cols
inputs = []
filt_in = []
for i, png in enumerate(still_for_sheet):
    inputs += ["-i", str(png)]
    filt_in.append(f"[{i}:v]scale=256:144:force_original_aspect_ratio=decrease,pad=256:144:(ow-iw)/2:(oh-ih)/2,setsar=1[s{i}]")
# pad missing tiles
while n < cols * rows:
    inputs += ["-f", "lavfi", "-i", "color=c=0x1E1C18:s=256x144"]
    filt_in.append(f"[{n}:v]scale=256:144,setsar=1[s{n}]")
    n += 1
layout = "|".join(
    f"{(i % cols) * 256}_{(i // cols) * 144}" for i in range(cols * rows)
)
filt = ";".join(filt_in) + ";" + "".join(f"[s{i}]" for i in range(cols * rows)) + f"xstack=inputs={cols*rows}:layout={layout}[v]"
ff(*inputs, "-filter_complex", filt, "-map", "[v]", "-frames:v", "1", str(contact))
print("wrote", contact)
PY

ffprobe -hide_banner "$OUT"
ls -lh "$OUT" "$CONTACT"
echo "regenerate: VO=$VO OUT=$OUT CARE_LADDER_ALLOW_INSECURE_LOCAL=1 ./scripts/render_amazon_demo.sh"
