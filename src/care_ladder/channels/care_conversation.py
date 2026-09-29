"""Channel-agnostic care conversation FSM (Alexa-session beats, no chat adapters).

States: idle → speaker_window → family_paged → pressure → calling_1 → calling_2 → closed
Resident clear_ok closes from speaker_window without paging family.
ANY caregiver ack stops escalation; outcome closes with documentation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar, Literal

from care_ladder.models import AuditEvent

CareState = Literal[
    "idle",
    "speaker_window",
    "family_paged",
    "pressure",
    "calling_1",
    "calling_2",
    "closed",
]

ACK_ACTIONS = ("im_on_it", "call_mom_now", "pass_to_next")

INFORM_ACTIONS: tuple[dict[str, str], ...] = (
    {"id": "im_on_it", "label": "I'm on it - call her myself"},
    {"id": "call_mom_now", "label": "Call Mom now"},
    {"id": "pass_to_next", "label": "Can't take it - go to {next}"},
)

_OPEN_STATES = frozenset(
    {"speaker_window", "family_paged", "pressure", "calling_1", "calling_2"}
)
_PAGEABLE = frozenset({"family_paged", "pressure", "calling_1", "calling_2"})


def inform_card(
    blurred_frame_ref: str,
    cue_text: str,
    countdown_sec: int,
    actions: list[dict[str, str]] | None = None,
    *,
    next_contact: str = "Secondary contact",
) -> dict[str, Any]:
    """Blurred still + countdown + three caregiver actions (no em dashes)."""
    if actions is None:
        acts = [
            {"id": a["id"], "label": a["label"].format(next=next_contact)}
            for a in INFORM_ACTIONS
        ]
    else:
        acts = list(actions[:3])
    return {
        "blurred_frame_ref": blurred_frame_ref,
        "cue_text": cue_text,
        "countdown_sec": int(countdown_sec),
        "actions": acts,
    }


class CareConversation:
    """One active conversation per household; new cues join an open thread."""

    _by_household: ClassVar[dict[str, CareConversation]] = {}

    def __init__(
        self,
        household_id: str,
        *,
        next_contact: str = "Secondary contact",
    ) -> None:
        self.household_id = household_id
        self.next_contact = next_contact
        self.state: CareState = "idle"
        self.incident_id: str | None = None
        self.owner: str | None = None
        self.acked_action: str | None = None
        self.documentation: str | None = None
        self.escalation_stopped: bool = False
        self.inform_card: dict[str, Any] | None = None
        self._events: list[AuditEvent] = []

    @classmethod
    def for_household(cls, household_id: str, **kwargs: Any) -> CareConversation:
        existing = cls._by_household.get(household_id)
        if existing is not None and existing.state in _OPEN_STATES:
            return existing
        conv = cls(household_id, **kwargs)
        cls._by_household[household_id] = conv
        return conv

    @classmethod
    def reset_registry(cls) -> None:
        cls._by_household.clear()

    def audit_events(self) -> list[AuditEvent]:
        return list(self._events)

    def start_speaker(
        self,
        *,
        incident_id: str,
        cue_kind: str,
        cue_text: str = "",
    ) -> CareState:
        if self.state in _OPEN_STATES:
            return self.state
        self.incident_id = incident_id
        self.state = "speaker_window"
        self._append(
            "speaker_window",
            {
                "incident_id": incident_id,
                "cue_kind": cue_kind,
                "cue_text": cue_text,
                "fsm_state": self.state,
            },
        )
        return self.state

    def close_from_speaker(self, *, reason: str = "clear_ok", raw: str = "") -> CareState:
        if self.state != "speaker_window":
            return self.state
        self.state = "closed"
        self._append(
            "closed",
            {
                "reason": reason,
                "raw": raw,
                "family_paged": False,
                "fsm_state": self.state,
            },
        )
        return self.state

    def expire_to_family_paged(
        self,
        *,
        reason: str,
        blurred_frame_ref: str,
        cue_text: str,
        countdown_sec: int,
    ) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        self.inform_card = inform_card(
            blurred_frame_ref,
            cue_text,
            countdown_sec,
            next_contact=self.next_contact,
        )
        self.state = "family_paged"
        self._append(
            "family_paged",
            {
                "reason": reason,
                "inform_card": self.inform_card,
                "fsm_state": self.state,
            },
        )
        return self.state

    def pressure(self) -> CareState:
        if self.escalation_stopped or self.state not in {"family_paged"}:
            return self.state
        self.state = "pressure"
        self._append("pressure", {"fsm_state": self.state})
        return self.state

    def start_call(self, n: int) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if n not in {1, 2}:
            return self.state
        target: CareState = "calling_1" if n == 1 else "calling_2"
        if n == 1 and self.state not in {"family_paged", "pressure"}:
            return self.state
        if n == 2 and self.state != "calling_1":
            return self.state
        self.state = target
        self._append(target, {"n": n, "fsm_state": self.state})
        return self.state

    def ack(self, action: str, by: str, raw: str = "") -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state not in _PAGEABLE:
            return self.state
        if action not in ACK_ACTIONS:
            return self.state
        self.owner = by
        self.acked_action = action
        self.escalation_stopped = True
        self._append(
            "caregiver_ack",
            {
                "action": action,
                "by": by,
                "raw": raw,
                "channel": "alexa_mobile",
                "fsm_state": self.state,
                "ask_outcome": True,
            },
        )
        return self.state

    def record_outcome(self, text: str) -> CareState:
        if self.state == "closed":
            return self.state
        self.documentation = text
        self.state = "closed"
        self._append(
            "closed",
            {
                "documentation": text,
                "owner": self.owner,
                "acked_action": self.acked_action,
                "fsm_state": self.state,
            },
        )
        return self.state

    def _append(self, tool: str, detail: dict[str, Any]) -> None:
        self._events.append(
            AuditEvent(
                tool=tool,
                detail=detail,
                at=datetime.now(timezone.utc),
            )
        )
