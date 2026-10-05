"""Lightweight repeating-window schedule pin (not ML, not fall-level)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

N_REPEATS = 3


class ScheduleBook:
    """Observe hour windows, propose a pin after N repeats, confirm, miss."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._pinned: dict[str, str] = {}
        self._proposed: dict[str, str] = {}
        self._changes: dict[str, dict[str, Any]] = {}

    def observe(self, household_id: str, window: str, *, at: datetime) -> dict[str, Any]:
        _ = at
        key = (household_id, window)
        self._counts[key] = self._counts.get(key, 0) + 1
        count = self._counts[key]
        proposed = count >= N_REPEATS
        if proposed:
            self._proposed[household_id] = window
        return {
            "proposed": proposed,
            "count": count,
            "window": window,
            "needs_confirm": proposed,
        }

    def confirm_pin(self, household_id: str, window: str = "") -> dict[str, Any]:
        chosen = (window or "").strip() or self._proposed.get(household_id, "")
        if not chosen:
            chosen = "14:00"
        previous = self._pinned.get(household_id)
        self._pinned[household_id] = chosen
        phrase = f"Schedule pinned at {chosen}."
        if previous and previous != chosen:
            change_phrase = f"Schedule changed from {previous} to {chosen}."
            self._changes[household_id] = {
                "kind": "schedule_changed",
                "from_window": previous,
                "to_window": chosen,
                "phrase": change_phrase,
            }
        return {
            "pinned": True,
            "window": chosen,
            "roster_alert": {"kind": "schedule_pinned", "phrase": phrase},
        }

    def last_change(self, household_id: str) -> dict[str, Any] | None:
        return self._changes.get(household_id)

    def missed_adherence(
        self,
        household_id: str,
        *,
        at: datetime,
        window: str | None = None,
    ) -> dict[str, Any]:
        _ = at
        pinned = window or self._pinned.get(household_id)
        phrase = (
            "Pinned window was missed. Starting a quiet check-in with the caregiver roster."
        )
        return {
            "action": "soft_escalate",
            "fall_level": False,
            "reason": "missed_adherence",
            "window": pinned,
            "household_id": household_id,
            "phrase": phrase,
        }


_BOOK = ScheduleBook()


def default_book() -> ScheduleBook:
    return _BOOK


def reset_schedule_book() -> None:
    global _BOOK
    _BOOK = ScheduleBook()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
