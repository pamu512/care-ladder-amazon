from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Contact(BaseModel):
    display_name: str
    phone_e164: str | None = None


class RosterEntry(BaseModel):
    """One slot on the family escalation ladder (any length)."""

    name: str
    relationship: str = ""
    local_responder: bool = False
    phone_e164: str | None = None


class NoMovementTrigger(BaseModel):
    enabled: bool = True
    timeout_sec: int


class SimpleTrigger(BaseModel):
    enabled: bool = True


class Triggers(BaseModel):
    no_movement: NoMovementTrigger
    no_visibility: SimpleTrigger = Field(default_factory=SimpleTrigger)
    distress_heuristic: SimpleTrigger = Field(default_factory=SimpleTrigger)


# Interface alias used in the plan
TriggerConfig = Triggers


class Zone(BaseModel):
    id: str
    polygon: list[list[float]]


class QuietHours(BaseModel):
    start: str
    end: str
    policy: str


class Rung(BaseModel):
    id: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)


class LearningConfigModel(BaseModel):
    """Optional care-plan ``learning:`` block (spec 2026-09-27). Missing = defaults."""

    enabled: bool = True
    settled_after_days: int = 10
    min_no_movement_timeout_sec: int = 120
    rapid_timeout_factor: float = 0.4


class CarePlan(BaseModel):
    household_id: str
    caregiver: Contact
    monitored: Contact
    zones: list[Zone] = Field(default_factory=list)
    triggers: Triggers
    rungs: list[Rung]
    quiet_hours: QuietHours | None = None
    secondary: Contact | None = None
    learning: LearningConfigModel | None = None
    roster: list[RosterEntry] = Field(default_factory=list)


class CueEvent(BaseModel):
    kind: Literal["no_movement", "no_visibility", "distress_heuristic"]
    confidence: float
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """One step in an incident timeline (cue → rung tools → resolve/jump)."""

    tool: str
    cue_kind: str | None = None
    rung_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))


IncidentStatus = Literal["open", "resolved", "exhausted", "suppressed"]
PrivacyMode = Literal["blur", "silhouette"]


class Incident(BaseModel):
    """Care-ladder run for one cue, with ordered audit events."""

    id: str
    household_id: str
    cue: CueEvent
    events: list[AuditEvent] = Field(default_factory=list)
    status: IncidentStatus = "open"
    created_at: datetime | None = None
    pre_event_frame_count: int = 0
    privacy: PrivacyMode | None = None
    # Caregiver acknowledgement (human-in-the-loop): set when a caregiver
    # confirms they have seen the incident. Acks never change status; they
    # gate re-dial cooldowns in the orchestrator.
    acked_by: str | None = None
    acked_at: datetime | None = None
