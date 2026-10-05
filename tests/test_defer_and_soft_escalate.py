"""FSM edges: caregiver voice set, soft-escalate timers, defer / defer-fail."""

from datetime import datetime, timedelta, timezone

from care_ladder.channels.care_conversation import CareConversation
from care_ladder.channels.caregiver_intent import spoken_confirmation
from care_ladder.channels.response_intent import classify_response_intent


T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _paged(hh="hh-defer") -> CareConversation:
    conv = CareConversation(household_id=hh, next_contact="Secondary contact")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement", cue_text="stillness")
    conv.expire_to_family_paged(
        reason="silence",
        blurred_frame_ref="blur-1",
        cue_text="Resident still for 4 minutes",
        countdown_sec=180,
        now=T0,
    )
    return conv


def test_false_alarm_closes_with_spoken_confirm():
    conv = _paged()
    state = conv.false_alarm(by="Primary contact", raw="false alarm")
    assert state == "closed"
    assert conv.escalation_stopped is True
    assert conv.acked_action == "false_alarm"
    tools = [e.tool for e in conv.audit_events()]
    assert "false_alarm" in tools
    assert conv.last_spoken == spoken_confirmation("false_alarm")
    assert "—" not in conv.last_spoken


def test_on_my_way_stops_escalation_and_asks_outcome():
    conv = _paged()
    state = conv.on_my_way(by="Primary contact", raw="on my way")
    assert state == "family_paged"
    assert conv.escalation_stopped is True
    assert conv.owner == "Primary contact"
    assert conv.acked_action == "on_my_way"
    assert conv.tick(T0 + timedelta(seconds=120)) == "family_paged"
    assert conv.start_call(1) == "family_paged"
    ev = next(e for e in conv.audit_events() if e.tool == "on_my_way")
    assert ev.detail["ask_outcome"] is True
    assert conv.last_spoken == spoken_confirmation("on_my_way")


def test_need_second_look_reenters_speaker_window():
    conv = _paged()
    state = conv.need_second_look(by="Primary contact", raw="check again")
    assert state == "speaker_window"
    assert conv.incident_id == "inc-1"
    assert conv.escalation_stopped is False
    assert "need_second_look" in [e.tool for e in conv.audit_events()]


def test_snooze_then_timer_returns_to_family_paged():
    conv = _paged()
    assert conv.snooze(by="Primary contact", raw="snooze", now=T0, t_snooze=300) == "snoozed"
    assert conv.tick(T0 + timedelta(seconds=299)) == "snoozed"
    assert conv.tick(T0 + timedelta(seconds=300)) == "family_paged"
    tools = [e.tool for e in conv.audit_events()]
    assert "snooze" in tools
    assert tools.count("family_paged") >= 2


def test_soft_escalate_reprompt_then_next_roster_never_dials():
    conv = _paged()
    assert conv.tick(T0 + timedelta(seconds=59)) == "family_paged"
    assert conv.tick(T0 + timedelta(seconds=60)) == "soft_reprompt"
    rep = next(e for e in conv.audit_events() if e.tool == "soft_reprompt")
    assert "Still waiting" in rep.detail["phrase"]
    assert conv.tick(T0 + timedelta(seconds=119)) == "soft_reprompt"
    assert conv.tick(T0 + timedelta(seconds=120)) == "soft_next"
    nxt = next(e for e in conv.audit_events() if e.tool == "soft_next")
    assert nxt.detail["next_contact"] == "Secondary contact"
    assert "not a phone call" in nxt.detail["phrase"].lower()
    later = conv.tick(T0 + timedelta(seconds=600))
    assert later == "soft_next"
    assert conv.start_call(1) == "soft_next"
    assert "calling_1" not in {e.tool for e in conv.audit_events()}
    assert "request_call" not in {e.tool for e in conv.audit_events()}


def test_defer_pages_alternate_with_deadline():
    conv = _paged()
    state = conv.defer(
        "Secondary contact",
        by="Primary contact",
        raw="call Secondary contact instead",
        now=T0,
        t_defer=90,
    )
    assert state == "deferred"
    assert conv.deferred_to == "Secondary contact"
    assert conv.defer_deadline == T0 + timedelta(seconds=90)
    ev = next(e for e in conv.audit_events() if e.tool == "defer")
    assert ev.detail["alternate_contact"] == "Secondary contact"
    assert ev.detail["notify_x"]["simulated"] is True
    assert "stillness" in str(ev.detail["notify_x"]["context"]).lower() or ev.detail[
        "notify_x"
    ]["cue_text"]
    spoken = spoken_confirmation("defer_escalation", alternate="Secondary contact")
    assert conv.last_spoken == spoken
    assert "Secondary contact" in spoken
    assert "—" not in spoken


