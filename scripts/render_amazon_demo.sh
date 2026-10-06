#!/usr/bin/env bash
# Remux the Amazon demo: live local captures + VO, then ffmpeg.
# VO dir and output path are env vars so a later Cartesia swap is
# re-time + re-render, not a remux of locked audio.
#
#   VO=docs/demo/vo/edge OUT=docs/demo/care-ladder-amazon-demo.mp4 \
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
export VO="${VO:-$ROOT/docs/demo/vo/edge}"
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
    ("b02", ["b02.wav"], ["b02_missed.png", "b02_battery.png", "b02_call.png", "b02_camera.png"]),
    ("b03", ["b03.wav"], ["b03_title.png", "b03_title_in.png"]),
    ("b04", ["b04.wav"], ["b04_ladder.png"]),
    ("b05", ["b05.wav"], ["b05_cue.png"]),
    ("b06", ["b06.wav"], ["b06_notify.png", "b06_apl.png"]),
    ("b07", ["b07a.wav", "b07b.wav"], ["b07_defer.png"]),
    ("b08", ["b08a.wav", "b08b.wav", "b08c.wav"], ["b08_split.png"]),
    ("b09", ["b09.wav"], ["b09_tryelse.png"]),
    ("b10", ["b10a.wav", "b10b.wav"], ["b10_neighbor.png"]),
    ("b11", ["b11a.wav", "b11b.wav"], ["b11_going.png", "b11_okay.png", "b11_status.png"]),
    ("b12", ["b12.wav"], ["b12_routine.png", "b12_roster.png"]),
    ("b13", ["b13.wav"], ["b13_firetv.png"]),
    ("b14", ["b14.wav"], ["b14_arch.png", "b14_pytest.png"]),
    ("b15", ["b15.wav"], ["b15_close.png"]),
]

# Music source is loudnormed ~-24 LUFS. Linear gains duck it ~22 dB
# under speech, out on the mom open, back on the resolution.
MUSIC_GAIN = {
    "b01": 0.0,
    "b02": 0.22,
    "b03": 0.22,
    "b04": 0.22,
    "b05": 0.22,
    "b06": 0.22,
    "b07": 0.22,
    "b08": 0.20,
    "b09": 0.22,
    "b10": 0.22,
    "b11": 0.34,
    "b12": 0.34,
    "b13": 0.32,
    "b14": 0.30,
    "b15": 0.32,
}
BEAT_XFADE = 0.36
# Solid hold after each beat, longer than the xfade so leftover text
# cannot sit in the overlap window.
BEAT_CLEAR = 0.62
ROOM_MIX = 0.18
# Extra room-tone hold so routine / architecture stills linger (headroom to 2:45-2:55).
HOLD_EXTRA = {"b12": 3.6, "b14": 4.0, "b03": 0.4}
KEN_BURNS = {"b03", "b08"}


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


def concat_audio(wavs: list[Path], dest: Path, beat: str, room: Path) -> None:
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
            g = gap(f"{beat}-{i}", 0.28, 0.40)
            inputs += ["-stream_loop", "-1", "-t", f"{g:.3f}", "-i", str(room)]
            filt.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[g{i}]"
            )
            labels.append(f"[g{i}]")
            idx += 1
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    ff(*inputs, "-filter_complex", ";".join(filt), "-map", "[out]", str(dest))


