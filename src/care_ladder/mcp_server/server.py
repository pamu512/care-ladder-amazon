"""Self-hosted MCP server exposing Care Ladder care-flow tools over
Streamable HTTP (MCP spec 2025-11-25+), for the Alexa+ agent path.

Mounted as an ASGI sub-app inside the existing FastAPI app: one container,
one port. The Alexa+ agent (or the in-repo simulator, alexa_sim.py) calls
these tools at runtime to drive an incident through its rungs.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from care_ladder.audit.store import AuditStore
from care_ladder.channels.apl_notify import apl_notify_card
from care_ladder.channels.care_conversation import (
    ACK_ACTIONS,
    CareConversation,
    apply_caregiver_intent,
    ensure_family_paged,
)
from care_ladder.channels.caregiver_intent import (
    DIRECTION_ACTIONS,
    VOICE_ACTIONS,
    classify_caregiver_intent,
    extract_alternate_contact,
    spoken_confirmation,
)
from care_ladder.learning.schedule import default_book
from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import AuditEvent, CueEvent
from care_ladder.plan_loader import effective_roster, load_care_plan

# Midday UTC clock so quiet-hours soft-suppress never hides the demo ladder.
from datetime import datetime, timezone

_DEMO_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AMAZON_PLAN = _REPO_ROOT / "configs" / "amazon_demo_home.yaml"

mcp: MCPServer = MCPServer("Care Ladder")

# Session registry keyed by household+incident. Incidents are also saved
# into the FastAPI AuditStore so Fire TV's /incidents poll sees the same
# object the MCP tools mutate.
_SESSIONS: dict[str, dict[str, Any]] = {}
_PENDING_ANSWERS: dict[str, str] = {}
_STORE: AuditStore | None = None


def bind_audit_store(store: AuditStore | None) -> None:
    """Point MCP mutations at the same store Fire TV polls."""
    global _STORE
    _STORE = store


def _persist(sess: dict[str, Any] | None, *, driving: bool = True) -> None:
    if _STORE is None or sess is None:
        return
    inc = sess["incident"]
    _STORE.save(inc)
    if driving:
        _STORE.mark_mcp_driving(sess["household_id"], inc.id)


def _mark_driving(household_id: str, incident_id: str | None) -> None:
    if _STORE is None or not incident_id:
        return
    _STORE.mark_mcp_driving(household_id, incident_id)


def _session_key(household_id: str, incident_id: str) -> str:
    return f"{household_id}:{incident_id}"


def _tools_trail(sess: dict[str, Any] | None) -> list[str]:
    if sess is None:
        return []
    return [e.tool for e in sess["incident"].events]


def _rung_index(sess: dict[str, Any] | None) -> int:
    """1-based last plan rung present on the incident trail; 0 if unknown."""
    if sess is None:
        return 0
    trail = _tools_trail(sess)
    idx = 0
    for i, name in enumerate(sess.get("rungs") or []):
        if name in trail:
            idx = i + 1
    return idx or 1


def session_snapshot(household_id: str, incident_id: str | None) -> dict[str, Any]:
    """Shared agent-memory block reused on every MCP tool return."""
    sess = (
        _SESSIONS.get(_session_key(household_id, incident_id))
        if incident_id
        else None
    )
    if sess is None:
        return {
            "household_id": household_id,
            "incident_id": incident_id,
            "rung": 0,
            "status": "unknown",
            "tools": [],
        }
    inc = sess["incident"]
    return {
        "household_id": household_id,
        "incident_id": inc.id,
        "rung": _rung_index(sess),
        "status": inc.status,
        "tools": _tools_trail(sess),
    }


def _with_snapshot(
    payload: dict[str, Any], household_id: str, incident_id: str | None
) -> dict[str, Any]:
    snap = session_snapshot(household_id, incident_id)
    out = {**payload, "session_snapshot": snap}
    for key in ("household_id", "incident_id", "rung", "status", "tools"):
        out.setdefault(key, snap[key])
    return out


def _stamp_via_mcp(inc) -> None:
    if inc.cue.detail.get("via") != "mcp":
        inc.cue.detail = {**inc.cue.detail, "via": "mcp"}
    for ev in inc.events:
        if ev.detail.get("via") != "mcp":
            ev.detail = {**ev.detail, "via": "mcp"}


def _append_mcp_event(sess: dict[str, Any], tool: str, extra: dict[str, Any] | None = None) -> None:
    inc = sess["incident"]
    inc.events.append(
        AuditEvent(
            tool=tool,
            cue_kind=inc.cue.kind,
            detail={"via": "mcp", **(extra or {})},
            at=datetime.now(timezone.utc),
        )
    )


@mcp.tool()
def start_or_resume_incident(
    cue_kind: str,
    household_id: str = "amazon-demo-1",
    confidence: float = 0.9,
    incident_id: str | None = None,
) -> dict[str, Any]:
    """Start (or resume) a care-ladder incident for a household.

    cue_kind: no_movement | no_visibility | distress_heuristic.
    Returns the incident id plus the plan's rung sequence.
    """
    if incident_id and _session_key(household_id, incident_id) in _SESSIONS:
        sess = _SESSIONS[_session_key(household_id, incident_id)]
        _persist(sess)
        return _with_snapshot(
            {"incident_id": sess["incident"].id, "resumed": True,
             "status": sess["incident"].status, "rungs": sess["rungs"]},
            household_id,
            incident_id,
        )
    if cue_kind not in {"no_movement", "no_visibility", "distress_heuristic"}:
        return _with_snapshot(
            {"error": "invalid cue_kind", "cue_kind": cue_kind},
            household_id,
            incident_id,
        )
    plan = load_care_plan(_AMAZON_PLAN)
    iid = incident_id or uuid.uuid4().hex
    stale = CareConversation._by_household.get(household_id)
    if stale is not None and stale.incident_id != iid:
        CareConversation._by_household.pop(household_id, None)
    cue = CueEvent(
        kind=cue_kind,  # type: ignore[arg-type]  # validated above
        confidence=confidence,
        detail={"via": "mcp", "incident_id": iid},
    )
    # The orchestrator runs async; run it to completion here (demo scale).
    incident = asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=[]),
            dialer=StubDialer(behavior={}),
            pre_event_frames=[],
            now=_DEMO_NOW,
        )
    )
    # Keep the caller-visible id stable even though run_incident mints its own.
    incident.id = iid
    conv = CareConversation._by_household.get(household_id)
    if conv is not None:
        conv.incident_id = iid
    _stamp_via_mcp(incident)
    sess = {
        "incident": incident,
        "rungs": [r.tool for r in plan.rungs],
        "household_id": household_id,
    }
    _SESSIONS[_session_key(household_id, iid)] = sess
    _persist(sess)
    return _with_snapshot(
        {"incident_id": iid, "resumed": False, "status": incident.status,
         "rungs": [r.tool for r in plan.rungs]},
        household_id,
        iid,
    )


@mcp.tool()
def check_in_prompt(household_id: str, incident_id: str, utterance: str) -> dict[str, Any]:
    """Record the monitored person's utterance from a voice check-in.

    The Alexa+ agent calls this after each TTS attempt. Fail-closed intent
    (clear_ok / needs_human / unclear) is the gate; reply_kind stays as the
    legacy ok / call_caregiver / silence mapping.
    """
    _PENDING_ANSWERS[_session_key(household_id, incident_id)] = utterance
    from care_ladder.channels.response_intent import (
        classify_response_intent,
        intent_label,
        intent_to_reply_kind,
    )

    intent = classify_response_intent(utterance)
    kind = intent_to_reply_kind(intent, utterance)
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is not None:
        last_chk = next(
            (e for e in reversed(sess["incident"].events) if e.tool == "alexa_checkin"),
            None,
        )
        detail = {
            "via": "mcp",
            "reply_raw": utterance,
            "response_intent": intent,
            "intent_label": intent_label(intent),
            "reply_kind": kind,
        }
        if last_chk is not None:
            last_chk.detail = {**last_chk.detail, **detail}
        else:
            _append_mcp_event(sess, "alexa_checkin", detail)
        _persist(sess)
    else:
        _mark_driving(household_id, incident_id)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            "reply_kind": kind,
            "response_intent": intent,
            "intent_label": intent_label(intent),
            "raw": utterance,
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def advance_rung(household_id: str, incident_id: str) -> dict[str, Any]:
    """Advance the incident to its next rung (silence / no-answer path)."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    _persist(sess)
    tools = [e.tool for e in sess["incident"].events]
    return _with_snapshot(
        {"incident_id": incident_id, "advanced_to": sess["rungs"][-1],
         "events_so_far": tools},
        household_id,
        incident_id,
    )


