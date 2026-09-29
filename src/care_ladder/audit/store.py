"""In-memory incident audit store (demo / local; DynamoDB later)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from care_ladder.models import Incident

# Calm TV pill: stay visible through a sim burst, then auto-clear.
_MCP_DRIVE_TTL_SEC = 12.0


class AuditStore:
    """Process-local store of incidents keyed by id."""

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._mcp_driving_until: datetime | None = None
        self._mcp_driving_hh: str | None = None
        self._mcp_driving_iid: str | None = None

    def save(self, incident: Incident) -> Incident:
        self._incidents[incident.id] = incident
        return incident

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def list_incidents(self) -> list[Incident]:
        return list(self._incidents.values())

    def mark_mcp_driving(
        self,
        household_id: str,
        incident_id: str,
        *,
        ttl_sec: float = _MCP_DRIVE_TTL_SEC,
    ) -> None:
        """Stamp an MCP-driven window. ttl_sec=0 clears immediately (tests)."""
        now = datetime.now(timezone.utc)
        self._mcp_driving_until = now + timedelta(seconds=ttl_sec)
        self._mcp_driving_hh = household_id
        self._mcp_driving_iid = incident_id

    def mcp_agent_status(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        until = self._mcp_driving_until
        if until is None or until <= now:
            return {"active": False, "household_id": None, "incident_id": None}
        return {
            "active": True,
            "household_id": self._mcp_driving_hh,
            "incident_id": self._mcp_driving_iid,
        }