def load_sent_durs(path: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        clip, dur_s = parts[0], parts[2]
        out.setdefault(clip, []).append(float(dur_s))
    return out


def encode_still(png: Path, dest: Path, slen: float, kenburns: bool) -> None:
    if kenburns and slen >= 0.8:
        n = max(8, int(round(slen * 15)))
        vf = (
            f"scale=1536:864,"
            f"zoompan=z='min(1.0+0.10*on/{n},1.10)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s=1280x720:fps=15"
        )
        ff(
            "-loop", "1", "-i", str(png),
            "-vf", vf,
            "-frames:v", str(n),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", "-r", "15", "-an",
            str(dest),
        )
        return
    ff(
        "-loop", "1", "-i", str(png),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-crf", "18", "-b:v", "1200k",
        "-t", f"{slen:.3f}", "-r", "15", "-s", "1280x720",
        "-an",
        str(dest),
    )


def xfade_video(clips: list[Path], durs: list[float], dest: Path, fade: float) -> None:
    if len(clips) == 1:
        ff("-i", str(clips[0]), "-c", "copy", str(dest))
        return
    fade = min(fade, min(durs) - 0.05) if durs else fade
    fade = max(0.12, fade)
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    vprev = "[0:v]"
    filt = []
    acc = durs[0]
    for i in range(1, len(clips)):
        offset = max(0.05, acc - fade)
        vout = f"[vx{i}]"
        filt.append(
            f"{vprev}[{i}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}{vout}"
        )
        vprev = vout
        acc = acc + durs[i] - fade
    ff(
        *inputs,
        "-filter_complex", ";".join(filt),
        "-map", vprev,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-an", "-r", "15", "-s", "1280x720",
        str(dest),
    )


def still_lens(beat: str, d: float, n: int, sent: dict[str, list[float]]) -> list[float]:
    if n <= 1:
        return [d]
    if beat == "b03" and n == 2:
        fade = 0.85
        total = d + fade
        a = max(0.9, total * 0.38)
        return [a, max(0.9, total - a)]
    if beat == "b02" and n >= 4 and "b02" in sent and sent["b02"]:
        # missed camera, dead phone, Neighbor ringing, camera off
        sents = sent["b02"]
        raw = sum(sents) or 1.0
        scale = d / raw
        if len(sents) >= 4:
            lens = [max(0.35, sents[i] * scale) for i in range(4)]
            drift = d - sum(lens)
            lens[-1] = max(0.35, lens[-1] + drift)
            return lens[:n]
        missed = max(0.45, sents[0] * scale)
        mid = (sents[1] * scale) if len(sents) > 1 else max(0.8, (d - missed) * 0.55)
        batt = max(0.40, mid * 0.52)
        call = max(0.35, mid - batt)
        cam = max(0.40, d - missed - batt - call)
        return [missed, batt, call, cam][:n]
    share = d / n
    lens = [share] * (n - 1)
    lens.append(max(0.2, d - share * (n - 1)))
    return lens


def probe_dur(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ],
        text=True,
    )
    return float(out.strip())


def mix_beat(vis: Path, voice: Path, dest: Path, mg: float, music: Path, room: Path) -> None:
    """Always map VO + room. Never let the still's silent track win."""
    cmd = [
        "-i", str(vis),
        "-i", str(voice),
        "-stream_loop", "-1", "-i", str(room),
    ]
    if music.is_file() and mg > 0:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filt = (
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[v];"
            f"[2:a]volume={ROOM_MIX:.3f},aformat=sample_fmts=fltp[r];"
            f"[3:a]volume={mg:.3f},aformat=sample_fmts=fltp[m];"
            f"[v][r][m]amix=inputs=3:duration=first:dropout_transition=0:normalize=0[a]"
        )
    else:
        filt = (
            f"[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[v];"
            f"[2:a]volume={ROOM_MIX:.3f},aformat=sample_fmts=fltp[r];"
            f"[v][r]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
        )
    ff(
        *cmd,
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-r", "15", "-s", "1280x720",
        str(dest),
    )


def xfade_concat(clips: list[Path], durs: list[float], dest: Path, fade: float) -> None:
    if len(clips) == 1:
        ff("-i", str(clips[0]), "-c", "copy", str(dest))
        return
    fade = min(fade, min(durs) - 0.05) if durs else fade
    fade = max(0.12, fade)
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    vprev = "[0:v]"
    aprev = "[0:a]"
    filt = []
    acc = durs[0]
    for i in range(1, len(clips)):
        offset = max(0.05, acc - fade)
        vout = f"[vx{i}]"
        aout = f"[ax{i}]"
        filt.append(
            f"{vprev}[{i}:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}{vout}"
        )
        filt.append(
            f"{aprev}[{i}:a]acrossfade=d={fade:.3f}:c1=tri:c2=tri{aout}"
        )
        vprev, aprev = vout, aout
        acc = acc + durs[i] - fade
    filt_s = ";".join(filt)
    ff(
        *inputs,
        "-filter_complex", filt_s,
        "-map", vprev, "-map", aprev,
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "15", "-s", "1280x720",
        str(dest),
    )


