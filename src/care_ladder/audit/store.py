"""In-memory incident audit store (demo / local; DynamoDB later)."""

from __future__ import annotations

from care_ladder.models import Incident


class AuditStore:
    """Process-local store of incidents keyed by id."""

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}

    def save(self, incident: Incident) -> Incident:
        self._incidents[incident.id] = incident
        return incident

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def list_incidents(self) -> list[Incident]:
        return list(self._incidents.values())
