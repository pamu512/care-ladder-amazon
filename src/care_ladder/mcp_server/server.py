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

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import AuditEvent, CueEvent
from care_ladder.plan_loader import load_care_plan

# Midday UTC clock so quiet-hours soft-suppress never hides the demo ladder.
from datetime import datetime, timezone

_DEMO_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AMAZON_PLAN = _REPO_ROOT / "configs" / "amazon_demo_home.yaml"

mcp: MCPServer = MCPServer("Care Ladder")

# In-memory incident sessions keyed by household+incident id (the AuditStore
# remains the durable record; this registry maps MCP sessions to incidents).
_SESSIONS: dict[str, dict[str, Any]] = {}
_PENDING_ANSWERS: dict[str, str] = {}


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
    _stamp_via_mcp(incident)
    _SESSIONS[_session_key(household_id, iid)] = {
        "incident": incident,
        "rungs": [r.tool for r in plan.rungs],
        "household_id": household_id,
    }
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


@mcp.tool()
def notify_caretaker(household_id: str, incident_id: str) -> dict[str, Any]:
    """Notify the caretaker (push mock + Fire TV). Demo-simulated, no real push."""
    sess = _SESSIONS.get(_session_key(household_id, incident_id))
    if sess is None:
        return _with_snapshot(
            {"error": "unknown incident", "incident_id": incident_id},
            household_id,
            incident_id,
        )
    inc = sess["incident"]
    _append_mcp_event(
        sess,
        "notify_caretaker",
        {"channels": ["push_mock", "fire_tv"], "simulated": True},
    )
    return _with_snapshot(
        {"incident_id": inc.id, "notified": True, "channels": ["push_mock", "fire_tv"],
         "simulated": True},
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
    plan = load_care_plan(_AMAZON_PLAN)
    _append_mcp_event(
        sess,
        "request_call",
        {"phone_e164": plan.caregiver.phone_e164, "simulated": True},
    )
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


def mount_path() -> str:
    """ASGI sub-app for FastAPI mounting at /mcp."""
    return "/mcp"


__all__ = ["mcp", "mount_path", "session_snapshot"]
