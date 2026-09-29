"""Live camera loop: cv2.VideoCapture (device index or RTSP/HTTP URL) feeding
the same CueDetector used by fixtures/uploads, auto-creating incidents.

Guardrails (hackathon demo):
- demo care plan only; hard time cap (default 10 min) enforced by the loop;
- frames are privacy-transformed before anything is persisted (same contract
  as fixtures/uploads);
- one camera session per process; stop clears it cleanly;
- designed to run in a worker thread; the API exposes start/stop/status.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from care_ladder.models import CueEvent


class CameraSession:
    """Runs CueDetector over a VideoCapture stream until stopped or capped."""

    def __init__(self, *, source: Any, detector, on_incident, max_seconds: float = 600.0,
                 sample_hz: float = 5.0, label: str = "live_camera") -> None:
        self.source = source
        self.detector = detector
        self.on_incident = on_incident  # async callable(incident) or None
        self.max_seconds = max_seconds
        self.sample_hz = sample_hz
        self.label = label
        self.started_at = time.monotonic()
        self.frames = 0
        self.last_cue: dict[str, Any] | None = None
        self.error: str | None = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self.thread.is_alive() and not self._stop.is_set()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "label": self.label,
            "elapsed_sec": round(time.monotonic() - self.started_at, 1),
            "max_seconds": self.max_seconds,
            "frames": self.frames,
            "last_cue": self.last_cue,
            "error": self.error,
        }

    # --- loop ------------------------------------------------------------
    def _run(self) -> None:  # pragma: no cover - exercised via stub tests
        import cv2

        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            self.error = f"could not open camera source {self.source!r}"
            return
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if fps <= 0 or fps != fps:
            fps = 30.0
        step = max(1, int(round(fps / self.sample_hz)))
        try:
            i = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    self.error = "stream ended or could not read frame"
                    break
                t = i / fps
                if t > self.max_seconds:
                    break
                if i % step == 0:
                    cue = self.detector.observe(frame, t=t)
                    self.frames += 1
                    if cue is not None:
                        self.last_cue = {
                            "kind": cue.kind,
                            "confidence": cue.confidence,
                            "detail": cue.detail,
                            "t": round(t, 2),
                        }
                        self._dispatch(cue, t)
                        break  # first cue ends the session; ladder takes over
                i += 1
        finally:
            cap.release()

    def _dispatch(self, cue: CueEvent, t: float) -> None:
        if self.on_incident is None:
            return
        import asyncio

        try:
            coro = self.on_incident(cue, t)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(coro)
            else:  # already inside a loop (shouldn't happen from a thread)
                asyncio.ensure_future(coro)
        except Exception as exc:  # pragma: no cover - env-dependent
            self.error = f"incident dispatch failed: {exc}"


# one session per process (demo guardrail)
_ACTIVE: CameraSession | None = None
_ACTIVE_LOCK = threading.Lock()


def start_session(**kwargs) -> CameraSession:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None and _ACTIVE.running:
            raise RuntimeError("a camera session is already running")
        _ACTIVE = CameraSession(**kwargs)
        _ACTIVE.start()
        return _ACTIVE


def active_session() -> CameraSession | None:
    with _ACTIVE_LOCK:
        return _ACTIVE


def stop_session() -> bool:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is None:
            return False
        _ACTIVE.stop()
        _ACTIVE = None
        return True
