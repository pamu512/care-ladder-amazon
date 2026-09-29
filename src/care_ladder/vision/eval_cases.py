"""Labeled evaluation fixtures for Care Ladder cue detection.

Each case: a short frame sequence (synthetic OpenCV-rendered scenario or a
sample photo loop) plus the expected cue (or None) within a time budget.

Metrics produced by scripts/evaluate.py:
- time-to-confirm: seconds from sequence start to expected cue emission
- false-escalation rate: fraction of expect-none cases that emitted a cue
- cue recall: fraction of expect-cue cases that emitted the right cue
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
FixturesDir = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
ClipsDir = Path(__file__).resolve().parents[3] / "clips"


@dataclass
class EvalCase:
    case_id: str
    description: str
    expect_cue: str | None  # "no_movement" | "no_visibility" | "distress_heuristic" | None
    timeout_sec: float
    frames: Callable[[], list[tuple[np.ndarray, float]]]  # [(frame, t), ...]


def _noisy_room(w: int = 320, h: int = 240, seed: int = 0, t: int = 0) -> np.ndarray:
    """Living-room-ish background: gradient + mild sensor noise + slow light drift."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack(
        [50 + yy * 0.06 + t * 0.5, 60 + yy * 0.05 + t * 0.4, 70 + yy * 0.04 + t * 0.3],
        axis=-1,
    )
    frame = base + rng.normal(0, 4, (h, w, 3))
    return np.clip(frame, 0, 255).astype(np.uint8)


