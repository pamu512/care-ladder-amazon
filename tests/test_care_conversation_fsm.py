"""CareConversation FSM: shared family-chat beats for the Alexa session."""

from datetime import datetime, timezone

from care_ladder.channels.care_conversation import (
    ACK_ACTIONS,
    CareConversation,
    INFORM_ACTIONS,
    inform_card,
)


def test_inform_card_has_blurred_frame_countdown_and_three_actions():
    card = inform_card(
        blurred_frame_ref="frame-blur-1",
        cue_text="Resident still for 4 minutes",
        countdown_sec=180,
    )
    assert card["blurred_frame_ref"] == "frame-blur-1"
    assert card["cue_text"] == "Resident still for 4 minutes"
    assert card["countdown_sec"] == 180
    assert len(card["actions"]) == 3
    ids = [a["id"] for a in card["actions"]]
    assert ids == ["im_on_it", "call_mom_now", "pass_to_next"]
    labels = [a["label"] for a in card["actions"]]
    assert labels[0] == "I'm on it - call her myself"
    assert labels[1] == "Call Mom now"
    assert "Can't take it - go to" in labels[2]
    blob = " ".join(labels)
    assert "—" not in blob and "–" not in blob


def test_inform_card_formats_next_contact_on_pass_action():
    card = inform_card(
        "f", "c", 60, next_contact="Secondary contact"
    )
    assert card["actions"][2]["label"] == "Can't take it - go to Secondary contact"


def test_cue_opens_speaker_window():
    conv = CareConversation(household_id="amazon-demo-1")
    state = conv.start_speaker(
        incident_id="inc-1", cue_kind="no_movement", cue_text="stillness"
    )
    assert state == "speaker_window"
    assert conv.state == "speaker_window"
    assert conv.incident_id == "inc-1"


def test_resident_clear_ok_closes_without_family_paged():
    conv = CareConversation(household_id="amazon-demo-1")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    state = conv.close_from_speaker(reason="clear_ok", raw="don't worry")
    assert state == "closed"
    tools = [e.tool for e in conv.audit_events()]
    assert "family_paged" not in tools
    assert conv.state == "closed"
    assert all(e.at is not None for e in conv.audit_events())


def test_silence_or_needs_human_pages_family_with_inform_card():
    conv = CareConversation(household_id="amazon-demo-1")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    state = conv.expire_to_family_paged(
        reason="needs_human",
        blurred_frame_ref="blur-9",
        cue_text="Resident said they are hurt",
        countdown_sec=180,
    )
    assert state == "family_paged"
    assert conv.inform_card["blurred_frame_ref"] == "blur-9"
    assert conv.inform_card["countdown_sec"] == 180
    assert len(conv.inform_card["actions"]) == 3
    tools = [e.tool for e in conv.audit_events()]
    assert "family_paged" in tools


def test_pressure_then_calling_ladder():
    conv = CareConversation(household_id="amazon-demo-1")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence",
        blurred_frame_ref="b",
        cue_text="no reply",
        countdown_sec=180,
    )
    assert conv.pressure() == "pressure"
    assert conv.start_call(1) == "calling_1"
    assert conv.start_call(2) == "calling_2"


def test_ack_first_wins_stops_escalation():
    conv = CareConversation(household_id="amazon-demo-1")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    first = conv.ack("im_on_it", by="Primary contact", raw="I'm on it")
    assert first == conv.state
    assert conv.escalation_stopped is True
    assert conv.owner == "Primary contact"
    assert conv.acked_action == "im_on_it"
    later = conv.ack("call_mom_now", by="Secondary contact", raw="Call Mom now")
    assert later == first
    assert conv.owner == "Primary contact"
    assert conv.acked_action == "im_on_it"
    assert conv.pressure() == first
    assert conv.start_call(1) == first
    assert "calling_1" not in {e.tool for e in conv.audit_events()}


def test_outcome_closes_with_documentation_and_timestamps():
    conv = CareConversation(household_id="amazon-demo-1")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    conv.ack("im_on_it", by="Primary contact", raw="I'm on it")
    state = conv.record_outcome("Called Mom, she's fine")
    assert state == "closed"
    assert conv.documentation == "Called Mom, she's fine"
    events = conv.audit_events()
    assert all(e.at is not None for e in events)
    stamps = [e.at for e in events]
    assert stamps == sorted(stamps)
    close = next(e for e in events if e.tool == "closed")
    assert close.detail["documentation"] == "Called Mom, she's fine"
    assert close.at.tzinfo is not None


def test_new_cue_while_open_joins_same_thread():
    CareConversation.reset_registry()
    first = CareConversation.for_household("amazon-demo-1")
    first.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    second = CareConversation.for_household("amazon-demo-1")
    state = second.start_speaker(incident_id="inc-2", cue_kind="distress_heuristic")
    assert second is first
    assert state == "speaker_window"
    assert first.incident_id == "inc-1"


def test_closed_household_starts_a_new_conversation():
    CareConversation.reset_registry()
    first = CareConversation.for_household("amazon-demo-1")
    first.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    first.close_from_speaker(reason="clear_ok")
    second = CareConversation.for_household("amazon-demo-1")
    assert second is not first
    second.start_speaker(incident_id="inc-2", cue_kind="no_movement")
    assert second.incident_id == "inc-2"


def test_closed_conversation_evicted_from_registry():
    CareConversation.reset_registry()
    conv = CareConversation.for_household("hh-evict")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.close_from_speaker(reason="clear_ok")
    assert conv.state == "closed"
    assert "hh-evict" not in CareConversation._by_household


def test_outcome_evicts_household_entry():
    CareConversation.reset_registry()
    conv = CareConversation.for_household("hh-out")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    conv.ack("im_on_it", by="Primary contact")
    conv.record_outcome("Called Mom, she's fine")
    assert conv.state == "closed"
    assert "hh-out" not in CareConversation._by_household


def test_idle_outcome_is_rejected():
    conv = CareConversation(household_id="hh-idle")
    state = conv.record_outcome("premature close")
    assert state == "idle"
    assert conv.state == "idle"
    assert conv.documentation is None
    assert conv.owner is None
    assert not any(e.tool == "closed" for e in conv.audit_events())


def test_paged_outcome_without_ack_is_rejected():
    conv = CareConversation(household_id="hh-paged")
    conv.start_speaker(incident_id="inc-1", cue_kind="no_movement")
    conv.expire_to_family_paged(
        reason="silence", blurred_frame_ref="b", cue_text="c", countdown_sec=180
    )
    state = conv.record_outcome("no ack yet")
    assert state == "family_paged"
    assert conv.state == "family_paged"
    assert conv.documentation is None
    assert conv.owner is None


def test_ack_actions_match_inform_card_ids():
    assert ACK_ACTIONS == tuple(a["id"] for a in INFORM_ACTIONS)


def test_fsm_events_carry_utc_at():
    conv = CareConversation(household_id="h")
    conv.start_speaker(incident_id="i", cue_kind="no_movement")
    ev = conv.audit_events()[0]
    assert ev.at is not None
    assert ev.at.tzinfo == timezone.utc
    assert isinstance(ev.at, datetime)
