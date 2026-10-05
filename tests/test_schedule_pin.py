"""Lightweight repeating-window schedule pin (not fall-level)."""

from datetime import datetime, timedelta, timezone

from care_ladder.learning.schedule import N_REPEATS, ScheduleBook


T0 = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)


def test_propose_pin_after_n_repeats():
    book = ScheduleBook()
    for i in range(N_REPEATS - 1):
        out = book.observe("amazon-demo-1", "14:00", at=T0 + timedelta(days=i))
        assert out["proposed"] is False
        assert out["count"] == i + 1
    out = book.observe("amazon-demo-1", "14:00", at=T0 + timedelta(days=N_REPEATS - 1))
    assert out["proposed"] is True
    assert out["count"] == N_REPEATS
    assert out["window"] == "14:00"
    assert out["needs_confirm"] is True


def test_confirm_pin_and_roster_notice():
    book = ScheduleBook()
    for i in range(N_REPEATS):
        book.observe("h", "14:00", at=T0 + timedelta(days=i))
    pin = book.confirm_pin("h", "14:00")
    assert pin["pinned"] is True
    assert pin["window"] == "14:00"
    assert pin["roster_alert"]["kind"] == "schedule_pinned"
    assert "14:00" in pin["roster_alert"]["phrase"]
    assert "—" not in pin["roster_alert"]["phrase"]


def test_schedule_change_alerts_roster():
    book = ScheduleBook()
    for i in range(N_REPEATS):
        book.observe("h", "14:00", at=T0 + timedelta(days=i))
    book.confirm_pin("h", "14:00")
    for i in range(N_REPEATS):
        book.observe("h", "16:00", at=T0 + timedelta(days=10 + i, hours=2))
    book.confirm_pin("h", "16:00")
    change = book.last_change("h")
    assert change is not None
    assert change["kind"] == "schedule_changed"
    assert change["from_window"] == "14:00"
    assert change["to_window"] == "16:00"
    assert "—" not in change["phrase"]


def test_missed_adherence_is_soft_escalate_not_fall():
    book = ScheduleBook()
    for i in range(N_REPEATS):
        book.observe("h", "14:00", at=T0 + timedelta(days=i))
    book.confirm_pin("h", "14:00")
    miss = book.missed_adherence("h", at=T0 + timedelta(days=10), window="14:00")
    assert miss["action"] == "soft_escalate"
    assert miss["fall_level"] is False
    assert miss["reason"] == "missed_adherence"
    assert "distress" not in miss["phrase"].lower()
    assert "fall" not in miss["phrase"].lower()
    assert "—" not in miss["phrase"]
