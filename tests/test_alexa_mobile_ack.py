"""Alexa mobile caregiver notify / ack / outcome via MCP + session_snapshot."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.channels.care_conversation import CareConversation

from test_mcp_server import _assert_session_snapshot, _init_and_caller, EXPECTED_TOOLS


def test_notify_payload_is_alexa_mobile_inform_card():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        note = call("notify_caretaker", {"household_id": "amazon-demo-1", "incident_id": iid})
        assert note["channels"] == ["alexa_mobile"]
        assert note["surface"] == "alexa_mobile"
        assert note["fsm_state"] == "family_paged"
        card = note["inform_card"]
        assert card["blurred_frame_ref"]
        assert card["countdown_sec"] == 180
        assert [a["id"] for a in card["actions"]] == [
            "im_on_it",
            "call_mom_now",
            "pass_to_next",
        ]
        _assert_session_snapshot(note, "amazon-demo-1", iid)

        inc = client.get(f"/incidents/{iid}").json()
        ev = next(e for e in inc["events"] if e["tool"] == "notify_caretaker")
        assert ev["at"]
        assert ev["detail"]["surface"] == "alexa_mobile"
        assert ev["detail"]["fsm_state"] == "family_paged"
        assert "fire_tv" not in ev["detail"]["channels"]


def test_caregiver_ack_stops_call_and_outcome_closes():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})

        ack = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "utterance": "I'm on it"},
        )
        assert ack["acked"] is True
        assert ack["action"] == "im_on_it"
        assert ack["escalation_stopped"] is True
        assert ack["channel"] == "alexa_mobile"
        assert ack["ask_outcome"] is True
        _assert_session_snapshot(ack, hh, iid)

        skipped = call("request_call", {"household_id": hh, "incident_id": iid})
        assert skipped.get("skipped") is True
        assert skipped.get("reason") == "escalation_stopped"

        out = call(
            "caregiver_outcome",
            {"household_id": hh, "incident_id": iid, "text": "Called Mom, she's fine"},
        )
        assert out["status"] == "resolved"
        assert out["documentation"] == "Called Mom, she's fine"
        _assert_session_snapshot(out, hh, iid)

        inc = client.get(f"/incidents/{iid}").json()
        assert inc["status"] == "resolved"
        assert inc["acked_by"] == "Primary contact"
        assert all(e.get("at") for e in inc["events"])
        resolve = next(e for e in inc["events"] if e["tool"] == "resolve")
        assert resolve["detail"]["documentation"] == "Called Mom, she's fine"
        assert resolve["detail"]["channel"] == "alexa_mobile"
        ack_ev = next(e for e in inc["events"] if e["tool"] == "caregiver_ack")
        assert ack_ev["detail"]["channel"] == "alexa_mobile"


def test_caregiver_ack_first_wins():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        first = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "action": "im_on_it"},
        )
        second = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "action": "call_mom_now"},
        )
        assert first["action"] == "im_on_it"
        assert second["action"] == "im_on_it"
        assert second.get("already_acked") is True


def test_unclear_ack_does_not_stop_ladder():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        bad = call(
            "caregiver_ack",
            {"household_id": hh, "incident_id": iid, "utterance": "nngh"},
        )
        assert bad.get("error") == "unclear_ack"
        call_out = call("request_call", {"household_id": hh, "incident_id": iid})
        assert call_out.get("simulated") is True
        assert call_out.get("skipped") is not True


def test_mcp_lists_caregiver_tools():
    assert "caregiver_ack" in EXPECTED_TOOLS
    assert "caregiver_outcome" in EXPECTED_TOOLS


def test_caregiver_outcome_rejected_before_ack():
    CareConversation.reset_registry()
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        hh = "amazon-demo-1"
        out = call(
            "caregiver_outcome",
            {"household_id": hh, "incident_id": iid, "text": "too early"},
        )
        assert out.get("error") == "outcome_requires_ack"
        assert out.get("fsm_state") != "closed"
        inc = client.get(f"/incidents/{iid}").json()
        assert inc["status"] != "resolved"

        call("notify_caretaker", {"household_id": hh, "incident_id": iid})
        still_early = call(
            "caregiver_outcome",
            {"household_id": hh, "incident_id": iid, "text": "still too early"},
        )
        assert still_early.get("error") == "outcome_requires_ack"
        assert still_early.get("fsm_state") == "family_paged"
        assert client.get(f"/incidents/{iid}").json()["status"] != "resolved"
