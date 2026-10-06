"""Hard-rule grep of VO lines plus on-screen overlay / story text.

Fails if em dashes, the abbreviation ack, fall/bathroom detail, secrets,
or model paths appear in the tape sources.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VO_LINES = ROOT / "docs/demo/vo_lines.tsv"
OVERLAY = ROOT / "scripts/demo_overlays.html"
STORY = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/demo/frames/story.json"

EM = re.compile(r"[\u2014\u2013]")
ACK = re.compile(r"(?<![A-Za-z])ack(?![A-Za-z])", re.I)
ACKED = re.compile(r"\backed\b", re.I)
FALL = re.compile(r"\bfalls?\b|\bbathroom\b", re.I)
SECRET = re.compile(
    r"fall_classifier\.npz|CARTESIA_API_KEY|AKIA[0-9A-Z]{16}|BEGIN PRIVATE KEY",
    re.I,
)


def collect() -> list[tuple[str, str]]:
    blobs: list[tuple[str, str]] = []
    blobs.append((str(VO_LINES), VO_LINES.read_text()))
    blobs.append((str(OVERLAY), OVERLAY.read_text()))
    if STORY.is_file():
        blobs.append((str(STORY), STORY.read_text()))
        data = json.loads(STORY.read_text())
        blobs.append(("story.json values", json.dumps(data, ensure_ascii=True)))
    for rel in (
        "docs/demo/vo/edge/SETTINGS.txt",
        "docs/demo/vo/chatterbox/SETTINGS.txt",
        "scripts/edge_vo.py",
        "scripts/chatterbox_vo.py",
        "scripts/generate_amazon_demo_vo_edge.sh",
        "scripts/generate_amazon_demo_vo_chatterbox.sh",
    ):
        p = ROOT / rel
        if p.is_file():
            blobs.append((str(p), p.read_text()))
    return blobs


DIGIT = re.compile(r"[0-9]")


def main() -> int:
    bad: list[str] = []
    for raw in VO_LINES.read_text().splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        _clip, _sp, text = raw.split("\t", 2)
        if DIGIT.search(text):
            bad.append(f"digit in TTS line {_clip}: {text[:80]}")
    for name, text in collect():
        if EM.search(text):
            bad.append(f"em/en dash in {name}")
        if ACK.search(text) or ACKED.search(text):
            # acknowledgment / Acknowledge / Alexa stay allowed
            for m in ACK.finditer(text):
                around = text[max(0, m.start() - 18) : m.end() + 18]
                if re.search(r"acknowledg", around, re.I):
                    continue
                if re.search(r"acknowledge", around, re.I):
                    continue
                bad.append(f"ack abbreviation in {name}: ...{around}...")
            if ACKED.search(text):
                bad.append(f"acked in {name}")
        if FALL.search(text):
            bad.append(f"fall/bathroom in {name}")
        if SECRET.search(text):
            bad.append(f"secret/model path in {name}")
        if "live video" in text.lower() and "nobody" not in text.lower():
            bad.append(f"live video claim in {name}")
        if name.endswith("demo_overlays.html") and "placeholder" in text.lower():
            bad.append(f"placeholder on screen in {name}")
        banned_locale = "en" + "-" + "IN"
        banned_label = "M" + "um"
        if banned_locale in text:
            bad.append(f"Indian-locale stock voice tag in {name}")
        if re.search(rf"\b{banned_label}\b", text):
            bad.append(f"banned household label in {name}")
    if bad:
        print("COPY FAIL")
        for b in bad:
            print(" -", b)
        return 1
    print("COPY OK")
    print("checked", VO_LINES)
    print("checked", OVERLAY)
    if STORY.is_file():
        print("checked", STORY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
