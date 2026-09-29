"""DynamoDB-backed audit store (production path) alongside the in-memory store.

Env-gated: set CARE_LADDER_STORE=dynamodb (plus AWS region/credentials) and the
API persists incidents across restarts. Local/tests default to in-memory.

Design:
- Table ``care-ladder-incidents`` (created on demand), PK ``incident_id`` (S).
- Item = full Incident JSON + serialized privacy-transformed frames (PNG bytes,
  base64) so the caregiver clip viewer works from any task instance.
- Frames are ONLY the blur/silhouette copies — the same guarantee as memory.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import cv2
import numpy as np

from care_ladder.audit.store import AuditStore
from care_ladder.models import Incident

TABLE_NAME = os.environ.get("CARE_LADDER_DDB_TABLE", "care-ladder-incidents")
_FRAMES_ATTR = "_frames_png_b64"


def _to_native(value: Any) -> Any:
    """boto3 resource clients reject floats; convert to Decimal recursively."""
    from decimal import Decimal

    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_to_native(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_native(v) for k, v in value.items()}
    return value


def _from_native(value: Any) -> Any:
    """Decimal → float/int for pydantic round-trips."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f == int(f) and abs(f) < 1e15 else f
    if isinstance(value, list):
        return [_from_native(v) for v in value]
    if isinstance(value, dict):
        return {k: _from_native(v) for k, v in value.items()}
    return value


def _frames_to_b64(frames: list[Any]) -> list[str]:
    out = []
    for f in frames:
        ok, buf = cv2.imencode(".png", f)
        if ok:
            out.append(base64.b64encode(buf.tobytes()).decode("ascii"))
    return out


def _b64_to_frames(items: list[str]) -> list[np.ndarray]:
    frames = []
    for s in items:
        arr = np.frombuffer(base64.b64decode(s), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is not None:
            frames.append(img)
    return frames


class DynamoAuditStore(AuditStore):
    """AuditStore with DynamoDB persistence; falls back to memory semantics."""

    def __init__(self, table_name: str = TABLE_NAME, client: Any | None = None) -> None:
        super().__init__()
        if client is None:
            import boto3

            client = boto3.resource("dynamodb").meta.client
        self._client: Any = client
        self._table = table_name
        self._ensure_table()

    def _ensure_table(self) -> None:
        existing = self._client.list_tables()["TableNames"]
        if self._table in existing:
            return
        self._client.create_table(
            TableName=self._table,
            KeySchema=[{"AttributeName": "incident_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "incident_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = self._client.get_waiter("table_exists")
        waiter.wait(TableName=self._table, WaiterConfig={"Delay": 2, "MaxAttempts": 15})

    # -- store API ---------------------------------------------------------

    def save(self, incident: Incident) -> Incident:
        super().save(incident)  # keep in-memory hot copy for this process
        item = json.loads(incident.model_dump_json())
        frames = incident.__dict__.get("_private_pre_event_frames") or []
        if frames:
            item[_FRAMES_ATTR] = _frames_to_b64(frames)
        item["saved_at"] = int(time.time())
        # boto3 resource-style clients expect NATIVE types (str/int/list/dict),
        # not low-level AttributeValue maps — the manual marshaller wrapped the
        # key as {"S": ...} which boto3 re-wrapped as a Map, breaking the schema.
        ddb_item = _to_native(dict(item))
        ddb_item["incident_id"] = incident.id
        try:
            self._client.put_item(TableName=self._table, Item=ddb_item)
        except Exception as exc:  # pragma: no cover - env-dependent
            # Persistence is best-effort: the incident stays in memory and the
            # API keeps working; log loudly so the gap is visible.
            print(f"WARNING: DynamoDB put failed for {incident.id}: {exc}")
        return incident

    def get(self, incident_id: str) -> Incident | None:
        local = super().get(incident_id)
        if local is not None:
            return local
        resp = self._client.get_item(TableName=self._table, Key={"incident_id": incident_id})
        item = resp.get("Item")
        if not item:
            return None
        data = _from_native(dict(item))
        data.pop("incident_id", None)
        frames_b64 = data.pop(_FRAMES_ATTR, None)
        incident = Incident.model_validate(data)
        if frames_b64:
            incident.__dict__["_private_pre_event_frames"] = _b64_to_frames(frames_b64)
        super().save(incident)  # cache
        return incident

    def list_incidents(self) -> list[Incident]:
        local = super().list_incidents()
        if local:
            return local
        resp = self._client.scan(TableName=self._table, Limit=100)
        out = []
        for item in resp.get("Items", []):
            data = _from_native(dict(item))
            data.pop("incident_id", None)
            data.pop(_FRAMES_ATTR, None)
            out.append(Incident.model_validate(data))
        return sorted(out, key=lambda i: i.id)


# -- DynamoDB low-level (AttributeValue) marshalling, boto3-free -----------
