"""Person tracking: count, enter/leave events, and coarse shape signatures.

Privacy-preserving by construction: tracks are described ONLY by geometry
(height ratio, aspect, position) — no color histograms, no faces, no identity
claims. Two people of similar build may be conflated; that limitation is
documented in docs/failure-modes.md.

Non-clinical demo component.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Track:
    id: int
    height_ratio: float  # box height / frame height
    aspect: float  # box width / height
    cx: float
    cy: float
    first_seen: float
    last_seen: float
    frames: int = 1
    left: bool = False

    def signature(self) -> dict[str, Any]:
        """Coarse shape descriptor — distinguishes tall/short, slim/wide."""
        return {
            "track_id": self.id,
            "height_ratio": round(self.height_ratio, 3),
            "aspect": round(self.aspect, 2),
        }


@dataclass
class TrackerState:
    tracks: dict[int, Track] = field(default_factory=dict)
    next_id: int = 1
    events: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "person_count": sum(1 for t in self.tracks.values() if not t.left),
            "tracks": [
                {**t.signature(), "frames": t.frames, "last_seen": t.last_seen}
                for t in sorted(self.tracks.values(), key=lambda t: t.id)
                if not t.left
            ],
            "events": list(self.events[-8:]),
        }


class PersonTracker:
    """Greedy centroid+height matching across frames.

    A detection matches an active track when centroid distance ≤ gate AND the
    height-ratio delta ≤ height_gate. Unmatched detections spawn tracks
    (``enter`` event); tracks unmatched for ``max_missed`` consecutive frames
    are retired (``leave`` event).
    """

    def __init__(
        self,
        frame_w: int,
        frame_h: int,
        *,
        dist_gate_ratio: float = 0.15,
        height_gate: float = 0.18,
        max_missed: int = 3,
    ) -> None:
        self.gate = max(dist_gate_ratio * max(frame_w, frame_h), 8.0)
        self.height_gate = height_gate
        self.max_missed = max_missed
        self.state = TrackerState()
        self._missed: dict[int, int] = {}

    def observe(
        self, detections: list[dict[str, Any]], t: float
    ) -> dict[str, Any]:
        st = self.state
        active = [tr for tr in st.tracks.values() if not tr.left]

        # -- match: greedy best-first on (distance, height delta) -------------
        candidates: list[tuple[float, int, int]] = []  # (score, track_idx, det_idx)
        for ti, tr in enumerate(active):
            for di, d in enumerate(detections):
                dist = float(np.hypot(d["cx"] - tr.cx, d["cy"] - tr.cy))
                dh = abs(float(d.get("height_ratio", d.get("h", 0.0))) - tr.height_ratio)
                if dist <= self.gate and dh <= self.height_gate:
                    candidates.append((dist + dh, ti, di))
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for _, ti, di in sorted(candidates):
            if ti in matched_tracks or di in matched_dets:
                continue
            tr, d = active[ti], detections[di]
            tr.cx, tr.cy = float(d["cx"]), float(d["cy"])
            tr.height_ratio = float(d.get("height_ratio", d.get("h", tr.height_ratio)))
            tr.aspect = float(d.get("aspect", tr.aspect))
            tr.last_seen = t
            tr.frames += 1
            matched_tracks.add(ti)
            matched_dets.add(di)

        # -- unmatched detections → enter --------------------------------------
        for di, d in enumerate(detections):
            if di in matched_dets:
                continue
            tr = Track(
                id=st.next_id,
                height_ratio=float(d.get("height_ratio", d.get("h", 0.0))),
                aspect=float(d.get("aspect", 0.0)),
                cx=float(d["cx"]),
                cy=float(d["cy"]),
                first_seen=t,
                last_seen=t,
            )
            st.next_id += 1
            st.tracks[tr.id] = tr
            st.events.append({"type": "enter", "t": t, **tr.signature()})

        # -- unmatched tracks: miss counting; retire after max_missed ---------
        for ti, tr in enumerate(active):
            if ti in matched_tracks or tr.left:
                continue
            self._missed.setdefault(tr.id, 0)
            self._missed[tr.id] += 1
            if self._missed[tr.id] > self.max_missed:
                tr.left = True
                self._missed.pop(tr.id, None)
                st.events.append({"type": "leave", "t": t, **tr.signature()})
        for ti in matched_tracks:
            self._missed.pop(active[ti].id, None)

        return st.snapshot()
