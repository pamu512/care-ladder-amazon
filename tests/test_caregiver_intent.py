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
        "got it, on my way",
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
    assert set(CAREGIVER_INTENT_LABELS) == {
        "im_on_it",
        "call_mom_now",
        "pass_to_next",
        "outcome",
        "unclear",
    }
