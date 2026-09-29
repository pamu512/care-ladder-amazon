"""Cloud sinks: S3 clip persistence + EventBridge cue emission.

Both are env-gated and silently no-op when unconfigured so local dev/tests stay
hermetic. Privacy rule: ONLY silhouette/blur-transformed frames ever reach S3 —
enforced by requiring the transform tag on upload.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("care_ladder.cloud")

S3_BUCKET = os.environ.get("CLIP_BUCKET", "")
EVENT_BUS = os.environ.get("EVENT_BUS_NAME", "")


class CloudSinks:
    """Optional S3 + EventBridge writers used by the API after an incident."""

    def __init__(self, bucket: str = S3_BUCKET, bus: str = EVENT_BUS) -> None:
        self.bucket = bucket
        self.bus = bus
        self._s3 = None
        self._events = None
        if bucket:
            try:
                import boto3

                self._s3 = boto3.client("s3")
            except Exception as exc:  # pragma: no cover
                logger.warning("S3 unavailable: %s", exc)
        if bus:
            try:
                import boto3

                self._events = boto3.client("events")
            except Exception as exc:  # pragma: no cover
                logger.warning("EventBridge unavailable: %s", exc)

    @property
    def enabled(self) -> bool:
        return bool(self._s3 or self._events)

    def upload_clip_frames(
        self, incident_id: str, frames: list[np.ndarray], privacy: str | None
    ) -> list[str]:
        """Upload privacy-transformed frames as PNGs; return S3 URIs.

        Refuses (returns []) when the privacy tag is missing — the no-raw-bytes
        rule is enforced here, not just at attach time.
        """
        if not self._s3 or not frames:
            return []
        if privacy not in {"blur", "silhouette"}:
            logger.warning("refusing S3 upload without privacy transform (got %r)", privacy)
            return []
        keys = []
        for i, frame in enumerate(frames):
            ok, buf = cv2.imencode(".png", frame)
            if not ok:
                continue
            key = f"incidents/{incident_id}/pre_event_{i:03d}.png"
            self._s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=buf.tobytes(),
                ContentType="image/png",
                Metadata={"incident-id": incident_id, "privacy": privacy},
            )
            keys.append(f"s3://{self.bucket}/{key}")
        return keys

    def emit_cue(self, incident: Any, clip_uris: list[str] | None = None) -> bool:
        """PutEvents a CareLadderCue event for the incident's cue."""
        if not self._events:
            return False
        detail = {
            "incident_id": incident.id,
            "household_id": incident.household_id,
            "kind": incident.cue.kind,
            "confidence": incident.cue.confidence,
            "status": incident.status,
        }
        if clip_uris:
            detail["clip_s3_uris"] = clip_uris
        try:
            self._events.put_events(
                Entries=[
                    {
                        "Source": "care.ladder",
                        "DetailType": "CareLadderCue",
                        "Detail": json.dumps(detail),
                        "EventBusName": self.bus,
                    }
                ]
            )
            return True
        except Exception as exc:  # pragma: no cover - env-dependent
            logger.warning("put_events failed: %s", exc)
            return False