def _person_standing(f: np.ndarray, cx: int, cy: int) -> None:
    """Draw a simple textured person (head + torso) centered at (cx, cy)."""
    h, w = f.shape[:2]
    torso_h, torso_w = 90, 44
    x1, x2 = max(0, cx - torso_w // 2), min(w, cx + torso_w // 2)
    y1, y2 = max(0, cy), min(h, cy + torso_h)
    f[y1:y2, x1:x2] = (110, 130, 150)
    head_r = 14
    hy = max(head_r, cy - head_r)
    cv2.circle(f, (cx, int(hy)), head_r, (180, 170, 160), -1)


def _person_on_floor(f: np.ndarray, cx: int, cy: int) -> None:
    """Wide, low, horizontal blob near the floor (distress stand-in)."""
    h, w = f.shape[:2]
    body_w, body_h = 120, 26
    x1, x2 = max(0, cx - body_w // 2), min(w, cx + body_w // 2)
    y1, y2 = max(0, cy), min(h, cy + body_h)
    f[y1:y2, x1:x2] = (110, 130, 150)


def _seq_still_person() -> list[tuple[np.ndarray, float]]:
    """Person sits motionless in zone for 6s (fps 2) → no_movement at ~timeout."""
    frames = []
    for i in range(13):  # t=0..6
        f = _noisy_room(t=i)
        _person_standing(f, 160, 90)
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_active_person() -> list[tuple[np.ndarray, float]]:
    """Person moves within zone every frame → no cue expected."""
    frames = []
    for i in range(13):
        f = _noisy_room(t=i)
        _person_standing(f, 140 + (i % 5) * 10, 90 + (i % 3) * 6)
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_leaves_zone() -> list[tuple[np.ndarray, float]]:
    """Person present, then walks out of frame → no_visibility."""
    frames = []
    for i in range(8):
        f = _noisy_room(t=i)
        if i < 4:
            _person_standing(f, 160, 90)
        # i>=4: empty room
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_on_floor() -> list[tuple[np.ndarray, float]]:
    """Person lying on floor, still → distress_heuristic (non-clinical)."""
    frames = []
    for i in range(10):
        f = _noisy_room(t=i)
        _person_on_floor(f, 160, 200)
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_pet_motion() -> list[tuple[np.ndarray, float]]:
    """No person; small moving blob (pet stand-in) → no cue expected."""
    frames = []
    for i in range(13):
        f = _noisy_room(t=i)
        x = 60 + i * 12
        f[180:200, x : x + 24] = (90, 90, 95)  # small low blob
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_light_shift() -> list[tuple[np.ndarray, float]]:
    """Empty room with a strong illumination ramp → no cue expected (MOG2)."""
    frames = []
    for i in range(13):
        f = _noisy_room(t=i * 6)  # aggressive drift
        frames.append((f, float(i) * 0.5))
    return frames


def _seq_photo_person_still() -> list[tuple[np.ndarray, float]]:
    """Real photo (OpenCV sample with a person) repeated → DNN localizes person;
    identical frames → stillness → no_movement. Requires tests/fixtures/basketball1.png
    and the ONNX model; skipped by evaluate.py when absent."""
    photo = cv2.imread(str(FixturesDir / "basketball1.png"))
    if photo is None:
        return []
    return [(photo, float(i) * 0.5) for i in range(8)]


def build_cases() -> list[EvalCase]:
    return [
        EvalCase(
            "still_person",
            "person motionless in zone 6s",
            "no_movement",
            timeout_sec=4.0,
            frames=_seq_still_person,
        ),
        EvalCase(
            "active_person",
            "person moving in zone",
            None,
            timeout_sec=8.0,
            frames=_seq_active_person,
        ),
        EvalCase(
            "leaves_zone",
            "person leaves frame",
            "no_visibility",
            timeout_sec=6.0,
            frames=_seq_leaves_zone,
        ),
        EvalCase(
            "on_floor",
            "wide low posture sustained (non-clinical stand-in)",
            "distress_heuristic",
            timeout_sec=6.0,
            frames=_seq_on_floor,
        ),
        EvalCase(
            "pet_motion",
            "small moving blob, no person",
            None,
            timeout_sec=8.0,
            frames=_seq_pet_motion,
        ),
        EvalCase(
            "light_shift",
            "empty room, illumination ramp",
            None,
            timeout_sec=8.0,
            frames=_seq_light_shift,
        ),
        EvalCase(
            "photo_person_still",
            "real photo loop, person still (DNN detector)",
            "no_movement",
            timeout_sec=5.0,
            frames=_seq_photo_person_still,
        ),
        EvalCase(
            "clip_real_fall_1",
            "KU Leuven fall re-enactment (person+pose DNN)",
            "distress_heuristic",
            timeout_sec=180.0,
            frames=lambda: _seq_clip("kul_fall_1.avi", fps=30, sample_hz=5),
        ),
        EvalCase(
            "clip_fall_2_two_tier",
            "KU Leuven gradual bed-collapse, post-fall window (stillness escalation)",
            "no_movement",
            timeout_sec=30.0,
            frames=lambda: _seq_clip("kul_fall_2.avi", fps=30, sample_hz=5, start_sec=75.0),
        ),
        EvalCase(
            "clip_pedestrians_negative",
            "OpenCV vtest pedestrians — no DISTRESS escalation (mild no_visibility when people exit frame is correct)",
            "no_visibility",
            timeout_sec=80.0,
            frames=lambda: _seq_clip("vtest.avi", fps=10, sample_hz=5),
        ),
    ]


def _seq_clip(name: str, fps: float, sample_hz: float, start_sec: float = 0.0):
    """Decode a downloaded clip (clips/, via scripts/download_clips.sh) at a
    reduced sample rate; empty list when the clip is absent (case skipped).
    start_sec skips the pre-roll (e.g. test only the post-fall window)."""
    path = ClipsDir / name
    if not path.exists():
        return []
    import cv2

    step = max(1, int(round(fps / sample_hz)))
    skip = int(start_sec * fps)
    frames = []
    cap = cv2.VideoCapture(str(path))
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i >= skip and (i - skip) % step == 0:
            # timestamp in REAL seconds (source fps), not sample steps —
            # the pose state machine measures transition speed from these
            frames.append((f, (i - skip) / fps))
        i += 1
    cap.release()
    return frames


def summarize(results: list[dict]) -> dict:
    """Compute the grant-proposal metrics from per-case result dicts.

    Skipped cases (missing fixture/clip) are excluded from recall/FPR
    denominators — a case that could not run is not a miss.
    """
    ran = [r for r in results if not r.get("skipped")]
    expect_cue = [r for r in ran if r["expect_cue"] is not None]
    expect_none = [r for r in ran if r["expect_cue"] is None]
    hits = [r for r in expect_cue if r.get("emitted") == r["expect_cue"]]
    false_escalations = [r for r in expect_none if r.get("emitted") is not None]
    ttc = [r["time_to_cue_sec"] for r in hits if r.get("time_to_cue_sec") is not None]
    return {
        "cases": len(results),
        "cases_ran": len(ran),
        "cases_skipped": len(results) - len(ran),
        "cue_recall": round(len(hits) / len(expect_cue), 3) if expect_cue else None,
        "false_escalation_rate": (
            round(len(false_escalations) / len(expect_none), 3) if expect_none else None
        ),
        "mean_time_to_confirm_sec": round(float(np.mean(ttc)), 2) if ttc else None,
        "per_case": [
            {
                "case_id": r["case_id"],
                "expect": r["expect_cue"],
                "emitted": r.get("emitted"),
                "time_to_cue_sec": r.get("time_to_cue_sec"),
                **({"skipped": r["skipped"]} if r.get("skipped") else {}),
            }
            for r in results
        ],
    }


if __name__ == "__main__":
    print(json.dumps(summarize([{"case_id": c.case_id, "expect_cue": c.expect_cue} for c in build_cases()]), indent=2))