def test_deferred_alternate_ack_stops_ladder():
    conv = _paged()
    conv.defer("Secondary contact", by="Primary contact", raw="call X instead", now=T0)
    state = conv.ack("im_on_it", by="Secondary contact", raw="I'm on it")
    assert conv.escalation_stopped is True
    assert conv.owner == "Secondary contact"
    assert state == "deferred"
    assert conv.tick(T0 + timedelta(seconds=120)) == "deferred"


def test_defer_fail_asks_primary_and_checks_monitored_in_parallel():
    conv = _paged()
    conv.defer("Secondary contact", by="Primary contact", raw="call X instead", now=T0, t_defer=90)
    state = conv.tick(T0 + timedelta(seconds=90), monitored_raw="I'm fine")
    assert state == "defer_failed"
    assert conv.monitored_report == "monitored_ok"
    assert classify_response_intent("I'm fine") == "clear_ok"
    ev = next(e for e in conv.audit_events() if e.tool == "defer_failed")
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
    assert ev.detail["deferred_to"] == "Secondary contact"


def test_defer_fail_silent_monitored_is_monitored_silent():
    conv = _paged("hh-silent")
    conv.defer("Neighbor", by="Primary contact", raw="call Neighbor instead", now=T0, t_defer=90)
    conv.tick(T0 + timedelta(seconds=90), monitored_raw="")
    assert conv.monitored_report == "monitored_silent"


def test_defer_fail_needs_help_token():
    conv = _paged("hh-hurt")
    conv.defer("Neighbor", by="Primary contact", raw="try Neighbor instead", now=T0, t_defer=90)
    conv.tick(T0 + timedelta(seconds=90), monitored_raw="I think I'm hurt")
    assert conv.monitored_report == "monitored_needs_help"


def test_primary_direction_try_again_and_try_other():
    conv = _paged("hh-dir")
    conv.defer("Secondary contact", by="Primary contact", raw="call X instead", now=T0, t_defer=90)
    conv.tick(T0 + timedelta(seconds=90), monitored_raw="")
    again = conv.primary_direction(
        "try_again", by="Primary contact", raw="try them again", now=T0 + timedelta(seconds=91)
    )
    assert again == "deferred"
    assert conv.deferred_to == "Secondary contact"
    conv.tick(T0 + timedelta(seconds=181), monitored_raw="")
    other = conv.primary_direction(
        "try_other",
        by="Primary contact",
        raw="try the neighbor",
        now=T0 + timedelta(seconds=182),
        alternate="Neighbor",
    )
    assert other == "deferred"
    assert conv.deferred_to == "Neighbor"


def test_primary_direction_false_alarm_and_on_my_way():
    conv = _paged("hh-fa")
    conv.defer("X", by="Primary contact", raw="call X instead", now=T0, t_defer=90)
    conv.tick(T0 + timedelta(seconds=90), monitored_raw="")
    assert conv.primary_direction("false_alarm", by="Primary contact", raw="false alarm") == "closed"

    conv2 = _paged("hh-omw")
    conv2.defer("X", by="Primary contact", raw="call X instead", now=T0, t_defer=90)
    conv2.tick(T0 + timedelta(seconds=90), monitored_raw="")
    state = conv2.primary_direction("on_my_way", by="Primary contact", raw="on my way")
    assert state == "defer_failed"
    assert conv2.escalation_stopped is True
    assert conv2.acked_action == "on_my_way"


def test_household_status_open_and_quiet():
    conv = _paged("hh-status")
    conv.on_my_way(by="Primary contact", raw="on my way")
    status = conv.household_status()
    assert status["last_cue"]["kind"] == "no_movement"
    assert status["last_ack"]["action"] == "on_my_way"
    assert status["open"] is True
    assert "quiet_since" not in status or status["quiet_since"] is None

    conv.record_outcome("Called Mom, she's fine")
    closed = conv.household_status()
    assert closed["open"] is False
    assert closed["quiet_since"] is not None
    assert closed["last_ack"]["action"] == "on_my_way"
