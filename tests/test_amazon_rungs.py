"""Amazon ladder rungs (PRD 8.2): alexa_checkin, wait_window, notify, request_call."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from care_ladder.channels.dial import StubDialer
from care_ladder.channels.speaker import SpeakerSimulator
from care_ladder.ladder.orchestrator import run_incident
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan

PLAN = Path(__file__).resolve().parents[1] / "configs" / "amazon_demo_home.yaml"


@pytest.fixture()
def plan():
    return load_care_plan(PLAN)


NOON = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _run(cue, plan, scripted, behavior=None):
    return asyncio.run(
        run_incident(
            cue=cue,
            plan=plan,
            speaker=SpeakerSimulator(scripted=scripted),
            dialer=StubDialer(behavior=behavior or {}),
            now=NOON,
        )
    )


def _tools(incident):
    return [e.tool for e in incident.events]


def test_ok_on_attempt_1_resolves_without_notify(plan):
    inc = _run(CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, ["I'm fine"])
    assert inc.status == "resolved"
    assert "notify_caretaker" not in _tools(inc)
    resolve = [e for e in inc.events if e.tool == "resolve"]
    assert resolve[0].detail["reason"] == "alexa_checkin_ok"
    assert resolve[0].detail["attempt"] == 1


def test_ok_on_attempt_2_resolves_without_notify(plan):
    inc = _run(
        CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, ["", "I'm ok"]
    )
    assert inc.status == "resolved"
    assert "notify_caretaker" not in _tools(inc)
    checkins = [e for e in inc.events if e.tool == "alexa_checkin"]
    assert len(checkins) == 2
    assert checkins[1].detail["attempt"] == 2
    assert checkins[1].detail["reply_kind"] == "ok"
    assert checkins[1].detail["response_intent"] == "clear_ok"
    assert checkins[1].detail["intent_label"] == "Clear OK"


def test_soft_ok_without_okay_resolves(plan):
    inc = _run(
        CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, ["don't worry"]
    )
    assert inc.status == "resolved"
    assert "notify_caretaker" not in _tools(inc)
    chk = next(e for e in inc.events if e.tool == "alexa_checkin")
    assert chk.detail["response_intent"] == "clear_ok"
    assert chk.detail["reply_raw"] == "don't worry"


def test_mixed_hurt_does_not_clear_and_notifies(plan):
    inc = _run(
        CueEvent(kind="no_movement", confidence=0.9, detail={}),
        plan,
        ["I'm okay but I think I'm hurt"],
    )
    assert inc.status != "resolved"
    assert "notify_caretaker" in _tools(inc)
    chk = next(e for e in inc.events if e.tool == "alexa_checkin")
    assert chk.detail["response_intent"] == "needs_human"
    assert chk.detail["intent_label"] == "Needs human"
    notify = next(e for e in inc.events if e.tool == "notify_caretaker")
    assert notify.detail["basis"] == "needs_human"
    jump = [e for e in inc.events if e.tool == "jump"]
    assert jump and jump[0].detail["reason"] == "needs_human"


def test_unclear_groan_reasks_then_escalates(plan):
    inc = _run(
        CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, ["nngh", "ugh"]
    )
    assert inc.status != "resolved"
    checkins = [e for e in inc.events if e.tool == "alexa_checkin"]
    assert len(checkins) == 2
    assert all(e.detail["response_intent"] == "unclear" for e in checkins)
    assert "notify_caretaker" in _tools(inc)
    assert not any(e.tool == "resolve" for e in inc.events)


def test_silence_advances_to_notify_then_call(plan):
    inc = _run(CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, [])
    tools = _tools(inc)
    assert "alexa_checkin" in tools and "wait_window" in tools
    assert "notify_caretaker" in tools and "request_call" in tools
    notify = next(e for e in inc.events if e.tool == "notify_caretaker")
    assert notify.detail["basis"] == "no_response_escalation"
    assert notify.detail["channels"] == ["alexa_mobile"]
    assert notify.detail["surface"] == "alexa_mobile"
    assert notify.detail["fsm_state"] == "family_paged"
    assert notify.detail["inform_card"]["countdown_sec"] == 180
    assert len(notify.detail["inform_card"]["actions"]) == 3
    call = next(e for e in inc.events if e.tool == "request_call")
    assert call.detail["simulated"] is True
    assert call.detail["phone_e164"] == "+12125550176"
    # request_call is a stub: no dial_contact tool ever runs
    assert "dial_contact" not in tools


def test_call_caregiver_jumps_to_notify(plan):
    inc = _run(
        CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, ["yes call Anoop"]
    )
    tools = _tools(inc)
    assert "notify_caretaker" in tools
    # wait_window was jumped over
    assert "wait_window" not in tools
    jump = [e for e in inc.events if e.tool == "jump"]
    assert jump and jump[0].detail["reason"] == "call_caregiver"


def test_emergency_off_never_fires_and_is_audited(plan):
    inc = _run(CueEvent(kind="no_movement", confidence=0.9, detail={}), plan, [])
    em = [e for e in inc.events if e.tool == "emergency"]
    assert not em or em[0].detail.get("executed") is not True
    jumps = [e for e in inc.events if e.tool == "jump"]
    assert any(j.detail["reason"] == "emergency_disabled_fail_closed" for j in jumps)
    assert inc.status == "exhausted"


def test_wait_window_logs_policy_and_occlusion_hold(plan):
    cue = CueEvent(kind="no_movement", confidence=0.9, detail={"occluded_during_wait": True})
    inc = _run(cue, plan, [])
    wait = next(e for e in inc.events if e.tool == "wait_window")
    assert wait.detail["occluded_hold"] is True
    assert wait.detail["policy"] == "hold_and_restart_on_recovery"
