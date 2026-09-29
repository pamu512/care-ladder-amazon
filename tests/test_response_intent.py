"""Fail-closed check-in response intent: clear_ok / needs_human / unclear."""

from care_ladder.channels.response_intent import (
    INTENT_LABELS,
    classify_response_intent,
    intent_to_reply_kind,
)


def test_soft_ok_without_the_word_okay():
    for phrase in (
        "don't worry",
        "dont worry",
        "I'm fine",
        "leave me alone",
        "I'm good",
        "all good",
    ):
        assert classify_response_intent(phrase) == "clear_ok", phrase


def test_explicit_okay_still_clear_when_unmixed():
    for phrase in ("ok", "okay", "I'm ok, just resting", "yes I'm okay"):
        assert classify_response_intent(phrase) == "clear_ok", phrase


def test_mixed_hurt_is_needs_human_not_ok():
    phrase = "I'm okay but I think I'm hurt"
    assert classify_response_intent(phrase) == "needs_human"
    assert intent_to_reply_kind("needs_human", phrase) != "ok"


def test_fall_and_help_without_call_are_needs_human():
    assert classify_response_intent("I fell") == "needs_human"
    assert classify_response_intent("help but don't call") == "needs_human"


def test_explicit_call_request_is_needs_human():
    assert classify_response_intent("yes call Anoop") == "needs_human"
    assert intent_to_reply_kind("needs_human", "yes call Anoop") == "call_caregiver"


def test_groan_empty_and_garbage_are_unclear():
    for phrase in ("", "   ", "nngh", "ugh", "uh", "um", "...", "asdfgh"):
        assert classify_response_intent(phrase) == "unclear", repr(phrase)


def test_never_invent_ok_from_a_groan():
    assert intent_to_reply_kind(classify_response_intent("nngh"), "nngh") == "silence"
    assert classify_response_intent("nngh") != "clear_ok"


def test_book_is_not_ok_via_substring():
    assert classify_response_intent("book") == "unclear"


def test_intent_labels_are_demo_visible():
    assert INTENT_LABELS["clear_ok"] == "Clear OK"
    assert INTENT_LABELS["needs_human"] == "Needs human"
    assert INTENT_LABELS["unclear"] == "Unclear"


def test_llm_hook_stays_off_by_default(monkeypatch):
    called = {"n": 0}

    def _hook(_raw: str):
        called["n"] += 1
        return "clear_ok"

    monkeypatch.delenv("CARE_LADDER_INTENT_LLM", raising=False)
    assert classify_response_intent("nngh", llm_classify=_hook) == "unclear"
    assert called["n"] == 0

    monkeypatch.setenv("CARE_LADDER_INTENT_LLM", "1")
    assert classify_response_intent("nngh", llm_classify=_hook) == "clear_ok"
    assert called["n"] == 1
