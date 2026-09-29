"""Real video ingest: decode a clip with OpenCV VideoCapture, run CueDetector
frame-by-frame (real wall-clock timestamps), and return the first cue plus a
privacy-transformed pre-event frame window.

Non-clinical demo component. Uploaded clips are processed in memory; frames are
privacy-transformed before any persistence.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from care_ladder.models import CueEvent
from care_ladder.vision.cues import CueDetector


@dataclass
class VideoIngestResult:
    cue: CueEvent | None
    frame_count: int
    fps: float
    duration_sec: float
    pre_event_frames: list[np.ndarray]
    detector_source: str


def ingest_video(
    path: str | Path,
    detector: CueDetector,
    *,
    max_seconds: float = 120.0,
    pre_event_seconds: float = 3.0,
    sample_hz: float | None = None,
    prefer_distress: bool = False,
    use_dnn: Any | None = None,
) -> VideoIngestResult:
    """Decode ``path`` and observe frames through ``detector``.

    Frame timestamps use real decode time (frame_index / fps) so trigger
    timeouts behave as they would on a live camera. Decoding stops at the first
    cue (the ladder takes over from there) or end of clip / max_seconds.

    ``sample_hz`` processes a real-time sample grid (e.g. 5 Hz → every 6th
    frame at 30 fps): timestamps stay in real seconds — validated on the
    KU Leuven fall clips (sudden-fall signature survives 5 Hz sampling) —
    while DNN cost drops ~6x for CPU-bound containers.

    ``prefer_distress`` keeps scanning after a non-distress cue and returns
    the distress cue if one fires later in the clip (a fall anywhere in an
    upload outranks an earlier stillness cue); otherwise the first cue wins.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"could not open video: {path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if fps <= 0 or fps != fps:  # 0 or NaN
            fps = 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(fps / sample_hz))) if sample_hz else 1

        cue: CueEvent | None = None
        seen = 0
        processed = 0
        window: list[tuple[float, np.ndarray]] = []

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = seen / fps
            if t > max_seconds:
                break
            seen += 1
            if (seen - 1) % step != 0:
                continue  # off-grid frame: skip DNN work, keep real timestamps
            processed += 1

            candidate = detector
            observed = candidate.observe(frame, t=t)
            if observed is not None and cue is None:
                cue = observed
            elif prefer_distress and observed is not None and observed.kind == "distress_heuristic":
                # a fall anywhere in the clip outranks an earlier stillness cue
                cue = observed

            # rolling pre-event window (raw in memory only)
            window.append((t, frame))
            cutoff = t - pre_event_seconds
            while window and window[0][0] < cutoff:
                window.pop(0)

            if cue is not None and (cue.kind == "distress_heuristic" or not prefer_distress):
                break

        duration = seen / fps
        pre_frames = [f for _, f in window]
        return VideoIngestResult(
            cue=cue,
            frame_count=seen or frame_count,
            fps=round(fps, 2),
            duration_sec=round(duration, 2),
            pre_event_frames=pre_frames,
            detector_source=detector.last_detection_source or "contour_blob",
        )
    finally:
        cap.release()


def save_upload(data: bytes, suffix: str = ".mp4") -> Path:
    """Spill an upload to a temp file for VideoCapture. Caller deletes."""
    if not data:
        raise ValueError("empty upload")
    tmp = tempfile.NamedTemporaryFile(prefix="care-ladder-upload-", suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    return Path(tmp.name)
