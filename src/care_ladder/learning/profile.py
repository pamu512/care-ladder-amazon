"""Adaptive schedule learning: RoutineProfile (spec 2026-09-27).

Explainable histogram learning of the monitored person's usual day.
NOT machine learning, NOT clinical, NEVER auto-enables emergency. Ladder
shape (rung order, contacts) stays human-configured; only timing and
sensitivity move, with an audit-visible explain string.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from care_ladder.models import CarePlan

LearningPhase = Literal["rapid", "settled"]


def subject_key(
    *,
    household_id: str | None = None,
    tenant_id: str | None = None,
    monitored_id: str | None = None,
) -> str:
    """Canonical profile key: household (OpenCV/Amazon) or tenant[+monitored]
    (Galuxium). Ported from the Cursor branch (credit: ide/*-c860 PRs)."""
    if tenant_id:
        tid = tenant_id.strip()
        if not tid:
            raise ValueError("tenant_id is empty")
        mid = (monitored_id or "").strip()
        return f"{tid}:{mid}" if mid else tid
    hid = (household_id or "").strip()
    if not hid:
        raise ValueError("subject_key needs household_id or tenant_id")
    return hid


class LearningConfig(BaseModel):
    """Optional care-plan ``learning:`` block. Missing block = enabled defaults."""

    enabled: bool = True
    settled_after_days: int = 10
    min_no_movement_timeout_sec: int = 120
    rapid_timeout_factor: float = 0.4


class RoutineProfile(BaseModel):
    subject_key: str
    learning_phase: LearningPhase = "rapid"
    frozen: bool = False
    confirmed_ok_days: int = 0
    settled_after_days: int = 10
    # hour-of-day (0..23) buckets: cue counts and OK resolves
    still_hour_hist: list[int] = Field(default_factory=lambda: [0] * 24)
    leave_zone_hour_hist: list[int] = Field(default_factory=lambda: [0] * 24)
    ok_resolve_hour_hist: list[int] = Field(default_factory=lambda: [0] * 24)
    # derived / cached
    suggested_no_movement_timeout_sec: int | None = None
    usual_still_end_hour: int | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Persisted OK-day dedupe: survives process restarts (unlike a transient
    # attr, which double-counts the same calendar day after a redeploy).
    last_confirmed_ok_date: date | None = None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def effective_no_movement_timeout_sec(
    plan: CarePlan, profile: RoutineProfile | None, *, config: LearningConfig | None = None
) -> int:
    """Effective stillness timeout honoring the learning phase.

    rapid: plan_timeout * rapid_timeout_factor, floored at min and clamped
    to the plan timeout (never LONGER than the human plan while learning).
    settled: p80-ish blend of plan timeout and suggestion; simple and tested
    over clever. Learning disabled / frozen / no profile -> plan timeout.
    """
    cfg = config or LearningConfig()
    plan_timeout = int(plan.triggers.no_movement.timeout_sec)
    if profile is None or not cfg.enabled:
        return plan_timeout
    if profile.frozen:
        # frozen: serve the last suggestion if present, else plan timeout
        return profile.suggested_no_movement_timeout_sec or plan_timeout

    if profile.learning_phase == "rapid":
        effective = int(
            _clamp(
                plan_timeout * cfg.rapid_timeout_factor,
                cfg.min_no_movement_timeout_sec,
                plan_timeout,
            )
        )
        return effective

    # settled: blend plan with profile suggestion (if any), bounded by plan
    if profile.suggested_no_movement_timeout_sec:
        suggested = profile.suggested_no_movement_timeout_sec
        blended = int(_clamp(0.5 * (plan_timeout + suggested), cfg.min_no_movement_timeout_sec, plan_timeout))
        return blended
    return plan_timeout


def _p80(hist: list[int]) -> int | None:
    """Hour with 80% of cumulative still-cue mass (for explain copy)."""
    total = sum(hist)
    if total <= 0:
        return None
    acc = 0
    for hour, count in enumerate(hist):
        acc += count
        if acc >= 0.8 * total:
            return hour
    return 23


def explain(profile: RoutineProfile, *, plan_timeout_sec: int, effective_sec: int) -> str:
    """One-line, non-clinical explain for the timeline."""
    phase_word = "settled" if profile.learning_phase == "settled" else "learning (rapid)"
    usual = ""
    if profile.usual_still_end_hour is not None:
        usual = f"usual still often ends by {profile.usual_still_end_hour:02d}:00; "
    return (
        f"{usual}timeout {effective_sec // 60}m ({phase_word}) "
        f"from plan {plan_timeout_sec // 60}m"
    )


def record_incident_outcome(
    profile: RoutineProfile,
    *,
    cue_kind: str,
    cue_start_hour: int,
    resolved_ok: bool,
    ok_day: str | None = None,
    config: LearningConfig | None = None,
) -> RoutineProfile:
    """Deterministic profile update per closed incident (spec section 5).

    frozen -> no histogram/day updates (timeouts still served).
    settled promotion at confirmed_ok_days >= settled_after_days.
    Returns the SAME profile object, mutated (caller persists).
    """
    cfg = config or LearningConfig()
    if profile.frozen:
        profile.updated_at = datetime.now(timezone.utc)
        return profile

    hour = int(_clamp(cue_start_hour, 0, 23))
    if cue_kind == "no_movement":
        profile.still_hour_hist[hour] += 1
    elif cue_kind == "no_visibility":
        profile.leave_zone_hour_hist[hour] += 1

    if resolved_ok:
        profile.ok_resolve_hour_hist[hour] += 1
        from datetime import date as _date

        try:
            day = _date.fromisoformat(ok_day) if ok_day else None
        except ValueError:
            day = None
        if day is not None and day != profile.last_confirmed_ok_date:
            profile.confirmed_ok_days += 1
            profile.last_confirmed_ok_date = day

    # derive usual still end hour (p80 of still-cue mass)
    profile.usual_still_end_hour = _p80(profile.still_hour_hist)

    # suggestion moves toward the observed OK-resolve mass while settling
    if profile.confirmed_ok_days > 0:
        profile.suggested_no_movement_timeout_sec = None  # settled uses plan blend
    profile.learning_phase = (
        "settled"
        if profile.confirmed_ok_days >= profile.settled_after_days
        else "rapid"
    )
    profile.updated_at = datetime.now(timezone.utc)
    return profile


def freeze(profile: RoutineProfile) -> RoutineProfile:
    profile.frozen = True
    return profile


def reset(profile: RoutineProfile) -> RoutineProfile:
    """Back to rapid with cleared histograms (freeze cleared per spec: 'reset learning (back to rapid + clear histogram)')."""
    fresh = RoutineProfile(
        subject_key=profile.subject_key,
        settled_after_days=profile.settled_after_days,
    )
    return fresh


def mark_settled(profile: RoutineProfile) -> RoutineProfile:
    profile.confirmed_ok_days = max(profile.confirmed_ok_days, profile.settled_after_days)
    profile.learning_phase = "settled"
    return profile
