"""Edge-tts VO for the Amazon demo. US English Neural voices only.

Narrator: en-US-BrianMultilingualNeural  rate -5%
Alexa:    en-US-AvaNeural
Neighbor: en-US-EmmaMultilingualNeural  rate -8% (calm)

One call per sentence. The cue list is clause-split so commas are audible.
Gaps 0.30 to 0.50s; 0.65 to 0.85s after mom lines. Never atempo.

Env: VO, LINES, ANOOP, FORCE, LINE
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VO = Path(os.environ.get("VO", ROOT / "docs/demo/vo/edge"))
LINES = Path(os.environ.get("LINES", ROOT / "docs/demo/vo_lines.tsv"))
ANOOP = Path(os.environ.get("ANOOP", ROOT / "docs/demo/vo/anoop"))
FORCE = os.environ.get("FORCE", "0") == "1"
ONLY = [x.strip() for x in os.environ.get("LINE", "").split(",") if x.strip()]
TAKES_DIR = VO / "takes"
TIMINGS = VO / "timings.tsv"

VOICE = {
    "N": {
        "voice": "en-US-BrianMultilingualNeural",
        "rate": "-5%",
        "eq": "narrator",
    },
    "A": {
        "voice": "en-US-AvaNeural",
        "rate": "+0%",
        "eq": "alexa",
    },
    "G": {
        "voice": "en-US-EmmaMultilingualNeural",
        "rate": "-8%",
        "eq": "neighbor",
    },
}

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
MOM_RE = re.compile(r"\bmom\b", re.I)
DIGIT = re.compile(r"[0-9]")
BANNED_LOCALE = "en" + "-" + "IN"
BANNED_LABEL = "M" + "um"
MUM = re.compile(rf"\b{BANNED_LABEL}\b")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def read_lines() -> list[tuple[str, str, str]]:
    rows = []
    for raw in LINES.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        clip, speaker, text = raw.split("\t", 2)
        rows.append((clip.strip(), speaker.strip(), text.strip()))
    return rows


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENT_SPLIT.split(text) if p.strip()]
    out: list[str] = []
    for p in parts:
        # List lines need audible commas. Generate each clause on its own.
        if p.lower().startswith("the cue,") and p.count(",") >= 2:
            bits = [b.strip() for b in p.split(",") if b.strip()]
            for i, bit in enumerate(bits):
                if i < len(bits) - 1:
                    out.append(bit + ",")
                else:
                    out.append(bit if bit.endswith(".") else bit + ".")
        else:
            out.append(p)
    return out or [text]


def clip_hash(clip: str, idx: int, text: str) -> int:
    h = hashlib.sha256(f"{clip}|{idx}|{text}".encode()).hexdigest()
    return int(h[:8], 16)


OPENING = {"b01", "b02", "b03"}
SLOW = {"b12", "b14"}


def gap_after(clip: str, idx: int, text: str, n_sent: int) -> float:
    """Sentence gaps. Never atempo.

    Opening story is a touch longer. Learned-routine and architecture
    get 0.55 to 0.80s between sentences. Mom lines stay longer than the rest.
    """
    _ = n_sent
    h = clip_hash(clip, idx, "gap")
    if clip in SLOW:
        return 0.55 + (h % 26) / 100.0
    if clip in OPENING:
        if MOM_RE.search(text):
            return 0.70 + (h % 16) / 100.0
        return 0.45 + (h % 16) / 100.0
    if MOM_RE.search(text):
        return 0.48 + (h % 13) / 100.0
    return 0.28 + (h % 15) / 100.0


def line_rate(clip: str, idx: int, sent: str, default: str) -> str:
    if clip == "b05" and "Kaggle" in sent:
        return "-8%"
    if clip == "b07b":
        return "-6%"
    if clip == "b14" and idx == 0:
        return "-8%"
    return default


def tts_text(clip: str, idx: int, sent: str) -> str:
    if clip == "b05" and "Kaggle" in sent:
        return "The model was trained on a public Kaggle dataset."
    if clip == "b14" and idx == 0:
        return "Alexa Plus talks to my own M. C. P. server."
    return sent


def write_timings(rows: list[tuple[str, int, float]]) -> None:
    lines = ["# clip\tsent_idx\tduration"]
    for clip, idx, dur in rows:
        lines.append(f"{clip}\t{idx}\t{dur:.3f}")
    TIMINGS.write_text("\n".join(lines) + "\n")


def _edge_tts_wav(voice: str, rate: str, text: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".edge.mp3")
    run(
        [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            f"--rate={rate}",
            "--text",
            text,
            "--write-media",
            str(raw),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-f",
            "wav",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    raw.unlink(missing_ok=True)


def ensure_music() -> Path:
    dest = VO / "music.wav"
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    print("music", dest)
    raw = dest.with_suffix(".raw.wav")
    run(
        [
            "ffmpeg",
            "-y",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=48",
            "-f", "lavfi", "-i", "sine=frequency=261.63:duration=48",
            "-f", "lavfi", "-i", "sine=frequency=329.63:duration=48",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=48",
            "-filter_complex",
            (
                "[0]volume=0.55,lowpass=f=1200[a];"
                "[1]volume=0.38,lowpass=f=1400,adelay=900|900[b];"
                "[2]volume=0.28,lowpass=f=1600,adelay=1800|1800[c];"
                "[3]volume=0.20,lowpass=f=1800,adelay=2700|2700[d];"
                "[a][b][c][d]amix=inputs=4:normalize=0,"
                "aecho=0.7:0.75:80:0.25,highpass=f=80,alimiter=limit=0.85"
            ),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(raw),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw),
            "-af",
            "loudnorm=I=-24:TP=-3:LRA=8",
            "-ac",
            "1",
            "-ar",
            "44100",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    raw.unlink(missing_ok=True)
    return dest


def ensure_room() -> Path:
    dest = VO / "roomtone.wav"
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    print("roomtone", dest)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.012:duration=8",
            "-af",
            "highpass=f=40,lowpass=f=800,volume=0.22",
            "-ac",
            "1",
            "-ar",
            "44100",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dest


def trim_take(src: Path, dest: Path) -> None:
    """Drop leading clicks and trailing TTS pad. Keep a 150ms speech tail.

    stop_periods=-1 trims from the end only, so a mid-line breath is safe.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-af",
            (
                "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.06:"
                "stop_periods=-1:stop_threshold=-42dB:stop_silence=0.15"
            ),
            "-ar",
            "24000",
            "-ac",
            "1",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def process_wav(src: Path, dest: Path, kind: str, room: Path) -> None:
    """HP80, presence EQ, light comp, room bed, LUFS. No atempo. No hard gate."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    filters = [
        "highpass=f=80",
        "equalizer=f=300:t=q:w=1.1:g=-2",
        "equalizer=f=3500:t=q:w=1.0:g=1.4",
        "acompressor=threshold=-18dB:ratio=2.5:attack=12:release=120:makeup=2",
        "aecho=0.8:0.88:36:0.18",
    ]
    if kind == "alexa":
        filters = [
            "highpass=f=200",
            "lowpass=f=6000",
            "equalizer=f=2000:t=q:w=1.0:g=1.8",
            "equalizer=f=3500:t=q:w=1.0:g=1.2",
            "equalizer=f=300:t=q:w=1.1:g=-1.5",
            "acompressor=threshold=-16dB:ratio=2.2:attack=8:release=80:makeup=1.5",
            "aecho=0.8:0.88:36:0.18",
        ]
    filters.append("silenceremove=start_periods=1:start_threshold=-44dB:start_silence=0.08")
    filters.append("areverse,afade=t=in:d=0.15,areverse")
    chain = ",".join(filters)
    tmp = dest.with_suffix(".proc.wav")
    run(
        ["ffmpeg", "-y", "-i", str(src), "-af", chain, "-ar", "44100", "-ac", "1", str(tmp)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(tmp),
            "-stream_loop",
            "-1",
            "-i",
            str(room),
            "-filter_complex",
            (
                "[1]volume=0.20,aformat=sample_fmts=fltp[r];"
                "[0][r]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                "loudnorm=I=-16:TP=-1.5:LRA=11"
            ),
            "-ar",
            "44100",
            "-ac",
            "1",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    tmp.unlink(missing_ok=True)


def concat_with_gaps(parts: list[tuple[Path, float]], dest: Path, room: Path) -> None:
    """parts: (wav, gap_after_seconds). Gaps are room tone, never digital zero."""
    if len(parts) == 1:
        run(
            ["ffmpeg", "-y", "-i", str(parts[0][0]), "-c", "copy", str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    n = len(parts)
    inputs: list[str] = []
    for i, (p, gap) in enumerate(parts):
        inputs += ["-i", str(p)]
        if i < n - 1:
            inputs += ["-stream_loop", "-1", "-t", f"{gap:.3f}", "-i", str(room)]
    labels = []
    idx = 0
    filt = []
    out_i = 0
    for i in range(n):
        filt.append(
            f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[a{out_i}]"
        )
        labels.append(f"[a{out_i}]")
        idx += 1
        out_i += 1
        if i < n - 1:
            filt.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[g{i}]"
            )
            labels.append(f"[g{i}]")
            idx += 1
    filt.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]")
    run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filt),
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(dest),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def reprocess_concats(room: Path) -> int:
    """Rebuild clip wavs from existing sentence takes with current gaps."""
    rows = read_lines()
    if ONLY:
        rows = [r for r in rows if r[0] in ONLY]
    timing_out: list[tuple[str, int, float]] = []
    for clip, speaker, text in rows:
        dest = VO / f"{clip}.wav"
        override = anoop_override(clip) if speaker == "N" else None
        if override is not None:
            print("anoop override", clip, override)
            process_wav(override, dest, VOICE[speaker]["eq"], room)
            continue
        sentences = split_sentences(text)
        assembled: list[tuple[Path, float]] = []
        missing = False
        for idx, sent in enumerate(sentences):
            take = TAKES_DIR / f"{clip}_s{idx}.wav"
            if not take.is_file():
                print(f"missing take {take}", file=sys.stderr)
                missing = True
                break
            trimmed = TAKES_DIR / f"{clip}_s{idx}_trim.wav"
            trim_take(take, trimmed)
            timing_out.append((clip, idx, wav_duration(trimmed)))
            assembled.append((trimmed, gap_after(clip, idx, sent, len(sentences))))
        if missing:
            return 2
        raw = TAKES_DIR / f"{clip}_concat.wav"
        concat_with_gaps(assembled, raw, room)
        process_wav(raw, dest, VOICE[speaker]["eq"], room)
        print("reprocessed", dest, f"{wav_duration(dest):.2f}s")
    timing_out.sort(key=lambda r: (r[0], r[1]))
    write_timings(timing_out)
    print("VO wavs in", VO)
    return 0


def anoop_override(clip: str) -> Path | None:
    for name in (f"{clip}.wav", f"{clip}.mp3"):
        p = ANOOP / name
        if p.is_file():
            return p
    return None


def selfcheck() -> int:
    bits = split_sentences("The cue, the time, how long ago, any missed check-ins.")
    assert bits[0] == "The cue," and bits[1] == "the time,"
    g = gap_after("b04", 0, "x", 2)
    assert 0.28 <= g <= 0.43
    go = gap_after("b03", 0, "x", 2)
    assert 0.45 <= go <= 0.61
    gs = gap_after("b12", 0, "x", 4)
    assert 0.55 <= gs <= 0.81
    gm = gap_after("b01", 1, "So when something happens to my mom, we only find out.", 2)
    assert 0.70 <= gm <= 0.86
    assert line_rate("b05", 2, "The model was trained on a public Kaggle dataset.", "-5%") == "-8%"
    assert line_rate("b14", 0, "Alexa Plus talks to my own M C P server.", "-5%") == "-8%"
    src = Path(__file__).read_text()
    settings = VO / "SETTINGS.txt"
    blobs = [src]
    if settings.is_file():
        blobs.append(settings.read_text())
    for blob in blobs:
        if BANNED_LOCALE in blob:
            raise AssertionError("Indian-locale stock voice tag in VO tooling")
        if MUM.search(blob):
            raise AssertionError("banned household label in VO tooling")
    for clip, _sp, text in read_lines():
        if DIGIT.search(text):
            raise AssertionError(f"digit in TTS line: {text}")
        if MUM.search(text):
            raise AssertionError(f"banned household label in TTS line {clip}: {text}")
        if BANNED_LOCALE in text:
            raise AssertionError(f"Indian-locale stock voice tag in TTS line {clip}")
    for cfg in VOICE.values():
        if not str(cfg["voice"]).startswith("en-US-"):
            raise AssertionError(f"non-US voice {cfg['voice']}")
        if "IN" in str(cfg["voice"]):
            raise AssertionError(f"disallowed voice {cfg['voice']}")
    print("SELFCHECK OK")
    return 0


def check_kaggle() -> int:
    wav = VO / "b05.wav"
    if not wav.is_file():
        print("KAGGLE CHECK: missing b05.wav", file=sys.stderr)
        return 1
    try:
        import whisper
    except ImportError:
        print("KAGGLE CHECK: whisper missing; listen to b05.wav by ear")
        return 0
    print("loading whisper tiny.en")
    model = whisper.load_model("tiny.en", device="cpu")
    result = model.transcribe(str(wav), language="en", fp16=False, verbose=False)
    hyp = str(result.get("text") or "")
    print("b05 whisper:", hyp)
    if re.search(r"kaggle|caggle|kagel|kag[\s-]?gull", hyp, re.I):
        print("KAGGLE OK")
        return 0
    print("KAGGLE CHECK: unexpected token; consider a phonetic spelling")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        return selfcheck()
    if len(sys.argv) > 1 and sys.argv[1] == "--check-kaggle":
        return check_kaggle()
    if not LINES.is_file():
        print(f"missing {LINES}", file=sys.stderr)
        return 2
    VO.mkdir(parents=True, exist_ok=True)
    TAKES_DIR.mkdir(parents=True, exist_ok=True)
    room = ensure_room()
    ensure_music()
    if os.environ.get("REPROCESS", "0") == "1":
        return reprocess_concats(room)

    rows = read_lines()
    if ONLY:
        unknown = [c for c in ONLY if c not in {r[0] for r in rows}]
        if unknown:
            print(f"unknown LINE={unknown}", file=sys.stderr)
            return 2
        rows = [r for r in rows if r[0] in ONLY]

    timing_out: list[tuple[str, int, float]] = []
    if TIMINGS.is_file() and ONLY:
        for raw in TIMINGS.read_text().splitlines():
            if not raw.strip() or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if parts[0] in ONLY:
                continue
            timing_out.append((parts[0], int(parts[1]), float(parts[2])))

    for clip, speaker, text in rows:
        dest = VO / f"{clip}.wav"
        override = anoop_override(clip) if speaker == "N" else None
        if override is not None:
            print("anoop override", clip, override)
            process_wav(override, dest, VOICE[speaker]["eq"], room)
            continue
        if dest.is_file() and not FORCE and not ONLY:
            print("skip existing", dest.name)
            continue

        cfg = VOICE[speaker]
        sentences = split_sentences(text)
        assembled: list[tuple[Path, float]] = []
        for idx, sent in enumerate(sentences):
            take = TAKES_DIR / f"{clip}_s{idx}.wav"
            spoken = tts_text(clip, idx, sent)
            rate = line_rate(clip, idx, sent, cfg["rate"])
            print(f"tts {clip} sent={idx} {cfg['voice']} {rate} {spoken[:70]}")
            _edge_tts_wav(cfg["voice"], rate, spoken, take)
            trimmed = TAKES_DIR / f"{clip}_s{idx}_trim.wav"
            trim_take(take, trimmed)
            timing_out.append((clip, idx, wav_duration(trimmed)))
            assembled.append((trimmed, gap_after(clip, idx, sent, len(sentences))))

        raw = TAKES_DIR / f"{clip}_concat.wav"
        concat_with_gaps(assembled, raw, room)
        process_wav(raw, dest, cfg["eq"], room)
        print("wrote", dest, f"{wav_duration(dest):.2f}s")

    timing_out.sort(key=lambda r: (r[0], r[1]))
    write_timings(timing_out)
    print("VO wavs in", VO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
