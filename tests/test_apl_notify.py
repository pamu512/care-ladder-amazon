"""APL notify card: thumbnail, household, time since cue, voice actions."""

from care_ladder.channels.apl_notify import APL_VOICE_ACTIONS, apl_notify_card


def test_apl_card_slots_and_voice_actions():
    card = apl_notify_card(
        thumbnail="blurred:inc-1",
        household_label="amazon-demo-1 · Resident",
        time_since_cue_sec=45,
        cue_text="Resident still for 4 minutes",
        countdown_sec=180,
        next_contact="Secondary contact",
    )
    assert card["thumbnail"] == "blurred:inc-1"
    assert card["householdLabel"] == "amazon-demo-1 · Resident"
    assert card["time_since_cue_sec"] == 45
    assert card["timeSinceCue"] == "just now"
    assert card["cueText"] == "Resident still for 4 minutes"
    ids = [a["id"] for a in card["actions"]]
    for needed in APL_VOICE_ACTIONS:
        assert needed in ids
    for legacy in ("im_on_it", "call_mom_now", "pass_to_next"):
        assert legacy in ids
    blob = " ".join(a["label"] for a in card["actions"])
    assert "—" not in blob and "–" not in blob
    assert card["apl"]["type"] == "APL"
    assert "notify" in card["datasources"]
    ds = card["datasources"]["notify"]
    assert ds["thumbnail"] == "blurred:inc-1"
    assert ds["householdLabel"] == card["householdLabel"]


def test_time_since_cue_renders_minutes():
    card = apl_notify_card(
        thumbnail="last-frame-placeholder",
        household_label="amazon-demo-1",
        time_since_cue_sec=240,
        cue_text="stillness",
        countdown_sec=180,
    )
    assert card["timeSinceCue"] == "4 min ago"
    assert card["thumbnail"] == "last-frame-placeholder"
