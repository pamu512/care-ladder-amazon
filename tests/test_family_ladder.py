"""Family escalation ladder: order, evidence, local responder, mid-rung defer, exhaust."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_ladder.channels.care_conversation import CareConversation, T_NEXT, T_REPROMPT
from care_ladder.channels.caregiver_intent import (
    classify_caregiver_intent,
    classify_local_outcome,
)
from care_ladder.models import RosterEntry
from care_ladder.plan_loader import effective_roster, load_care_plan

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

FAMILY = [
    RosterEntry(name="Me", relationship="self"),
    RosterEntry(name="Wife", relationship="spouse"),
    RosterEntry(name="Sister", relationship="sibling"),
    RosterEntry(name="Neighbor", relationship="neighbor", local_responder=True),
]


def _open(hh: str = "hh-family") -> CareConversation:
    conv = CareConversation(household_id=hh, roster=FAMILY)
    conv.start_speaker(
        incident_id="inc-1", cue_kind="no_movement", cue_text="stillness", now=T0
    )
    conv.expire_to_family_paged(
        reason="silence",
        blurred_frame_ref="blur-1",
        cue_text="Resident still for 4 minutes",
        countdown_sec=180,
        now=T0,
    )
    return conv


def _advance_to(conv: CareConversation, name: str) -> None:
    now = T0
    while conv.current_entry.name != name and conv.state not in {
        "ladder_exhausted",
        "defer_failed",
        "closed",
    }:
        now = now + timedelta(seconds=T_REPROMPT + T_NEXT)
        conv.tick(now)


def test_amazon_plan_loads_me_wife_sister_neighbor():
    plan = load_care_plan(Path("configs/amazon_demo_home.yaml"))
    names = [e.name for e in effective_roster(plan)]
    assert names == ["Me", "Wife", "Sister", "Neighbor"]
    neighbor = effective_roster(plan)[-1]
    assert neighbor.relationship == "neighbor"
    assert neighbor.local_responder is True


def test_soft_timers_walk_ladder_in_roster_order():
    conv = _open()
    seen: list[str] = [conv.current_entry.name]
    assert seen == ["Me"]
    assert conv.state == "family_paged"

    now = T0
    for expected in ("Wife", "Sister", "Neighbor"):
        now = now + timedelta(seconds=T_REPROMPT)
        assert conv.tick(now) == "soft_reprompt"
        now = now + timedelta(seconds=T_NEXT)
        state = conv.tick(now)
        assert state == "family_paged"
        assert conv.current_entry.name == expected
        seen.append(expected)
        nxt = [e for e in conv.audit_events() if e.tool == "soft_next"][-1]
        assert nxt.detail["next_contact"] == expected
        assert "not a phone call" in nxt.detail["phrase"].lower()
        assert conv.start_call(1) == "family_paged"

    assert seen == ["Me", "Wife", "Sister", "Neighbor"]
    assert "calling_1" not in {e.tool for e in conv.audit_events()}
    assert "request_call" not in {e.tool for e in conv.audit_events()}


def test_alert_carries_evidence_payload():
    conv = _open()
    ev = conv.evidence_payload(T0)
    assert ev["cue_kind"] == "no_movement"
    assert ev["cue_at"]
    assert ev["time_since_cue_sec"] == 0
    assert ev["missed_checkins"] >= 1
    assert ev["already_tried"] == []
    page = next(e for e in conv.audit_events() if e.tool == "family_paged")
    assert page.detail["evidence"]["cue_kind"] == "no_movement"
    assert "evidence" in conv.inform_card

    conv.tick(T0 + timedelta(seconds=T_REPROMPT))
    conv.tick(T0 + timedelta(seconds=T_REPROMPT + T_NEXT))
    later = conv.evidence_payload(T0 + timedelta(seconds=T_REPROMPT + T_NEXT))
    assert later["time_since_cue_sec"] == T_REPROMPT + T_NEXT
    names = [t["name"] for t in later["already_tried"]]
    assert names == ["Me"]
    assert later["already_tried"][0]["result"] == "no_response"
    nxt = next(e for e in conv.audit_events() if e.tool == "soft_next")
    assert nxt.detail["evidence"]["already_tried"][0]["name"] == "Me"


def test_local_responder_alert_states_basis_for_concern():
    conv = _open()
    _advance_to(conv, "Neighbor")
    assert conv.current_entry.local_responder is True
    page = [e for e in conv.audit_events() if e.tool == "family_paged"][-1]
    phrase = page.detail["phrase"]
    assert "basis for concern" in phrase.lower()
    assert "no_movement" in phrase or "still" in phrase.lower()
    assert "Me" in phrase and "Wife" in phrase and "Sister" in phrase
    assert "—" not in phrase
    assert page.detail["evidence"]["already_tried"]
    assert conv.inform_card["local_responder"] is True


def test_local_responder_im_going_then_okay_reports_primary():
    conv = _open()
    _advance_to(conv, "Neighbor")
    assert classify_caregiver_intent("I'm going") == "on_my_way"
    state = conv.local_going(by="Neighbor", raw="I'm going")
    assert conv.escalation_stopped is True
    assert conv.owner == "Neighbor"
    assert state == "family_paged"
    going = next(e for e in conv.audit_events() if e.tool == "local_going")
    assert going.detail["by"] == "Neighbor"
    assert going.detail["ask_outcome"] is True

    assert classify_local_outcome("she's okay") == "okay"
    closed = conv.report_local_outcome("she's okay", by="Neighbor")
    assert closed == "closed"
    report = next(e for e in conv.audit_events() if e.tool == "primary_report")
    assert report.detail["outcome"] == "okay"
    assert report.detail["from"] == "Neighbor"
    assert report.detail["to"] == "Me"
    assert report.detail["role"] == "local_responder"
    assert "okay" in report.detail["phrase"].lower()
    assert "—" not in report.detail["phrase"]


def test_local_responder_needs_help_reports_primary():
    conv = _open("hh-help")
    _advance_to(conv, "Neighbor")
    conv.local_going(by="Neighbor", raw="I'm going")
    assert classify_local_outcome("needs help") == "needs_help"
    state = conv.report_local_outcome("needs help", by="Neighbor")
    assert state == "family_paged"
    report = next(e for e in conv.audit_events() if e.tool == "primary_report")
    assert report.detail["outcome"] == "needs_help"
    assert report.detail["to"] == "Me"
    assert report.detail["ask_primary"] is True
    assert conv.state != "closed"


def test_defer_from_mid_ladder():
    conv = _open("hh-mid")
    _advance_to(conv, "Sister")
    assert conv.current_entry.name == "Sister"
    state = conv.defer(
        "Neighbor",
        by="Sister",
        raw="call Neighbor instead",
        now=T0 + timedelta(hours=1),
    )
    assert state == "deferred"
    assert conv.deferred_to == "Neighbor"
    ev = next(e for e in conv.audit_events() if e.tool == "defer")
    assert ev.detail["alternate_contact"] == "Neighbor"
    assert ev.detail["by"] == "Sister"
    evidence = ev.detail["notify_x"]["evidence"]
    tried = [t["name"] for t in evidence["already_tried"]]
    assert "Me" in tried and "Wife" in tried
    assert evidence["cue_kind"] == "no_movement"
    assert "Sister" not in tried


def test_ladder_exhaustion_asks_primary_and_checks_monitored():
    conv = _open("hh-ex")
    now = T0
    for _ in range(len(FAMILY)):
        now = now + timedelta(seconds=T_REPROMPT)
        conv.tick(now, monitored_raw="I'm fine")
        now = now + timedelta(seconds=T_NEXT)
        conv.tick(now, monitored_raw="I'm fine")
    assert conv.state == "ladder_exhausted"
    assert conv.monitored_report == "monitored_ok"
    ev = next(e for e in conv.audit_events() if e.tool == "ladder_exhausted")
    assert ev.detail["ask_primary"] is True
    assert ev.detail["parallel_checkin"] is True
    assert ev.detail["monitored_report"] == "monitored_ok"
    assert ev.detail["direction_actions"] == [
        "try_other",
        "try_again",
        "on_my_way",
        "false_alarm",
        "snooze_alert",
    ]
    tried = [t["name"] for t in ev.detail["tried"]]
    assert tried == ["Me", "Wife", "Sister", "Neighbor"]
    assert conv.start_call(1) == "ladder_exhausted"
    assert "calling_1" not in {e.tool for e in conv.audit_events()}

    again = conv.primary_direction(
        "try_other",
        by="Me",
        raw="try Wife",
        now=now + timedelta(seconds=1),
        alternate="Wife",
    )
    assert again == "deferred"
    assert conv.deferred_to == "Wife"