@mcp.tool()
def resolve_incident(
    household_id: str, incident_id: str, reason: str = "voice_ok"
) -> dict[str, Any]:
    """Resolve an incident (voice OK or caretaker acknowledge)."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    if sess["incident"].status == "resolved":
        return _with_snapshot(
            {"error": "already_resolved", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    sess["incident"].status = "resolved"
    _append_mcp_event(sess, "resolve", {"reason": reason})
    _persist(sess)
    return _with_snapshot(
        {"incident_id": incident_id, "status": "resolved", "reason": reason},
        household_id,
        incident_id,
    )


@mcp.tool()
def get_incident_status(household_id: str, incident_id: str) -> dict[str, Any]:
    """Return the incident's status, cue, and audit-trail tool sequence."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    inc = sess["incident"]
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": inc.id,
            "status": inc.status,
            "cue_kind": inc.cue.kind,
            "tools": [e.tool for e in inc.events],
            "rungs": sess["rungs"],
        },
        household_id,
        incident_id,
    )


def _latest_incident_id(household_id: str) -> str | None:
    for key, sess in reversed(list(_SESSIONS.items())):
        if sess.get("household_id") == household_id:
            return sess["incident"].id
    conv = CareConversation._by_household.get(household_id)
    return conv.incident_id if conv is not None else None


