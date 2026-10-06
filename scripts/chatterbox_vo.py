"""Chatterbox VO for the Amazon demo. Sentence-level, seeded, cheap to regen.

V4 knobs (sister OpenCV demo): narrator 0.55 / 0.38 / 0.80, 15-16s warm ref,
per-sentence takes, whisper WER + highest f0 std + no clip. Never atempo.

Env:
  VO, LINES, ANOOP, FORCE, TAKES, LINE, DEVICE, REPROCESS, FORCE_REFS
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
ONLY = [x.strip() for x in os.environ.get("LINE", "").split(",") if x.strip()]
DEVICE = os.environ.get("DEVICE", "cpu")
FORCE_REFS = os.environ.get("FORCE_REFS", "0") == "1"
REFS = VO / "refs"
TAKES_DIR = VO / "takes"
SEEDS = VO / "seeds.tsv"
TIMINGS = VO / "timings.tsv"
SR = 24000

EMOTIONAL = {
    "And my mum said no to a caretaker.",
    "Care Ladder is for families who live far from someone who lives alone.",
}

# Extra takes on the lines the review called out.
EXTRA_TAKES = {
    "b02": 8,
    "b04": 8,
    "b05": 6,
    "b06": 6,
    "b08b": 8,
    "b10b": 8,
    "b11a": 8,
    "b11b": 8,
    "b14": 6,
}

VOICE = {
    "N": {
        "ref": REFS / "narrator_ref.wav",
        "exag": 0.55,
        "cfg": 0.38,
        "temp": 0.80,
        "eq": "narrator",
    },
    "A": {
        "ref": REFS / "alexa_ref.wav",
        "exag": 0.30,
        "cfg": 0.50,
        "temp": 0.60,
        "eq": "alexa",
    },
    "G": {
        "ref": REFS / "neighbor_ref.wav",
        "exag": 0.45,
        "cfg": 0.45,
        "temp": 0.80,
        "eq": "neighbor",
    },
}

# Warm conversational prompts. Over-long on purpose so a 16.2s trim is speech,
# not silence (V4: reference length matters most).
REF_PROMPTS = {
    "narrator_ref.wav": (
        "en-IN-PrabhatNeural",
        "-12%",
        "Hey, sit for a minute. I was just thinking about last Sunday, "
        "when we made tea and talked about nothing in particular. "
        "The rain had just stopped, and the street was quiet. "
        "I like evenings like that, when nobody is in a hurry, "
        "and we can just sit and listen to the fans. "
        "Tell me how your week has been, and whether you found time to rest. "
        "I keep thinking about that walk to the shop, how we stood on the "
        "corner and watched the buses go by, then came home and sat down.",
    ),
    "alexa_ref.wav": (
        "en-US-AvaNeural",
        "-8%",
        "Hello. I can help with a quick check-in. Please say if you are okay, "
        "or if you need a moment. I will wait for your reply, and then I will "
        "let your family know. There is no rush. Take your time, and answer "
        "when you are ready. If you would like a glass of water, or if you "
        "want me to try someone else, just say so. I am here, and I will "
        "stay on until we know that you are fine.",
    ),
    "neighbor_ref.wav": (
        "en-IN-NeerjaNeural",
        "-10%",
        "Yes, I am nearby. I can walk over in a few minutes. Just tell me "
        "which house, and I will go now. It is no trouble at all. I will knock, "
        "see that she is fine, and then I will call you back. "
        "If the gate is locked I will wait by the steps, and I will not rush her. "
        "These things take a moment, and that is all right with me.",
    ),
}

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[a-z0-9']+")


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


def n_takes(clip: str) -> int:
    return max(TAKES, EXTRA_TAKES.get(clip, TAKES))


def candidate_seeds(clip: str, idx: int, text: str) -> list[int]:
    base = clip_hash(clip, idx, text)
    return [(base + i * 9973) % 1_000_000 for i in range(n_takes(clip))]


def gap_after(clip: str, idx: int, text: str, n_sent: int) -> float:
    """0.20 to 0.35s between sentences. Beat changes are handled in render."""
    _ = (text, n_sent)
    return 0.20 + (clip_hash(clip, idx, "gap") % 16) / 100.0


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


def write_timings(rows: list[tuple[str, int, float, int]]) -> None:
    lines = ["# clip\tsent_idx\tduration\tseed"]
    for clip, idx, dur, seed in rows:
        lines.append(f"{clip}\t{idx}\t{dur:.3f}\t{seed}")
    TIMINGS.write_text("\n".join(lines) + "\n")


def _edge_tts_wav(voice: str, rate: str, text: str, dest: Path) -> None:
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


def _speech_duration(path: Path) -> float:
    """Seconds of non-silent audio. Padding silence does not count."""
    try:
        import numpy as np
        import soundfile as sf
    except ImportError:
        return wav_duration(path)
    audio, sr = sf.read(str(path), always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if audio.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(audio**2)))
    thr = max(0.008, rms * 0.12)
    win = max(1, sr // 50)
    voiced = 0
    for i in range(0, audio.size, win):
        chunk = audio[i : i + win]
        if float(np.sqrt(np.mean(chunk**2))) >= thr:
            voiced += chunk.size
    return voiced / float(sr)


def ensure_refs() -> None:
    REFS.mkdir(parents=True, exist_ok=True)
    extra = (
        " I keep thinking about that walk to the shop, "
        "how we stood on the corner and watched the buses go by."
    )
    for name, (voice, rate, text) in REF_PROMPTS.items():
        dest = REFS / name
        if dest.is_file() and dest.stat().st_size > 1000 and not FORCE_REFS:
            try:
                spoken = _speech_duration(dest)
                total = wav_duration(dest)
                if 14.5 <= spoken <= 16.8 and total <= 17.2:
                    continue
            except Exception:
                dest.unlink(missing_ok=True)
        print("ref", dest.name, voice)
        _edge_tts_wav(voice, rate, text, dest)
        spoken = _speech_duration(dest)
        if spoken < 14.8:
            more = dest.with_suffix(".more.wav")
            _edge_tts_wav(voice, rate, extra.strip(), more)
            joined = dest.with_suffix(".join.wav")
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(dest),
                    "-i",
                    str(more),
                    "-filter_complex",
                    "[0][1]concat=n=2:v=0:a=1[out]",
                    "-map",
                    "[out]",
                    str(joined),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            joined.replace(dest)
            more.unlink(missing_ok=True)
        # Keep 15.2 to 16.2s of the speaking take. Do not pad with silence.
        spoken = _speech_duration(dest)
        total = wav_duration(dest)
        keep = 16.2 if spoken >= 15.0 or total >= 16.2 else max(15.2, min(16.2, total))
        tmp = dest.with_suffix(".trim.wav")
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(dest),
                "-t",
                f"{keep:.2f}",
                str(tmp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tmp.replace(dest)
        print(
            "  ref dur",
            f"{wav_duration(dest):.2f}s",
            "speech",
            f"{_speech_duration(dest):.2f}s",
        )


def ensure_music() -> Path:
    """Original soft piano-like bed, loud enough to sit ~-22 dB under speech."""
    dest = VO / "music.wav"
    if dest.is_file() and dest.stat().st_size > 1000 and not FORCE_REFS:
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
    # Target a usable bed (~-24 dB mean) so render gains can duck to -22 under speech.
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
    if dest.is_file() and dest.stat().st_size > 1000 and not FORCE_REFS:
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


def _norm_words(text: str) -> list[str]:
    t = text.lower()
    t = t.replace("kag-gull", "kaggle").replace("kag gull", "kaggle")
    t = t.replace("two hundred and four", "two hundred four")
    t = re.sub(r"\b204\b", "two hundred four", t)
    return WORD_RE.findall(t)


def word_wer(ref: str, hyp: str) -> float:
    r = _norm_words(ref)
    h = _norm_words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    dp = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        dp[i][0] = i
    for j in range(len(h) + 1):
        dp[0][j] = j
    for i, rw in enumerate(r, 1):
        for j, hw in enumerate(h, 1):
            dp[i][j] = min(
                dp[i - 1][j] + 1,
                dp[i][j - 1] + 1,
                dp[i - 1][j - 1] + (0 if rw == hw else 1),
            )
    return dp[-1][-1] / float(len(r))


def _load_audio(path: Path):
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(str(path), always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return np.asarray(audio, dtype=float), int(sr)


def peak_clipped(audio) -> bool:
    import numpy as np

    if audio.size == 0:
        return True
    return float(np.max(np.abs(audio))) > 0.99


def f0_std(audio, sr: int) -> float:
    import numpy as np

    try:
        import librosa
    except ImportError:
        win = max(1, sr // 10)
        chunks = [audio[i : i + win] for i in range(0, audio.size, win) if audio[i : i + win].size > 8]
        vars_ = [float(np.sqrt(np.mean(c**2))) for c in chunks]
        return float(np.std(vars_)) if vars_ else 0.0
    f0, _, _ = librosa.pyin(
        audio.astype(float),
        fmin=70,
        fmax=360,
        sr=sr,
        frame_length=2048,
    )
    voiced = f0[~np.isnan(f0)]
    if voiced.size < 6:
        return 0.0
    return float(np.std(voiced))


def ending_clip_ratio(audio, sr: int) -> float:
    """High when the last voiced word dies in a cliff (<45ms) instead of a decay."""
    import numpy as np

    if audio.size < int(sr * 0.25):
        return 0.0
    hop = max(1, sr // 100)
    env = []
    for i in range(0, audio.size, hop):
        chunk = audio[i : i + hop]
        env.append(float(np.sqrt(np.mean(chunk**2))) if chunk.size else 0.0)
    peak = max(env) or 1.0
    thr = peak * 0.08
    last = len(env) - 1
    while last > 0 and env[last] < thr:
        last -= 1
    if last < 6:
        return 0.0
    local = env[max(0, last - 30) : last + 1]
    loc_peak = max(local) or 1.0
    k = last
    while k > 0 and env[k] < 0.45 * loc_peak:
        k -= 1
    decay_s = (last - k) * (hop / sr)
    # 0.15s+ is a natural tail; 0.03s is a chopped word.
    if decay_s >= 0.12:
        return 0.0
    return max(0.0, (0.12 - decay_s) / 0.12)


def odd_stress_penalty(audio, sr: int) -> float:
    """Punish flat reads and a last-word pitch bend."""
    import numpy as np

    try:
        import librosa
    except ImportError:
        return 0.0
    f0, _, _ = librosa.pyin(
        audio.astype(float),
        fmin=70,
        fmax=360,
        sr=sr,
        frame_length=2048,
    )
    voiced = f0[~np.isnan(f0)]
    if voiced.size < 8:
        return -4.0
    std = float(np.std(voiced))
    pen = 0.0
    if std < 8.0:
        pen -= 6.0
    tail = voiced[int(voiced.size * 0.75) :]
    head = voiced[: max(1, int(voiced.size * 0.75))]
    if tail.size and head.size and abs(float(np.mean(tail)) - float(np.mean(head))) > 55:
        pen -= 5.0
    return pen


def longest_internal_silence(audio, sr: int) -> float:
    """Longest mid-utterance gap. Catches 'Are you, okay?' style bends."""
    import numpy as np

    if audio.size < sr * 0.25:
        return 0.0
    rms = float(np.sqrt(np.mean(audio**2)))
    thr = max(0.012, rms * 0.15)
    win = max(1, sr // 40)
    silent = []
    for i in range(0, audio.size, win):
        chunk = audio[i : i + win]
        silent.append(float(np.sqrt(np.mean(chunk**2))) < thr)
    # ignore 80ms edges
    edge = max(1, int(0.08 * sr / win))
    mid = silent[edge : len(silent) - edge] if len(silent) > edge * 2 else silent
    best = 0
    run = 0
    for flag in mid:
        if flag:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best * (win / sr)


def whisper_hyp(path: Path, model) -> str:
    if model is None:
        return ""
    result = model.transcribe(str(path), language="en", fp16=False, verbose=False)
    return str(result.get("text") or "")


def score_take(path: Path, text: str, whisper_model=None) -> float:
    """Higher is better: WER match, highest f0 std, no clip, no mid pause."""
    try:
        audio, sr = _load_audio(path)
    except Exception:
        return -1e9
    if audio.size < sr * 0.15:
        return -1e9
    if peak_clipped(audio):
        return -1e6
    words = max(1, len(text.split()))
    dur = audio.size / sr
    if dur < 0.18 * words or dur > 1.6 * words + 1.2:
        # sanity: not a clipped fragment or a stalled take
        sanity = -8.0
    else:
        sanity = 0.0
    pause = longest_internal_silence(audio, sr)
    # Alexa "Are you okay?" should be one phrase; a comma-pause fails.
    pause_pen = 0.0
    if pause > 0.22:
        pause_pen = -12.0 - (pause - 0.22) * 20.0
    end_pen = 0.0
    end_r = ending_clip_ratio(audio, sr)
    if end_r > 0.22:
        end_pen = -10.0 - (end_r - 0.22) * 25.0
    stress_pen = odd_stress_penalty(audio, sr)
    f0 = f0_std(audio, sr)
    wer = 0.0
    if whisper_model is not None:
        hyp = whisper_hyp(path, whisper_model)
        wer = word_wer(text, hyp)
        if wer > 0.55:
            return -1e5 + f0
    # Prefer low WER, then high f0 variance, intact last word.
    return (
        sanity
        + pause_pen
        + end_pen
        + stress_pen
        + (1.0 - min(wer, 1.0)) * 20.0
        + min(f0, 80.0) * 0.12
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
    # Leading click only. Never hard-trim the last word; 150ms tail fade.
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
        filt.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[a{out_i}]")
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


def set_seed(seed: int) -> None:
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def generate_sentence(model, text: str, speaker: str, seed: int, emotion: bool):
    cfg = VOICE[speaker]
    exag = 0.62 if emotion and speaker == "N" else cfg["exag"]
    cfgw = 0.32 if emotion and speaker == "N" else cfg["cfg"]
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
    rows = read_lines()
    for clip, speaker, _text in rows:
        raw = TAKES_DIR / f"{clip}_concat.wav"
        dest = VO / f"{clip}.wav"
        if not raw.is_file():
            continue
        if ONLY and clip not in ONLY:
            continue
        process_wav(raw, dest, VOICE[speaker]["eq"], room)
        print("reprocessed", dest, f"{wav_duration(dest):.2f}s")


def load_whisper():
    try:
        import whisper
    except ImportError:
        print("warning: openai-whisper missing; take pick falls back to f0 only", file=sys.stderr)
        return None
    print("loading whisper tiny.en")
    return whisper.load_model("tiny.en", device="cpu")


def audit_narrator() -> int:
    """Score current narrator sentence takes: clipped endings + odd stress."""
    stored = load_seeds()
    rows = []
    for clip, speaker, text in read_lines():
        if speaker != "N":
            continue
        for idx, sent in enumerate(split_sentences(text)):
            seed = stored.get((clip, idx))
            take = TAKES_DIR / f"{clip}_s{idx}_{seed}.wav" if seed is not None else None
            if take is None or not take.is_file():
                dest = VO / f"{clip}.wav"
                if not dest.is_file():
                    continue
                take = dest
            audio, sr = _load_audio(take)
            end_r = ending_clip_ratio(audio, sr)
            stress = odd_stress_penalty(audio, sr)
            f0 = f0_std(audio, sr)
            # Higher bad = worse
            bad = end_r * 12.0 - stress - min(f0, 40.0) * 0.05
            rows.append((bad, end_r, f0, stress, clip, idx, sent, take.name))
    rows.sort(reverse=True)
    print("# worst narrator takes (clipped ending / odd stress)")
    print("# rank\tclip\tsent\tend_ratio\tf0_std\tstress\ttext")
    for i, (bad, end_r, f0, stress, clip, idx, sent, name) in enumerate(rows[:12], 1):
        print(f"{i}\t{clip}\t{idx}\t{end_r:.3f}\t{f0:.2f}\t{stress:.1f}\t{sent[:70]}\t{name}")
    dest = VO / "narrator_audit.tsv"
    lines = ["# rank\tclip\tsent_idx\tend_ratio\tf0_std\tstress\tbad\ttext"]
    for i, (bad, end_r, f0, stress, clip, idx, sent, _n) in enumerate(rows, 1):
        lines.append(
            f"{i}\t{clip}\t{idx}\t{end_r:.3f}\t{f0:.2f}\t{stress:.1f}\t{bad:.3f}\t{sent}"
        )
    dest.write_text("\n".join(lines) + "\n")
    print("wrote", dest)
    worst = [r[4] for r in rows[:5]]
    print("WORST5_CLIPS", ",".join(dict.fromkeys(worst)))
    return 0


def selfcheck() -> int:
    assert abs(word_wer("Are you okay?", "Are you okay?")) < 1e-9
    assert word_wer("Are you okay?", "Are you, okay?") < 0.2
    assert word_wer("I'm going.", "I am leaving now.") > 0.4
    assert word_wer("Kag-gull dataset", "Kaggle dataset") == 0.0
    bits = split_sentences("The cue, the time, how long ago, any missed check-ins.")
    assert bits[0] == "The cue," and bits[1] == "the time,"
    assert 0.20 <= gap_after("b03", 0, "x", 2) <= 0.35
    for _clip, _sp, text in read_lines():
        if re.search(r"\d", text):
            raise AssertionError(f"digit in TTS line: {text}")
    print("SELFCHECK OK")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        return selfcheck()
    if len(sys.argv) > 1 and sys.argv[1] == "--audit-narrator":
        return audit_narrator()
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
        unknown = [c for c in ONLY if c not in {r[0] for r in read_lines()}]
        if unknown:
            print(f"unknown LINE={unknown}", file=sys.stderr)
            return 2
        rows = [r for r in rows if r[0] in ONLY]

    stored = load_seeds()
    seed_out: list[tuple[str, int, int, str, float, float, float, int]] = []
    timing_out: list[tuple[str, int, float, int]] = []
    if TIMINGS.is_file() and ONLY:
        for raw in TIMINGS.read_text().splitlines():
            if not raw.strip() or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if parts[0] in ONLY:
                continue
            timing_out.append((parts[0], int(parts[1]), float(parts[2]), int(parts[3])))
    if SEEDS.is_file():
        for raw in SEEDS.read_text().splitlines():
            if not raw.strip() or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if ONLY and parts[0] in ONLY:
                continue
            if not ONLY and FORCE:
                continue
            seed_out.append(
                (
                    parts[0],
                    int(parts[1]),
                    int(parts[2]),
                    parts[3] if len(parts) > 3 else "",
                    float(parts[4]) if len(parts) > 4 else 0.55,
                    float(parts[5]) if len(parts) > 5 else 0.38,
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
    whisper_model = None
    if need_tts:
        print(f"loading ChatterboxTTS device={DEVICE}")
        import perth
        from chatterbox.tts import ChatterboxTTS

        if getattr(perth, "PerthImplicitWatermarker", None) is None:
            perth.PerthImplicitWatermarker = perth.DummyWatermarker

        model = ChatterboxTTS.from_pretrained(device=DEVICE)
        whisper_model = load_whisper()

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
            if stored.get((clip, idx)) is not None and not FORCE and not ONLY:
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
                sc = score_take(take, sent, whisper_model)
                print(f"  score {sc:.3f} dur={wav_duration(take):.2f}s")
                if sc > best_score:
                    best_score = sc
                    best_path = take
                    best_meta = (seed, exag, cfgw, temp)
            assert best_path is not None
            seed, exag, cfgw, temp = best_meta
            seed_out.append((clip, idx, seed, sent, exag, cfgw, temp, int(emotion)))
            timing_out.append((clip, idx, wav_duration(best_path), seed))
            gap = gap_after(clip, idx, sent, len(sentences))
            assembled.append((best_path, gap))

        raw = TAKES_DIR / f"{clip}_concat.wav"
        concat_with_gaps(assembled, raw, room)
        process_wav(raw, dest, VOICE[speaker]["eq"], room)
        print("wrote", dest, f"{wav_duration(dest):.2f}s")

    seed_out.sort(key=lambda r: (r[0], r[1]))
    write_seeds(seed_out)
    timing_out.sort(key=lambda r: (r[0], r[1]))
    write_timings(timing_out)
    print("VO wavs in", VO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
