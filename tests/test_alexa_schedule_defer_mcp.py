"""MCP tools for defer, timers, HowIsHousehold, schedule pin, APL card."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.channels.care_conversation import CareConversation

from test_mcp_server import EXPECTED_TOOLS, _assert_session_snapshot, _init_and_caller


NEW_TOOLS = {
    "defer_escalation",
    "tick_care_timers",
    "how_is_household",
    "confirm_schedule_pin",
}


def test_mcp_lists_schedule_defer_tools():
    for name in NEW_TOOLS:
        assert name in EXPECTED_TOOLS


def test_notify_includes_apl_card():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        note = call("notify_caretaker", {"household_id": "amazon-demo-1", "incident_id": iid})
        card = note["apl_card"]
        assert card["thumbnail"]
        assert card["householdLabel"]
        assert "timeSinceCue" in card
        ids = [a["id"] for a in card["actions"]]
        assert "false_alarm" in ids
        assert "on_my_way" in ids
        assert "need_second_look" in ids
        assert "snooze_alert" in ids
        _assert_session_snapshot(note, "amazon-demo-1", iid)


def test_caregiver_ack_false_alarm_and_spoken():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        ack = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "utterance": "false alarm"},
        )
        assert ack["acked"] is True
        assert ack["action"] == "false_alarm"
        assert ack["fsm_state"] == "closed"
        assert "false alarm" in ack["spoken"].lower()
        _assert_session_snapshot(ack, hh, iid)


def test_defer_escalation_and_fail_tick():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        deferred = call(
            "defer_escalation",
            {
                "household_id": hh,
                "incident_id": iid,
                "alternate_contact": "Secondary contact",
                "utterance": "call Secondary contact instead",
            },
        )
        assert deferred["fsm_state"] == "deferred"
        assert deferred["alternate_contact"] == "Secondary contact"
        assert deferred["spoken"]
        _assert_session_snapshot(deferred, hh, iid)

        expired = call(
            "tick_care_timers",
            {
                "household_id": hh,
                "incident_id": iid,
                "now_iso": "2026-12-01T00:00:00+00:00",
                "monitored_utterance": "don't worry",
            },
        )
        assert expired["fsm_state"] == "defer_failed"
        assert expired["monitored_report"] == "monitored_ok"
        assert expired["ask_primary"] is True
        assert "try_other" in expired["direction_actions"]
        _assert_session_snapshot(expired, hh, iid)

        direction = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "utterance": "on my way"},
        )
        assert direction["action"] == "on_my_way"
        assert direction["escalation_stopped"] is True


def test_how_is_household_and_schedule_pin():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "utterance": "on my way"},
        )
        status = call("how_is_household", {"household_id": hh})
        assert status["last_cue"]["kind"] == "no_movement"
        assert status["last_ack"]["action"] == "on_my_way"
        assert status["open"] is True
        _assert_session_snapshot(status, hh, iid)

        pin = call(
            "confirm_schedule_pin",
            {"household_id": hh, "window": "14:00"},
        )
        assert pin["pinned"] is True
        assert pin["window"] == "14:00"
        _assert_session_snapshot(pin, hh, iid)
