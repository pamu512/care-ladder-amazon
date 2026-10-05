"""Channel-agnostic care conversation FSM (Alexa-session beats, no chat adapters).

States: idle → speaker_window → family_paged → pressure → calling_1 → calling_2 → closed
Plus deepen: snoozed, deferred, defer_failed, soft_reprompt, soft_next.
Resident clear_ok closes from speaker_window without paging family.
ANY caregiver ack stops escalation; outcome closes with documentation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Literal

from care_ladder.channels.response_intent import classify_response_intent
from care_ladder.models import AuditEvent

CareState = Literal[
    "idle",
    "speaker_window",
    "family_paged",
    "pressure",
    "calling_1",
    "calling_2",
    "snoozed",
    "deferred",
    "defer_failed",
    "soft_reprompt",
    "soft_next",
    "closed",
]

ACK_ACTIONS = ("im_on_it", "call_mom_now", "pass_to_next")

INFORM_ACTIONS: tuple[dict[str, str], ...] = (
    {"id": "im_on_it", "label": "I'm on it - call her myself"},
    {"id": "call_mom_now", "label": "Call Mom now"},
    {"id": "pass_to_next", "label": "Can't take it - go to {next}"},
)

T_REPROMPT = 60
T_NEXT = 60
T_SNOOZE = 300
T_DEFER = 90

DIRECTION_ACTIONS = (
    "try_other",
    "try_again",
    "on_my_way",
    "false_alarm",
    "snooze_alert",
)

_OPEN_STATES = frozenset(
    {
        "speaker_window",
        "family_paged",
        "pressure",
        "calling_1",
        "calling_2",
        "snoozed",
        "deferred",
        "defer_failed",
        "soft_reprompt",
        "soft_next",
    }
)
_PAGEABLE = frozenset(
    {
        "family_paged",
        "pressure",
        "calling_1",
        "calling_2",
        "soft_reprompt",
        "soft_next",
        "deferred",
        "defer_failed",
    }
)
_SOFT_HOLD = frozenset({"soft_reprompt", "soft_next"})


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
        self.apl_card: dict[str, Any] | None = None
        self.last_spoken: str = ""
        self.deferred_to: str | None = None
        self.defer_deadline: datetime | None = None
        self.snooze_until: datetime | None = None
        self.family_paged_at: datetime | None = None
        self.soft_reprompt_at: datetime | None = None
        self.monitored_report: str | None = None
        self.cue_kind: str | None = None
        self.cue_text: str = ""
        self.blurred_frame_ref: str = ""
        self.countdown_sec: int = 180
        self.last_cue: dict[str, Any] | None = None
        self.last_ack: dict[str, Any] | None = None
        self.quiet_since: datetime | None = None
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
        self.cue_kind = cue_kind
        self.cue_text = cue_text
        self.last_cue = {
            "kind": cue_kind,
            "text": cue_text,
            "at": datetime.now(timezone.utc),
        }
        self.state = "speaker_window"
        self.quiet_since = None
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

    def _evict_if_registered(self) -> None:
        if type(self)._by_household.get(self.household_id) is self:
            type(self)._by_household.pop(self.household_id, None)

    def close_from_speaker(self, *, reason: str = "clear_ok", raw: str = "") -> CareState:
        if self.state != "speaker_window":
            return self.state
        self.state = "closed"
        self.quiet_since = datetime.now(timezone.utc)
        self._evict_if_registered()
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
        now: datetime | None = None,
    ) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state in _PAGEABLE:
            return self.state
        clock = now or datetime.now(timezone.utc)
        self.blurred_frame_ref = blurred_frame_ref
        self.cue_text = cue_text
        self.countdown_sec = countdown_sec
        self.inform_card = inform_card(
            blurred_frame_ref,
            cue_text,
            countdown_sec,
            next_contact=self.next_contact,
        )
        self._refresh_apl(0)
        self.family_paged_at = clock
        self.state = "family_paged"
        self._append(
            "family_paged",
            {
                "reason": reason,
                "inform_card": self.inform_card,
                "fsm_state": self.state,
            },
        )
        from care_ladder.channels.proactive_events import (
            proactive_enabled,
            send_awareness_chime,
        )

        if proactive_enabled() and self.incident_id:
            chime = send_awareness_chime(self.household_id, self.incident_id)
            self._append("proactive_chime", chime)
        return self.state

    def _refresh_apl(self, time_since_cue_sec: int) -> None:
        from care_ladder.channels.apl_notify import apl_notify_card

        self.apl_card = apl_notify_card(
            thumbnail=self.blurred_frame_ref or "last-frame-placeholder",
            household_label=f"{self.household_id} · Resident",
            time_since_cue_sec=time_since_cue_sec,
            cue_text=self.cue_text,
            countdown_sec=self.countdown_sec,
            next_contact=self.next_contact,
        )

    def pressure(self) -> CareState:
        if self.escalation_stopped or self.state not in {"family_paged"}:
            return self.state
        self.state = "pressure"
        self._append("pressure", {"fsm_state": self.state})
        return self.state

    def start_call(self, n: int) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state in _SOFT_HOLD | {"deferred", "defer_failed", "snoozed"}:
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
        self._set_ack(action, by)
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

    def _set_ack(self, action: str, by: str) -> None:
        self.last_ack = {
            "action": action,
            "by": by,
            "at": datetime.now(timezone.utc),
        }

    def record_outcome(self, text: str) -> CareState:
        if self.state == "closed":
            return self.state
        if self.state not in _PAGEABLE or not self.escalation_stopped:
            return self.state
        self.documentation = text
        self.state = "closed"
        self.quiet_since = datetime.now(timezone.utc)
        self._evict_if_registered()
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

    def false_alarm(self, by: str, raw: str = "") -> CareState:
        if self.state in {"idle", "closed"}:
            return self.state
        from care_ladder.channels.caregiver_intent import spoken_confirmation

        self.owner = by
        self.acked_action = "false_alarm"
        self.escalation_stopped = True
        self.last_spoken = spoken_confirmation("false_alarm")
        self._set_ack("false_alarm", by)
        self._append(
            "false_alarm",
            {
                "by": by,
                "raw": raw,
                "spoken": self.last_spoken,
                "fsm_state": self.state,
            },
        )
        self.state = "closed"
        self.quiet_since = datetime.now(timezone.utc)
        self._evict_if_registered()
        self._append(
            "closed",
            {
                "reason": "false_alarm",
                "owner": by,
                "fsm_state": self.state,
            },
        )
        return self.state

    def on_my_way(self, by: str, raw: str = "") -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state not in _PAGEABLE:
            return self.state
        from care_ladder.channels.caregiver_intent import spoken_confirmation

        self.owner = by
        self.acked_action = "on_my_way"
        self.escalation_stopped = True
        self.last_spoken = spoken_confirmation("on_my_way")
        self._set_ack("on_my_way", by)
        self._append(
            "on_my_way",
            {
                "by": by,
                "raw": raw,
                "spoken": self.last_spoken,
                "ask_outcome": True,
                "fsm_state": self.state,
            },
        )
        return self.state

    def need_second_look(self, by: str, raw: str = "") -> CareState:
        if self.state == "closed" or self.state not in _PAGEABLE:
            return self.state
        from care_ladder.channels.caregiver_intent import spoken_confirmation

        self.last_spoken = spoken_confirmation("need_second_look")
        self._set_ack("need_second_look", by)
        self.state = "speaker_window"
        self._append(
            "need_second_look",
            {
                "by": by,
                "raw": raw,
                "spoken": self.last_spoken,
                "fsm_state": self.state,
                "incident_id": self.incident_id,
            },
        )
        return self.state

    def snooze(
        self,
        by: str,
        raw: str = "",
        *,
        now: datetime | None = None,
        t_snooze: int = T_SNOOZE,
    ) -> CareState:
        if self.state == "closed" or self.state not in _PAGEABLE | {"snoozed"}:
            return self.state
        from care_ladder.channels.caregiver_intent import spoken_confirmation

        clock = now or datetime.now(timezone.utc)
        self.state = "snoozed"
        self.snooze_until = clock + timedelta(seconds=int(t_snooze))
        self.last_spoken = spoken_confirmation("snooze_alert")
        self._set_ack("snooze_alert", by)
        self._append(
            "snooze",
            {
                "by": by,
                "raw": raw,
                "spoken": self.last_spoken,
                "until": self.snooze_until.isoformat(),
                "fsm_state": self.state,
            },
        )
        return self.state

    def defer(
        self,
        alternate_contact: str,
        by: str,
        raw: str = "",
        *,
        now: datetime | None = None,
        t_defer: int = T_DEFER,
    ) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state not in _PAGEABLE | {"speaker_window"}:
            return self.state
        from care_ladder.channels.caregiver_intent import spoken_confirmation

        clock = now or datetime.now(timezone.utc)
        name = (alternate_contact or "").strip()
        if not name:
            return self.state
        self.deferred_to = name
        self.defer_deadline = clock + timedelta(seconds=int(t_defer))
        self.state = "deferred"
        self.last_spoken = spoken_confirmation("defer_escalation", alternate=name)
        self._append(
            "defer",
            {
                "alternate_contact": name,
                "by": by,
                "raw": raw,
                "spoken": self.last_spoken,
                "deadline": self.defer_deadline.isoformat(),
                "notify_x": {
                    "simulated": True,
                    "to": name,
                    "household_id": self.household_id,
                    "cue_text": self.cue_text,
                    "context": (
                        f"{self.household_id}: {self.cue_text or self.cue_kind}. "
                        f"Asked to take this instead of {by}."
                    ),
                    "channel": "alexa_mobile",
                },
                "fsm_state": self.state,
            },
        )
        return self.state

    def record_monitored_checkin(self, raw: str) -> str:
        intent = classify_response_intent(raw)
        token = {
            "clear_ok": "monitored_ok",
            "needs_human": "monitored_needs_help",
            "unclear": "monitored_silent",
        }.get(intent, "monitored_silent")
        self.monitored_report = token
        self._append(
            "monitored_checkin",
            {
                "raw": raw,
                "response_intent": intent,
                "monitored_report": token,
                "prompt": "Are you okay?",
            },
        )
        return token

    def _enter_defer_failed(self, now: datetime, monitored_raw: str) -> CareState:
        self.state = "defer_failed"
        token = self.record_monitored_checkin(monitored_raw)
        self._append(
            "defer_failed",
            {
                "ask_primary": True,
                "parallel_checkin": True,
                "monitored_report": token,
                "deferred_to": self.deferred_to,
                "direction_actions": list(DIRECTION_ACTIONS),
                "at": now.isoformat(),
                "fsm_state": self.state,
                "phrase": (
                    f"{self.deferred_to} did not answer. Monitored report: {token}. "
                    "What should I do: try someone else, try them again, say you are "
                    "on the way, mark a false alarm, or snooze?"
                ),
            },
        )
        return self.state

    def tick(self, now: datetime, *, monitored_raw: str | None = None) -> CareState:
        if self.escalation_stopped or self.state == "closed":
            return self.state
        if self.state == "snoozed" and self.snooze_until is not None:
            if now >= self.snooze_until:
                return self._repage(now, reason="snooze_elapsed")
            return self.state
        if self.state == "deferred" and self.defer_deadline is not None:
            if now >= self.defer_deadline:
                raw = "" if monitored_raw is None else monitored_raw
                return self._enter_defer_failed(now, raw)
            return self.state
        if self.state == "family_paged" and self.family_paged_at is not None:
            elapsed = (now - self.family_paged_at).total_seconds()
            if elapsed >= T_REPROMPT:
                return self._soft_reprompt(now)
            return self.state
        if self.state == "soft_reprompt" and self.soft_reprompt_at is not None:
            elapsed = (now - self.soft_reprompt_at).total_seconds()
            if elapsed >= T_NEXT:
                return self._soft_next(now)
            return self.state
        return self.state

    def _soft_reprompt(self, now: datetime) -> CareState:
        self.state = "soft_reprompt"
        self.soft_reprompt_at = now
        phrase = "Still waiting on a reply. Care Ladder needs a caregiver."
        self._append(
            "soft_reprompt",
            {
                "phrase": phrase,
                "louder": True,
                "fsm_state": self.state,
                "at": now.isoformat(),
            },
        )
        return self.state

    def _soft_next(self, now: datetime) -> CareState:
        self.state = "soft_next"
        phrase = (
            f"No reply from Primary contact. Notifying {self.next_contact}. "
            "This is not a phone call."
        )
        self._append(
            "soft_next",
            {
                "phrase": phrase,
                "next_contact": self.next_contact,
                "dial": False,
                "fsm_state": self.state,
                "at": now.isoformat(),
            },
        )
        return self.state

    def _repage(self, now: datetime, *, reason: str) -> CareState:
        self.state = "family_paged"
        self.family_paged_at = now
        self.soft_reprompt_at = None
        self.inform_card = inform_card(
            self.blurred_frame_ref or "last-frame-placeholder",
            self.cue_text or "Care Ladder check-in",
            self.countdown_sec,
            next_contact=self.next_contact,
        )
        self._refresh_apl(0)
        self._append(
            "family_paged",
            {
                "reason": reason,
                "inform_card": self.inform_card,
                "fsm_state": self.state,
                "at": now.isoformat(),
            },
        )
        return self.state

    def primary_direction(
        self,
        intent: str,
        *,
        alternate: str | None = None,
        by: str,
        raw: str = "",
        now: datetime | None = None,
    ) -> CareState:
        if self.state != "defer_failed":
            return self.state
        clock = now or datetime.now(timezone.utc)
        if intent == "try_again":
            target = self.deferred_to or alternate or self.next_contact
            return self.defer(target, by=by, raw=raw, now=clock)
        if intent == "try_other":
            target = alternate or self.next_contact
            return self.defer(target, by=by, raw=raw, now=clock)
        if intent == "on_my_way":
            return self.on_my_way(by=by, raw=raw)
        if intent == "false_alarm":
            return self.false_alarm(by=by, raw=raw)
        if intent == "snooze_alert":
            return self.snooze(by=by, raw=raw, now=clock)
        return self.state

    def household_status(self) -> dict[str, Any]:
        open_ = self.state in _OPEN_STATES
        out: dict[str, Any] = {
            "household_id": self.household_id,
            "incident_id": self.incident_id,
            "fsm_state": self.state,
            "last_cue": self.last_cue or {"kind": self.cue_kind},
            "last_ack": self.last_ack,
            "open": open_,
        }
        if not open_:
            out["quiet_since"] = self.quiet_since
        return out

    def _append(self, tool: str, detail: dict[str, Any]) -> None:
        self._events.append(
            AuditEvent(
                tool=tool,
                detail=detail,
                at=datetime.now(timezone.utc),
            )
        )


def ensure_family_paged(
    household_id: str,
    *,
    incident_id: str,
    cue_kind: str,
    reason: str,
    blurred_frame_ref: str,
    cue_text: str,
    countdown_sec: int = 180,
    next_contact: str = "Secondary contact",
    now: datetime | None = None,
) -> CareConversation:
    """Open or join the household thread and page Alexa mobile if needed."""
    conv = CareConversation.for_household(household_id, next_contact=next_contact)
    if conv.state == "idle":
        conv.start_speaker(
            incident_id=incident_id, cue_kind=cue_kind, cue_text=cue_text
        )
    if conv.state == "speaker_window":
        conv.expire_to_family_paged(
            reason=reason,
            blurred_frame_ref=blurred_frame_ref,
            cue_text=cue_text,
            countdown_sec=countdown_sec,
            now=now,
        )
    return conv


def close_resident_ok(
    household_id: str,
    *,
    incident_id: str,
    cue_kind: str,
    raw: str = "",
) -> CareConversation:
    """Resident clear_ok closes the thread without paging family."""
    conv = CareConversation.for_household(household_id)
    if conv.state == "idle":
        conv.start_speaker(incident_id=incident_id, cue_kind=cue_kind)
    conv.close_from_speaker(reason="clear_ok", raw=raw)
    return conv


def apply_caregiver_intent(
    conv: CareConversation,
    intent: str,
    *,
    by: str,
    raw: str = "",
    now: datetime | None = None,
    alternate: str | None = None,
) -> CareState:
    """Dispatch a classified caregiver intent onto the conversation."""
    clock = now or datetime.now(timezone.utc)
    if conv.state == "defer_failed" and intent in DIRECTION_ACTIONS:
        return conv.primary_direction(
            intent, alternate=alternate, by=by, raw=raw, now=clock
        )
    if intent == "false_alarm":
        return conv.false_alarm(by=by, raw=raw)
    if intent == "on_my_way":
        return conv.on_my_way(by=by, raw=raw)
    if intent == "need_second_look":
        return conv.need_second_look(by=by, raw=raw)
    if intent == "snooze_alert":
        return conv.snooze(by=by, raw=raw, now=clock)
    if intent == "defer_escalation" and alternate:
        return conv.defer(alternate, by=by, raw=raw, now=clock)
    if intent in ACK_ACTIONS:
        return conv.ack(intent, by=by, raw=raw)
    return conv.state
