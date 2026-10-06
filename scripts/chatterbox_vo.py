"""Chatterbox VO for the Amazon demo. Sentence-level, seeded, cheap to regen.

Env:
  VO, LINES, ANOOP, FORCE, TAKES, LINE, DEVICE
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
VO = Path(os.environ.get("VO", ROOT / "docs/demo/vo/chatterbox"))
LINES = Path(os.environ.get("LINES", ROOT / "docs/demo/vo_lines.tsv"))
ANOOP = Path(os.environ.get("ANOOP", ROOT / "docs/demo/vo/anoop"))
FORCE = os.environ.get("FORCE", "0") == "1"
TAKES = max(1, int(os.environ.get("TAKES", "3")))
ONLY = os.environ.get("LINE", "").strip()
DEVICE = os.environ.get("DEVICE", "cpu")
REFS = VO / "refs"
TAKES_DIR = VO / "takes"
SEEDS = VO / "seeds.tsv"
SR = 24000

EMOTIONAL = {
    "And my mum said no to a caretaker.",
    "Care Ladder is for families who live far from someone who lives alone.",
}

VOICE = {
    "N": {
        "ref": REFS / "narrator_ref.wav",
        "exag": 0.45,
        "cfg": 0.35,
        "temp": 0.8,
        "eq": "narrator",
    },
    "A": {
        "ref": REFS / "alexa_ref.wav",
        "exag": 0.30,
        "cfg": 0.50,
        "temp": 0.6,
        "eq": "alexa",
    },
    "G": {
        "ref": REFS / "neighbor_ref.wav",
        "exag": 0.55,
        "cfg": 0.40,
        "temp": 0.85,
        "eq": "neighbor",
    },
}

REF_PROMPTS = {
    "narrator_ref.wav": (
        "en-IN-PrabhatNeural",
        "-15%",
        "Hey, sit for a minute. I was just thinking about last Sunday, "
        "when we made tea and talked about nothing in particular. "
        "The rain had just stopped, and the street was quiet. "
        "I like evenings like that, when nobody is in a hurry.",
    ),
    "alexa_ref.wav": (
        "en-US-AvaNeural",
        "-5%",
        "Hello. I can help with a quick check-in. Please say if you are okay, "
        "or if you need a moment. I will wait for your reply, and then I will "
        "let your family know.",
    ),
    "neighbor_ref.wav": (
        "en-IN-NeerjaNeural",
        "-8%",
        "Yes, I am nearby. I can walk over in a few minutes. Just tell me "
        "which house, and I will go now. It is no trouble at all.",
    ),
}

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


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
    return parts or [text]


def clip_hash(clip: str, idx: int, text: str) -> int:
    h = hashlib.sha256(f"{clip}|{idx}|{text}".encode()).hexdigest()
    return int(h[:8], 16)


def candidate_seeds(clip: str, idx: int, text: str) -> list[int]:
    base = clip_hash(clip, idx, text)
    return [(base + i * 9973) % 1_000_000 for i in range(TAKES)]


def gap_after(clip: str, idx: int, text: str, n_sent: int) -> float:
    """Varied edit gap. Longer around the emotional mum beat."""
    if text in EMOTIONAL or (idx == 0 and "mum lives alone" in text.lower()):
        return 0.95 + (clip_hash(clip, idx, text) % 21) / 100.0
    span = 0.32 + (clip_hash(clip, idx, "gap") % 17) / 100.0
    if idx == n_sent - 1:
        return span
    return span


def load_seeds() -> dict[tuple[str, int], int]:
    chosen: dict[tuple[str, int], int] = {}
    if not SEEDS.is_file():
        return chosen
    for raw in SEEDS.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        clip, idx_s, seed_s = parts[0], parts[1], parts[2]
        chosen[(clip, int(idx_s))] = int(seed_s)
    return chosen


def write_seeds(rows: list[tuple[str, int, int, str, float, float, float, int]]) -> None:
    lines = [
        "# clip\tsent_idx\tseed\ttext\texag\tcfg\ttemp\temotion",
    ]
    for clip, idx, seed, text, exag, cfg, temp, emo in rows:
        safe = text.replace("\t", " ")
        lines.append(
            f"{clip}\t{idx}\t{seed}\t{safe}\t{exag:.2f}\t{cfg:.2f}\t{temp:.2f}\t{emo}"
        )
    SEEDS.write_text("\n".join(lines) + "\n")


def ensure_refs() -> None:
    REFS.mkdir(parents=True, exist_ok=True)
    for name, (voice, rate, text) in REF_PROMPTS.items():
        dest = REFS / name
        if dest.is_file() and dest.stat().st_size > 1000:
            # keep a valid ref even under FORCE=1; refs are prompts, not takes
            try:
                wav_duration(dest)
                continue
            except Exception:
                dest.unlink(missing_ok=True)
        print("ref", dest.name, voice)
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
            ]
        )
        raw.unlink(missing_ok=True)
        # keep 10 to 20s; pad if short
        dur = wav_duration(dest)
        if dur < 10.0:
            pad = 10.2 - dur
            tmp = dest.with_suffix(".pad.wav")
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(dest),
                    "-af",
                    f"apad=pad_dur={pad:.2f}",
                    str(tmp),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            tmp.replace(dest)
        elif dur > 20.0:
            tmp = dest.with_suffix(".trim.wav")
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(dest),
                    "-t",
                    "18",
                    str(tmp),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            tmp.replace(dest)


def ensure_music() -> Path:
    """Original soft piano-like bed. No third-party sample."""
    dest = VO / "music.wav"
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    print("music", dest)
    # pentatonic-ish A minor arpeggio, low, looping 48s
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
                "[0]volume=0.09,lowpass=f=1200[a];"
                "[1]volume=0.05,lowpass=f=1400,adelay=900|900[b];"
                "[2]volume=0.04,lowpass=f=1600,adelay=1800|1800[c];"
                "[3]volume=0.03,lowpass=f=1800,adelay=2700|2700[d];"
                "[a][b][c][d]amix=inputs=4:normalize=0,"
                "aecho=0.7:0.75:80:0.25,highpass=f=80,volume=0.35"
            ),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(dest),
        ]
    )
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
            "anoisesrc=color=pink:amplitude=0.003:duration=8",
            "-af",
            "highpass=f=40,lowpass=f=800,volume=0.08",
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


def score_take(path: Path, text: str) -> float:
    """Prefer mid speaking rate, some energy variance, no clip, not tiny."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError:
        return wav_duration(path)
    audio, sr = sf.read(str(path), always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size < sr * 0.2:
        return -1e9
    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:
        return -1e6
    words = max(1, len(text.split()))
    dur = audio.size / sr
    wps = words / max(dur, 0.01)
    # ~2.4 to 3.4 words/sec sounds conversational; punish extremes
    rate = -abs(wps - 2.8) * 4.0
    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < 0.01:
        return -1e5
    win = max(1, sr // 10)
    chunks = [audio[i : i + win] for i in range(0, audio.size, win) if audio[i : i + win].size > 8]
    vars_ = [float(np.sqrt(np.mean(c**2))) for c in chunks]
    var = float(np.std(vars_)) if vars_ else 0.0
    # tiny natural breaths help; totally flat is bad
    return rate + min(var * 20.0, 3.0) + min(rms * 8.0, 2.0)


def process_wav(src: Path, dest: Path, kind: str, room: Path) -> None:
    """HPF, 300 Hz cut, light compress, short room, optional Alexa EQ, bed, LUFS."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    filters = [
        "highpass=f=80",
        "equalizer=f=300:t=q:w=1.1:g=-2",
        "acompressor=threshold=-18dB:ratio=2.5:attack=12:release=120:makeup=2",
        "aecho=0.8:0.88:36:0.18",
    ]
    if kind == "alexa":
        filters = [
            "highpass=f=200",
            "lowpass=f=6000",
            "equalizer=f=2000:t=q:w=1.0:g=1.8",
            "equalizer=f=300:t=q:w=1.1:g=-1.5",
            "acompressor=threshold=-16dB:ratio=2.2:attack=8:release=80:makeup=1.5",
            "aecho=0.8:0.88:36:0.18",
        ]
    # Trim only leading/trailing clicks. stop_periods=1 would cut at the
    # first inter-sentence breath and drop the rest of the beat.
    filters.append(
        "silenceremove=start_periods=1:start_threshold=-44dB:start_silence=0.05,"
        "areverse,"
        "silenceremove=start_periods=1:start_threshold=-44dB:start_silence=0.08,"
        "areverse"
    )
    chain = ",".join(filters)
    tmp = dest.with_suffix(".proc.wav")
    run(
        ["ffmpeg", "-y", "-i", str(src), "-af", chain, "-ar", "44100", "-ac", "1", str(tmp)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # room-tone bed so silences never hit digital zero, then loudnorm
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
                "[1]volume=0.12,aformat=sample_fmts=fltp[r];"
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


def concat_with_gaps(parts: list[tuple[Path, float]], dest: Path) -> None:
    """parts: (wav, gap_after_seconds). Last gap is ignored."""
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
            inputs += ["-f", "lavfi", "-t", f"{gap:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
    # anullsrc is digital zero; mix a whisper of room in a second pass via process
    labels = []
    idx = 0
    filt = []
    out_i = 0
    for i in range(n):
        filt.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[a{out_i}]")
        labels.append(f"[a{out_i}]")
        idx += 1
        out_i += 1
        if i < n - 1:
            filt.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono,volume=0[g{i}]"
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


def set_seed(seed: int) -> None:
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def generate_sentence(model, text: str, speaker: str, seed: int, emotion: bool):
    cfg = VOICE[speaker]
    exag = 0.60 if emotion and speaker == "N" else cfg["exag"]
    cfgw = 0.30 if emotion and speaker == "N" else cfg["cfg"]
    set_seed(seed)
    wav = model.generate(
        text,
        audio_prompt_path=str(cfg["ref"]),
        exaggeration=exag,
        cfg_weight=cfgw,
        temperature=cfg["temp"],
    )
    return wav, exag, cfgw, cfg["temp"]


def save_tensor(wav, path: Path, sr: int) -> None:
    import torchaudio

    if hasattr(wav, "cpu"):
        wav = wav.cpu()
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    torchaudio.save(str(path), wav, sr)


def anoop_override(clip: str) -> Path | None:
    for name in (f"{clip}.wav", f"{clip}.mp3"):
        p = ANOOP / name
        if p.is_file():
            return p
    return None


def reprocess_concats(room: Path) -> None:
    """Re-run the mix chain on existing sentence concats (no TTS)."""
    rows = read_lines()
    for clip, speaker, _text in rows:
        raw = TAKES_DIR / f"{clip}_concat.wav"
        dest = VO / f"{clip}.wav"
        if not raw.is_file():
            continue
        if ONLY and clip != ONLY:
            continue
        process_wav(raw, dest, VOICE[speaker]["eq"], room)
        print("reprocessed", dest, f"{wav_duration(dest):.2f}s")


def main() -> int:
    if not LINES.is_file():
        print(f"missing {LINES}", file=sys.stderr)
        return 2
    VO.mkdir(parents=True, exist_ok=True)
    TAKES_DIR.mkdir(parents=True, exist_ok=True)
    ensure_refs()
    room = ensure_room()
    ensure_music()
    if os.environ.get("REPROCESS", "0") == "1":
        reprocess_concats(room)
        print("VO wavs in", VO)
        return 0

    rows = read_lines()
    if ONLY:
        rows = [r for r in rows if r[0] == ONLY]
        if not rows:
            print(f"unknown LINE={ONLY}", file=sys.stderr)
            return 2

    stored = load_seeds()
    seed_out: list[tuple[str, int, int, str, float, float, float, int]] = []
    # keep seeds for clips we are not regenerating
    if SEEDS.is_file():
        for raw in SEEDS.read_text().splitlines():
            if not raw.strip() or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if ONLY and parts[0] == ONLY:
                continue
            if not ONLY and FORCE:
                continue
            seed_out.append(
                (
                    parts[0],
                    int(parts[1]),
                    int(parts[2]),
                    parts[3] if len(parts) > 3 else "",
                    float(parts[4]) if len(parts) > 4 else 0.45,
                    float(parts[5]) if len(parts) > 5 else 0.35,
                    float(parts[6]) if len(parts) > 6 else 0.8,
                    int(parts[7]) if len(parts) > 7 else 0,
                )
            )

    need_tts = False
    for clip, speaker, text in rows:
        dest = VO / f"{clip}.wav"
        if anoop_override(clip) and speaker == "N":
            continue
        if dest.is_file() and not FORCE and not ONLY:
            continue
        need_tts = True

    model = None
    if need_tts:
        print(f"loading ChatterboxTTS device={DEVICE}")
        import perth
        from chatterbox.tts import ChatterboxTTS

        # perth-net import fails without pkg_resources; DummyWatermarker is a no-op.
        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            perth.PerthImplicitWatermarker = perth.DummyWatermarker

        model = ChatterboxTTS.from_pretrained(device=DEVICE)

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

        sentences = split_sentences(text)
        assembled: list[tuple[Path, float]] = []
        for idx, sent in enumerate(sentences):
            emotion = sent in EMOTIONAL
            if stored.get((clip, idx)) is not None and not FORCE:
                seeds = [stored[(clip, idx)]]
            else:
                seeds = candidate_seeds(clip, idx, sent)
            best_path = None
            best_score = -1e18
            best_meta = (seeds[0], VOICE[speaker]["exag"], VOICE[speaker]["cfg"], VOICE[speaker]["temp"])
            for seed in seeds:
                take = TAKES_DIR / f"{clip}_s{idx}_{seed}.wav"
                if model is None:
                    print("need Chatterbox model but skip-only path ran", file=sys.stderr)
                    return 2
                print(f"tts {clip} sent={idx} seed={seed} emo={int(emotion)} {sent[:60]}")
                wav, exag, cfgw, temp = generate_sentence(model, sent, speaker, seed, emotion)
                save_tensor(wav, take, getattr(model, "sr", SR))
                sc = score_take(take, sent)
                print(f"  score {sc:.3f} dur={wav_duration(take):.2f}s")
                if sc > best_score:
                    best_score = sc
                    best_path = take
                    best_meta = (seed, exag, cfgw, temp)
            assert best_path is not None
            seed, exag, cfgw, temp = best_meta
            seed_out.append((clip, idx, seed, sent, exag, cfgw, temp, int(emotion)))
            gap = gap_after(clip, idx, sent, len(sentences))
            assembled.append((best_path, gap))

        raw = TAKES_DIR / f"{clip}_concat.wav"
        concat_with_gaps(assembled, raw)
        process_wav(raw, dest, VOICE[speaker]["eq"], room)
        print("wrote", dest, f"{wav_duration(dest):.2f}s")

    seed_out.sort(key=lambda r: (r[0], r[1]))
    write_seeds(seed_out)
    print("VO wavs in", VO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
