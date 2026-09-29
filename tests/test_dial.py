from pathlib import Path

from care_ladder.channels.dial import StubDialer, next_rung_after_no_answer
from care_ladder.plan_loader import load_care_plan


def test_stub_no_answer_then_escalate_index():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    assert dialer.dial(plan.caregiver, ring_sec=1).status == "no_answer"
    idx = next(
        i
        for i, r in enumerate(plan.rungs)
        if r.tool == "dial_contact" and r.params.get("contact") == "caregiver"
    )
    nxt = next_rung_after_no_answer(plan, idx)
    assert plan.rungs[nxt].params.get("contact") in {"secondary", "caregiver"} or plan.rungs[
        nxt
    ].tool in {"dial_contact", "emergency"}


def test_next_rung_skips_disabled_emergency():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    secondary_idx = next(
        i
        for i, r in enumerate(plan.rungs)
        if r.tool == "dial_contact" and r.params.get("contact") == "secondary"
    )
    nxt = next_rung_after_no_answer(plan, secondary_idx)
    # emergency is enabled: false — fail-closed, must not select it
    assert nxt is None
    emergency = next(r for r in plan.rungs if r.tool == "emergency")
    assert emergency.params.get("enabled") is False


def test_stub_secondary_answered_and_contact_id():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    dialer = StubDialer(behavior={"caregiver": "no_answer", "secondary": "answered"})
    result = dialer.dial(plan.secondary, ring_sec=1)
    assert result.status == "answered"
    assert result.contact_id == "secondary"
