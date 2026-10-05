"""Caregiver Alexa mobile utterances → ack actions / outcome / unclear."""

from care_ladder.channels.care_conversation import INFORM_ACTIONS
from care_ladder.channels.caregiver_intent import (
    CAREGIVER_INTENT_LABELS,
    classify_caregiver_intent,
)


def test_inform_card_labels_map_to_ack_actions():
    expected = {
        "I'm on it - call her myself": "im_on_it",
        "Call Mom now": "call_mom_now",
        "Can't take it - go to Secondary contact": "pass_to_next",
    }
    for action in INFORM_ACTIONS:
        label = action["label"].format(next="Secondary contact")
        assert classify_caregiver_intent(label) == expected[label]


def test_conversational_im_on_it():
    for phrase in (
        "I'm on it",
        "Im on it",
        "I'll call her myself",
        "got it",
    ):
        assert classify_caregiver_intent(phrase) == "im_on_it", phrase


def test_call_mom_now_is_not_im_on_it():
    assert classify_caregiver_intent("Call Mom now") == "call_mom_now"
    assert classify_caregiver_intent("please call mom now") == "call_mom_now"


def test_pass_to_next_variants():
    for phrase in (
        "Can't take it - go to Secondary contact",
        "cannot take it",
        "pass it on",
        "hand this off",
    ):
        assert classify_caregiver_intent(phrase) == "pass_to_next", phrase


def test_outcome_report():
    for phrase in (
        "Called Mom, she's fine",
        "I checked on her",
        "she's okay",
        "went over, all good",
    ):
        assert classify_caregiver_intent(phrase) == "outcome", phrase


def test_empty_and_garbage_are_unclear():
    for phrase in ("", "   ", "nngh", "asdfgh", "what"):
        assert classify_caregiver_intent(phrase) == "unclear", repr(phrase)


def test_labels_cover_all_buckets():
    assert set(CAREGIVER_INTENT_LABELS) >= {
        "im_on_it",
        "call_mom_now",
        "pass_to_next",
        "outcome",
        "unclear",
        "false_alarm",
        "on_my_way",
        "need_second_look",
        "snooze_alert",
        "defer_escalation",
        "how_is_household",
        "try_other",
        "try_again",
    }


def test_false_alarm_utterances():
    from care_ladder.channels.caregiver_intent import spoken_confirmation

    for phrase in ("false alarm", "it's nothing", "stand down"):
        assert classify_caregiver_intent(phrase) == "false_alarm", phrase
    spoken = spoken_confirmation("false_alarm")
    assert "false alarm" in spoken.lower()
    assert "—" not in spoken and "–" not in spoken


def test_on_my_way_is_not_im_on_it():
    from care_ladder.channels.caregiver_intent import spoken_confirmation

    for phrase in ("on my way", "I'm coming over", "heading there", "got it, on my way"):
        assert classify_caregiver_intent(phrase) == "on_my_way", phrase
    spoken = spoken_confirmation("on_my_way")
    assert "on the way" in spoken.lower()
    assert "—" not in spoken


def test_need_second_look_utterances():
    for phrase in ("need a second look", "check again", "look again"):
        assert classify_caregiver_intent(phrase) == "need_second_look", phrase


def test_snooze_alert_utterances():
    for phrase in ("snooze", "remind me later", "not now"):
        assert classify_caregiver_intent(phrase) == "snooze_alert", phrase


def test_defer_escalation_extracts_alternate_contact():
    from care_ladder.channels.caregiver_intent import extract_alternate_contact

    phrase = "call Secondary contact instead"
    assert classify_caregiver_intent(phrase) == "defer_escalation"
    assert extract_alternate_contact(phrase) == "Secondary contact"
    assert extract_alternate_contact("try the neighbor instead") == "the neighbor"
    assert extract_alternate_contact("page Neighbor") == "Neighbor"
    assert extract_alternate_contact("nngh") is None


def test_how_is_household_utterances():
    for phrase in ("how is the household", "any open alerts", "is it quiet"):
        assert classify_caregiver_intent(phrase) == "how_is_household", phrase


def test_defer_fail_direction_intents():
    assert classify_caregiver_intent("try them again") == "try_again"
    assert classify_caregiver_intent("try X again") == "try_again"
    assert classify_caregiver_intent("try the neighbor") == "try_other"
    assert classify_caregiver_intent("call the neighbor instead") == "defer_escalation"