music = vo / "music.wav"
room = vo / "roomtone.wav"
if not room.is_file():
    raise SystemExit(f"missing room tone {room}")
sent_durs = load_sent_durs(vo / "timings.tsv")
clips = []
clip_durs = []
still_for_sheet = []
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
    concat_audio(wavs, beat_wav, beat, room)
    extra = HOLD_EXTRA.get(beat, 0.0)
    if extra > 0.05:
        held = work / f"{beat}_hold.wav"
        ff(
            "-i", str(beat_wav),
            "-stream_loop", "-1", "-i", str(room),
            "-filter_complex",
            (
                f"[0]apad=pad_dur={extra:.3f}[v];"
                f"[1]volume={ROOM_MIX:.3f}[r];"
                "[v][r]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            ),
            "-map", "[a]",
            str(held),
        )
        beat_wav = held
    d = dur(beat_wav)
    # Solid hold, then crossfade. Never a black tpad and never a cloned last card.
    tail = BEAT_CLEAR if i < len(BEATS) - 1 else 0.0
    if tail > 0.05:
        pad = work / f"{beat}_pad.wav"
        ff(
            "-i", str(beat_wav),
            "-stream_loop", "-1", "-i", str(room),
            "-filter_complex",
            (
                f"[0]apad=pad_dur={tail:.3f}[v];"
                f"[1]volume={ROOM_MIX:.3f}[r];"
                "[v][r]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            ),
            "-map", "[a]",
            str(pad),
        )
        beat_wav = pad
        d = dur(beat_wav)
    png_paths = [frames / n for n in pngs]
    lens = still_lens(beat, d - tail, len(png_paths), sent_durs)
    parts = []
    offset = 0.0
    for j, png in enumerate(png_paths):
        slen = lens[j] if j < len(lens) else max(0.2, (d - tail) - offset)
        still = work / f"{beat}_{j}.mp4"
        encode_still(png, still, slen, beat in KEN_BURNS)
        parts.append(still)
        offset += slen
    vis = work / f"{beat}_vis.mp4"
    if len(parts) == 1:
        ff("-i", str(parts[0]), "-c", "copy", str(vis))
    elif beat == "b03":
        xfade_video(parts, lens[: len(parts)], vis, 0.85)
    else:
        lst = work / f"{beat}_vis.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(vis))
    # Solid tail (not a cloned last frame) so the next card fades up on empty bg.
    if tail > 0.05:
        cleared = work / f"{beat}_vis_clear.mp4"
        ff(
            "-i", str(vis),
            "-vf", f"tpad=stop_mode=add:stop_duration={tail:.3f}:color=0x1E1C18",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-crf", "18", "-an", "-r", "15", "-s", "1280x720",
            str(cleared),
        )
        vis = cleared
    mixed = work / f"{beat}_mix.mp4"
    mix_beat(vis, beat_wav, mixed, MUSIC_GAIN[beat], music, room)
    clips.append(mixed)
    clip_durs.append(probe_dur(mixed))
    print("clip", beat, f"{clip_durs[-1]:.2f}s")

speech = sum(dur(work / f"{b}.wav") for b, _, _ in BEATS)
print("speech", round(speech, 2), "xfade", BEAT_XFADE, "no atempo")
if speech > 178.5:
    print("warning: speech alone is", round(speech, 2), "s; xfade still keeps total near speech")

xfade_concat(clips, clip_durs, out, BEAT_XFADE)
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
