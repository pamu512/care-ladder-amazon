"""OpenCV cue detection: stillness, zone visibility, non-clinical distress heuristic."""

from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from typing import TYPE_CHECKING

from care_ladder.learning.profile import effective_no_movement_timeout_sec
from care_ladder.models import CarePlan, CueEvent

if TYPE_CHECKING:
    from care_ladder.learning.profile import RoutineProfile
from care_ladder.vision.pose_heuristics import PoseHeuristics, torso_metrics
from care_ladder.vision.tracker import PersonTracker

Point = tuple[float, float]


class CueDetector:
    """Detect Care Ladder cues from a stream of BGR frames.

    Uses frame differencing for motion, contour centroids vs a zone polygon
    (`cv2.pointPolygonTest`) for presence, and a simple aspect-ratio / y-position
    heuristic for a non-clinical on-floor stand-in.

    After emitting a cue, internal timers / presence latch clear so the same cue
    does not spam every subsequent frame.
    """

    def __init__(
        self,
        no_movement_timeout_sec: float,
        zone: Sequence[Point],
        *,
        motion_mean_threshold: float = 2.0,
        min_blob_area: float = 100.0,
        distress_sustain_sec: float = 2.0,
        distress_aspect_min: float = 2.0,
        distress_y_ratio_min: float = 0.65,
        binary_threshold: int = 40,
        enable_no_movement: bool = True,
        enable_no_visibility: bool = True,
        enable_distress_heuristic: bool = True,
        person_detector: Any | None = None,
        motion_source: str = "frame_diff",
        tracking_enabled: bool = True,
        pose_model: Any | None = None,
        fall_classifier: Any | None = None,
        fall_score_threshold: float = 0.65,
    ) -> None:
        self.no_movement_timeout_sec = float(no_movement_timeout_sec)
        self.zone = np.asarray(zone, dtype=np.float32)
        self.motion_mean_threshold = motion_mean_threshold
        self.min_blob_area = min_blob_area
        self.distress_sustain_sec = float(distress_sustain_sec)
        self.distress_aspect_min = distress_aspect_min
        self.distress_y_ratio_min = distress_y_ratio_min
        self.binary_threshold = binary_threshold
        self.enable_no_movement = enable_no_movement
        self.enable_no_visibility = enable_no_visibility
        self.enable_distress_heuristic = enable_distress_heuristic
        self.person_detector = person_detector
        if motion_source not in ("frame_diff", "mog2"):
            raise ValueError(f"unknown motion_source {motion_source!r}")
        self.motion_source = motion_source
        self._mog2 = cv2.createBackgroundSubtractorMOG2(
            history=60, varThreshold=32.0, detectShadows=False
        )

        self._prev_gray: np.ndarray | None = None
        self._seen_in_zone = False
        self._presence_frames = 0
        self._still_since: float | None = None
        self._distress_since: float | None = None
        self.last_detection_source: str | None = None
        self._tracker: PersonTracker | None = None
        self.tracking_enabled = tracking_enabled
        self.pose_model = pose_model
        self.pose_state = PoseHeuristics() if pose_model is not None else None
        self.fall_classifier = fall_classifier
        self.fall_score_threshold = float(fall_score_threshold)
        self._trained_fall_since: float | None = None
        self.last_fall_error: str | None = None
        self.last_fall_score: float | None = None

    @classmethod
    def from_plan(
        cls,
        plan: CarePlan,
        zone_id: str | None = None,
        profile: "RoutineProfile | None" = None,
    ) -> CueDetector:
        """Build a detector from ``CarePlan.triggers`` and a named (or first) zone.

        ``profile`` (spec 2026-09-27 section 6): when learning is enabled the
        detector arms at the ADAPTIVE stillness timeout, not the plan timeout -
        the badge number and the actual arming threshold must be the same
        number. ``None`` keeps the plan timeout (learning off / exact-timeout
        tests).
        """
        if not plan.zones:
            raise ValueError("care plan has no zones for CueDetector.from_plan")
        zone_model = None
        if zone_id is not None:
            for z in plan.zones:
                if z.id == zone_id:
                    zone_model = z
                    break
            if zone_model is None:
                raise ValueError(f"zone_id {zone_id!r} not found in care plan")
        else:
            zone_model = plan.zones[0]

        polygon = [(float(p[0]), float(p[1])) for p in zone_model.polygon]
        timeout = float(plan.triggers.no_movement.timeout_sec)
        if profile is not None:
            learning_cfg = plan.learning
            if learning_cfg is None or learning_cfg.enabled:
                timeout = float(
                    effective_no_movement_timeout_sec(plan, profile)
                )
        from care_ladder.vision.sagemaker_cue import resolve_fall_classifier

        det = cls(
            no_movement_timeout_sec=timeout,
            zone=polygon,
            enable_no_movement=bool(plan.triggers.no_movement.enabled),
            enable_no_visibility=bool(plan.triggers.no_visibility.enabled),
            enable_distress_heuristic=bool(plan.triggers.distress_heuristic.enabled),
            fall_classifier=resolve_fall_classifier(),
        )
        return det

    def observe(self, frame: np.ndarray, t: float) -> CueEvent | None:
        gray = (
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if frame.ndim == 3
            else frame
        )
        h, w = gray.shape[:2]

        # Person localization: DNN person detector when available, else contour blob.
        if self.person_detector is not None:
            boxes = self._detect_people_dnn(frame)
            self.last_detection_source = "dnn_person_detector"
            blob = boxes[0] if boxes else None
        else:
            blob = self._largest_blob(gray)
            self.last_detection_source = "contour_blob"
        # Track all detections (DNN: every person box; contour: the best blob).
        tracking = None
        if self.tracking_enabled:
            if self._tracker is None:
                self._tracker = PersonTracker(w, h)
            if self.person_detector is not None:
                dets = self._detect_people_dnn(frame)
                for d in dets:
                    d.setdefault("height_ratio", d.get("h", 0.0) / float(h))
            else:
                dets = [dict(blob, height_ratio=blob["h"] / float(h))] if blob else []
            tracking = self._tracker.observe(dets, t)
            self.last_tracking = tracking

        # Pose-based distress: when DNN person + pose models are available,
        # run keypoint geometry through the fall-signature state machine.
        pose_fire = None
        if self.pose_model is not None and self.person_detector is not None:
            if self.pose_state is None:
                self.pose_state = PoseHeuristics()
            try:
                people = self._detect_people_dnn(frame)
                if people:
                    res = self.pose_model.infer(frame, people[0]["_row"])
                    if res is not None:
                        _bbox, landmarks, *_ = res
                        metrics = torso_metrics(np.asarray(landmarks), h)
                        pose_fire = self.pose_state.observe(metrics, t)
                        self.last_pose_metrics = metrics
            except Exception:
                self.last_pose_metrics = None

        in_zone = bool(blob and self._point_in_zone(blob["cx"], blob["cy"]))

        # Motion: MOG2 foreground ratio (robust to global illumination drift) or
        # plain frame differencing.
        motion = 0.0
        if self.motion_source == "mog2":
            fg = self._mog2.apply(frame)
            motion = float(np.count_nonzero(fg)) / float(fg.size) * 255.0
        elif self._prev_gray is not None:
            diff = cv2.absdiff(gray, self._prev_gray)
            motion = float(np.mean(diff))
        self._prev_gray = gray.copy()

        if in_zone:
            self._presence_frames += 1
            # Require sustained presence before latching: single-frame noise
            # blobs (highlights, sensor noise) must not arm no_visibility.
            if not self._seen_in_zone and self._presence_frames >= 2:
                self._seen_in_zone = True
            if self._seen_in_zone:
                if self._still_since is None or motion > self.motion_mean_threshold:
                    self._still_since = t
                if self._is_distress_pose(blob, h):
                    if self._distress_since is None:
                        self._distress_since = t
                else:
                    self._distress_since = None
        else:
            self._presence_frames = 0
            self._still_since = None
            self._distress_since = None
            self._trained_fall_since = None
            if self._seen_in_zone and self.enable_no_visibility:
                # Latch: require re-entry before another no_visibility.
                self._seen_in_zone = False
                detail = {
                    "reason": "blob_left_zone_or_absent",
                    "in_zone": False,
                    "motion_mean": motion,
                }
                if getattr(self, "last_tracking", None):
                    tr = self.last_tracking
                    detail["person_count"] = tr["person_count"]
                    detail["track_events"] = tr["events"]
                return CueEvent(kind="no_visibility", confidence=0.85, detail=detail)

        # Pose-based fall signature takes priority over the shape heuristic.
        if (
            pose_fire is not None
            and self.enable_distress_heuristic
            and in_zone
        ):
            detail = dict(pose_fire)
            detail["source"] = "pose_heuristics"
            if getattr(self, "last_tracking", None):
                tr = self.last_tracking
                detail["person_count"] = tr["person_count"]
                detail["tracks"] = tr["tracks"]
            self._distress_since = None  # suppress the shape fallback
            return CueEvent(kind="distress_heuristic", confidence=0.85, detail=detail)

        if (
            self.fall_classifier is not None
            and self.enable_distress_heuristic
            and in_zone
            and blob is not None
        ):
            box = (
                blob["cx"] - blob["w"] / 2.0,
                blob["cy"] - blob["h"] / 2.0,
                blob["cx"] + blob["w"] / 2.0,
                blob["cy"] + blob["h"] / 2.0,
            )
            try:
                score = float(self.fall_classifier.predict_proba(frame, box))
            except Exception as exc:
                # A failed score is not 0. Thresholds at or below 0 would
                # otherwise turn an outage into a distress cue.
                self.last_fall_error = f"{type(exc).__name__}: {exc}"
                self.last_fall_score = None
                self._trained_fall_since = None
            else:
                self.last_fall_error = None
                self.last_fall_score = score
                if score >= self.fall_score_threshold:
                    if self._trained_fall_since is None:
                        self._trained_fall_since = t
                    if (t - self._trained_fall_since) >= self.distress_sustain_sec:
                        self._trained_fall_since = None
                        from care_ladder.vision.sagemaker_cue import SageMakerCueScorer

                        sagemaker = isinstance(self.fall_classifier, SageMakerCueScorer)
                        detail = {
                            "non_clinical": True,
                            "note": (
                                "SageMaker fall-frame score on a blurred or silhouette crop; not a medical diagnosis"
                                if sagemaker
                                else "trained fall-frame classifier; not a medical diagnosis"
                            ),
                            "source": (
                                "sagemaker_fall_classifier"
                                if sagemaker
                                else "trained_fall_classifier"
                            ),
                            "score": round(score, 4),
                        }
                        if sagemaker:
                            detail["privacy"] = getattr(
                                self.fall_classifier, "last_privacy", None
                            )
                            detail["artifact"] = "fall_classifier.npz"
                            detail["endpoint"] = getattr(
                                self.fall_classifier, "endpoint_name", None
                            )
                        if getattr(self, "last_tracking", None):
                            tr = self.last_tracking
                            detail["person_count"] = tr["person_count"]
                            detail["tracks"] = tr["tracks"]
                        return CueEvent(
                            kind="distress_heuristic",
                            confidence=min(0.85, 0.5 + 0.4 * score),
                            detail=detail,
                        )
                else:
                    self._trained_fall_since = None

        if (
            self.enable_distress_heuristic
            and in_zone
            and self._distress_since is not None
            and (t - self._distress_since) >= self.distress_sustain_sec
        ):
            assert blob is not None
            sustain = t - self._distress_since
            # Clear so condition must re-accumulate (no per-frame spam).
            self._distress_since = None
            detail = {
                "non_clinical": True,
                "note": "coarse aspect/y heuristic only; not a medical diagnosis",
                "aspect_ratio": blob["aspect"],
                "y_ratio": blob["cy"] / float(h),
                "sustain_sec": sustain,
                "source": "shape_heuristic",
            }
            if getattr(self, "last_tracking", None):
                tr = self.last_tracking
                detail["person_count"] = tr["person_count"]
                detail["tracks"] = tr["tracks"]
            return CueEvent(kind="distress_heuristic", confidence=0.7, detail=detail)

        if (
            self.enable_no_movement
            and in_zone
            and self._still_since is not None
            and (t - self._still_since) >= self.no_movement_timeout_sec
        ):
            still_sec = t - self._still_since
            # Restart stillness clock so the same still pose does not re-fire next frame.
            self._still_since = t
            detail = {
                "still_sec": still_sec,
                "motion_mean": motion,
                "timeout_sec": self.no_movement_timeout_sec,
            }
            if getattr(self, "last_tracking", None):
                tr = self.last_tracking
                detail["person_count"] = tr["person_count"]
                detail["tracks"] = tr["tracks"]
                detail["track_events"] = tr["events"]
            return CueEvent(kind="no_movement", confidence=0.8, detail=detail)

        return None

    def _point_in_zone(self, x: float, y: float) -> bool:
        # >= 0 means inside or on edge
        return cv2.pointPolygonTest(self.zone, (float(x), float(y)), False) >= 0.0

    def _detect_people_dnn(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Run the DNN person detector and normalize boxes to blob-dict shape."""
        rows = self.person_detector.infer(frame)
        out: list[dict[str, Any]] = []
        for r in rows:
            x1, y1, x2, y2 = (float(v) for v in r[:4])
            bw, bh = x2 - x1, y2 - y1
            area = bw * bh
            if area < self.min_blob_area:
                continue
            out.append(
                {
                    "cx": (x1 + x2) / 2.0,
                    "cy": (y1 + y2) / 2.0,
                    "w": float(bw),
                    "h": float(bh),
                    "area": float(area),
                    "aspect": (bw / float(bh)) if bh > 0 else 0.0,
                    "score": float(r[12]),
                    "_row": r,
                }
            )
        return sorted(out, key=lambda b: -b["score"])

    def _largest_blob(self, gray: np.ndarray) -> dict[str, Any] | None:
        # Otsu picks the threshold from the frame histogram, so detection works
        # on realistic multi-tone scenes, not only dark-bg/bright-person demos.
        _, mask = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        frame_area = float(gray.shape[0]) * float(gray.shape[1])
        # Reject background slabs: a contour covering a large fraction of the
        # frame is the scene (floor/wall boundary), not a person.
        candidates = [c for c in contours if cv2.contourArea(c) < 0.2 * frame_area]
        if not candidates:
            return None
        contour = max(candidates, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < self.min_blob_area:
            return None
        x, y, bw, bh = cv2.boundingRect(contour)
        m = cv2.moments(contour)
        if m["m00"] == 0:
            cx = x + bw / 2.0
            cy = y + bh / 2.0
        else:
            cx = float(m["m10"] / m["m00"])
            cy = float(m["m01"] / m["m00"])
        aspect = (bw / float(bh)) if bh > 0 else 0.0
        return {
            "cx": cx,
            "cy": cy,
            "w": float(bw),
            "h": float(bh),
            "area": area,
            "aspect": aspect,
        }

    def _is_distress_pose(self, blob: dict[str, Any] | None, frame_h: int) -> bool:
        if not blob or frame_h <= 0:
            return False
        y_ratio = blob["cy"] / float(frame_h)
        return (
            blob["aspect"] >= self.distress_aspect_min
            and y_ratio >= self.distress_y_ratio_min
        )