def _time_since_cue_sec(inc) -> int:
    created = getattr(inc, "created_at", None)
    if created is None:
        return 0
    now = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, int((now - created).total_seconds()))


def _page_mobile(sess: dict[str, Any], household_id: str, reason: str) -> CareConversation:
    inc = sess["incident"]
    plan = load_care_plan(_AMAZON_PLAN)
    roster = effective_roster(plan)
    next_name = (
        roster[1].name
        if len(roster) > 1
        else (
            plan.secondary.display_name
            if plan.secondary is not None
            else "Secondary contact"
        )
    )
    conv = ensure_family_paged(
        household_id,
        incident_id=inc.id,
        cue_kind=inc.cue.kind,
        reason=reason,
        blurred_frame_ref=f"blurred:{inc.id}",
        cue_text=str(inc.cue.kind).replace("_", " "),
        countdown_sec=180,
        next_contact=next_name,
        roster=roster,
    )
    conv._refresh_apl(_time_since_cue_sec(inc))
    return conv


def _parse_now(now_iso: str) -> datetime:
    raw = (now_iso or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


@mcp.tool()
def notify_caretaker(household_id: str, incident_id: str) -> dict[str, Any]:
    """Notify the caregiver on Alexa mobile (inform card). Simulated, no real push."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    inc = sess["incident"]
    conv = _page_mobile(sess, household_id, reason="mcp_notify")
    extra = {
        "channels": ["alexa_mobile"],
        "simulated": True,
        "surface": "alexa_mobile",
        "inform_card": conv.inform_card,
        "apl_card": conv.apl_card,
        "fsm_state": conv.state,
    }
    _append_mcp_event(sess, "notify_caretaker", extra)
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": inc.id,
            "notified": True,
            "channels": ["alexa_mobile"],
            "simulated": True,
            "surface": "alexa_mobile",
            "inform_card": conv.inform_card,
            "apl_card": conv.apl_card or apl_notify_card(
                thumbnail=f"blurred:{inc.id}",
                household_label=f"{household_id} · Resident",
                time_since_cue_sec=_time_since_cue_sec(inc),
                cue_text=str(inc.cue.kind).replace("_", " "),
                countdown_sec=180,
            ),
            "fsm_state": conv.state,
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def request_call(household_id: str, incident_id: str) -> dict[str, Any]:
    """Request a call to the caregiver's reserved fictional number. Simulated only."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    conv = CareConversation.for_household(household_id)
    if conv.escalation_stopped:
        _persist(sess)
        return _with_snapshot(
            {
                "incident_id": incident_id,
                "skipped": True,
                "reason": "escalation_stopped",
                "simulated": True,
            },
            household_id,
            incident_id,
        )
    plan = load_care_plan(_AMAZON_PLAN)
    _append_mcp_event(
        sess,
        "request_call",
        {"phone_e164": plan.caregiver.phone_e164, "simulated": True},
    )
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            "phone_e164": plan.caregiver.phone_e164,
            "simulated": True,
            "note": "demo_stub_no_real_dial",
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def caregiver_ack(
    household_id: str,
    incident_id: str,
    utterance: str = "",
    action: str = "",
) -> dict[str, Any]:
    """Caregiver ack on Alexa mobile. First wins; stops pressure/call escalation."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    resolved = action if action else classify_caregiver_intent(utterance)
    allowed = set(ACK_ACTIONS) | set(VOICE_ACTIONS) | set(DIRECTION_ACTIONS)
    if resolved not in allowed:
        _persist(sess)
        return _with_snapshot(
            {
                "error": "unclear_ack",
                "intent": resolved,
                "acked": False,
                "raw": utterance,
            },
            household_id,
            incident_id,
        )
    conv = _page_mobile(sess, household_id, reason="caregiver_ack")
    already = conv.escalation_stopped
    alt = extract_alternate_contact(utterance)
    apply_caregiver_intent(
        conv,
        resolved,
        by="Primary contact",
        raw=utterance or action,
        alternate=alt,
    )
    inc = sess["incident"]
    now = datetime.now(timezone.utc)
    if inc.acked_by is None and conv.owner:
        inc.acked_by = conv.owner
        inc.acked_at = now
    if conv.state == "closed" and inc.status != "resolved":
        inc.status = "resolved"
        _append_mcp_event(
            sess,
            "resolve",
            {
                "reason": conv.acked_action or resolved,
                "channel": "alexa_mobile",
                "owner": conv.owner,
                "fsm_state": conv.state,
            },
        )
    _append_mcp_event(
        sess,
        "caregiver_ack",
        {
            "action": conv.acked_action or resolved,
            "by": conv.owner,
            "raw": utterance,
            "channel": "alexa_mobile",
            "first_wins": True,
            "already_acked": already,
            "fsm_state": conv.state,
            "spoken": conv.last_spoken,
        },
    )
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            "acked": True,
            "action": conv.acked_action or resolved,
            "owner": conv.owner,
            "channel": "alexa_mobile",
            "escalation_stopped": conv.escalation_stopped,
            "ask_outcome": conv.acked_action in ACK_ACTIONS
            or conv.acked_action == "on_my_way",
            "already_acked": already,
            "fsm_state": conv.state,
            "spoken": conv.last_spoken or spoken_confirmation(resolved, alternate=alt),
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def caregiver_outcome(
    household_id: str,
    incident_id: str,
    text: str,
) -> dict[str, Any]:
    """Record caregiver outcome on Alexa mobile and close the incident."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    inc = sess["incident"]
    if inc.status == "resolved":
        return _with_snapshot(
            {"error": "already_resolved", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    conv = CareConversation._by_household.get(household_id)
    if conv is None:
        return _with_snapshot(
            {
                "error": "outcome_requires_ack",
                "incident_id": incident_id,
                "fsm_state": "idle",
            },
            household_id,
            incident_id,
        )
    if conv.owner and conv._is_local(conv.owner):
        conv.report_local_outcome(text, by=conv.owner)
    else:
        conv.record_outcome(text)
    if conv.state != "closed":
        return _with_snapshot(
            {
                "error": "outcome_requires_ack",
                "incident_id": incident_id,
                "fsm_state": conv.state,
            },
            household_id,
            incident_id,
        )
    inc.status = "resolved"
    _append_mcp_event(
        sess,
        "resolve",
        {
            "reason": "caregiver_outcome",
            "documentation": text,
            "channel": "alexa_mobile",
            "owner": conv.owner,
            "fsm_state": conv.state,
        },
    )
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            "status": "resolved",
            "documentation": text,
            "channel": "alexa_mobile",
            "fsm_state": "closed",
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def defer_escalation(
    household_id: str,
    incident_id: str,
    alternate_contact: str = "",
    utterance: str = "",
    now_iso: str = "",
) -> dict[str, Any]:
    """Defer the current escalate to alternate_contact. Notify X; no auto-dial."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    name = (alternate_contact or "").strip() or extract_alternate_contact(utterance) or ""
    if not name:
        return _with_snapshot(
            {"error": "missing_alternate_contact", "acked": False},
            household_id,
            incident_id,
        )
    conv = _page_mobile(sess, household_id, reason="defer_escalation")
    conv.defer(
        name,
        by="Primary contact",
        raw=utterance or f"call {name} instead",
        now=_parse_now(now_iso),
    )
    _append_mcp_event(
        sess,
        "defer_escalation",
        {
            "alternate_contact": name,
            "fsm_state": conv.state,
            "spoken": conv.last_spoken,
            "channel": "alexa_mobile",
        },
    )
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            "fsm_state": conv.state,
            "alternate_contact": name,
            "spoken": conv.last_spoken,
            "defer_deadline": (
                conv.defer_deadline.isoformat() if conv.defer_deadline else None
            ),
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def tick_care_timers(
    household_id: str,
    incident_id: str,
    now_iso: str = "",
    monitored_utterance: str = "",
) -> dict[str, Any]:
    """Advance soft-escalate / defer / snooze timers. Never auto-dials."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    conv = CareConversation._by_household.get(household_id) or _page_mobile(
        sess, household_id, reason="tick"
    )
    before = conv.state
    conv.tick(_parse_now(now_iso), monitored_raw=monitored_utterance)
    extra = {
        "from_state": before,
        "fsm_state": conv.state,
        "monitored_report": conv.monitored_report,
        "ask_primary": conv.state in {"defer_failed", "ladder_exhausted"},
        "direction_actions": list(
            conv.audit_events()[-1].detail.get("direction_actions", [])
        )
        if conv.state in {"defer_failed", "ladder_exhausted"}
        else [],
        "dial": False,
    }
    _append_mcp_event(sess, "tick_care_timers", extra)
    _persist(sess)
    return _with_snapshot(
        {
            "incident_id": incident_id,
            **extra,
        },
        household_id,
        incident_id,
    )


@mcp.tool()
def how_is_household(household_id: str) -> dict[str, Any]:
    """Status intent: last cue, last ack, open or quiet since."""
    conv = CareConversation._by_household.get(household_id)
    iid = _latest_incident_id(household_id)
    if conv is None:
        status = {
            "household_id": household_id,
            "last_cue": None,
            "last_ack": None,
            "open": False,
            "quiet_since": None,
            "fsm_state": "idle",
            "spoken": "The household is quiet. No open Care Ladder alert.",
        }
    else:
        status = conv.household_status()
        if iid:
            status["incident_id"] = iid
        status["spoken"] = spoken_confirmation("how_is_household")
    return _with_snapshot(status, household_id, iid)


@mcp.tool()
def confirm_schedule_pin(household_id: str, window: str = "") -> dict[str, Any]:
    """Caregiver confirms a proposed repeating window pin. Roster is informed."""
    book = default_book()
    pin = book.confirm_pin(household_id, window)
    iid = _latest_incident_id(household_id)
    sess = (
        _SESSIONS.get(_session_key(household_id, iid))
        if iid
        else None
    )
    if sess is not None:
        _append_mcp_event(sess, "schedule_pinned", pin)
        _persist(sess)
    return _with_snapshot(
        {
            **pin,
            "household_id": household_id,
        },
        household_id,
        iid,
    )


def mount_path() -> str:
    """ASGI sub-app for FastAPI mounting at /mcp."""
    return "/mcp"


__all__ = ["mcp", "mount_path", "session_snapshot", "bind_audit_store"]
