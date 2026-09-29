"""Detector arming threshold = the badge number (spec section 6 port)."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from care_ladder.learning.profile import RoutineProfile, effective_no_movement_timeout_sec
from care_ladder.models import CueEvent
from care_ladder.plan_loader import load_care_plan
from care_ladder.vision.cues import CueDetector

PLAN = Path(__file__).resolve().parents[1] / "configs" / "demo_home.yaml"
NOON = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _plan():
    return load_care_plan(PLAN)


def test_detector_arms_at_adaptive_timeout_when_learning():
    plan = _plan()
    profile = RoutineProfile(subject_key="demo-home-1")  # rapid
    det = CueDetector.from_plan(plan, zone_id="living_room", profile=profile)
    expected = effective_no_movement_timeout_sec(plan, profile)
    assert expected == 360  # 900 * 0.4
    assert det.no_movement_timeout_sec == expected


def test_detector_falls_back_to_plan_timeout_without_profile():
    plan = _plan()
    det = CueDetector.from_plan(plan, zone_id="living_room", profile=None)
    assert det.no_movement_timeout_sec == 900


def test_detector_ignores_profile_when_learning_disabled():
    import yaml

    plan = _plan()
    data = yaml.safe_load(Path(PLAN).read_text())
    data["learning"] = {"enabled": False}
    from care_ladder.models import CarePlan

    plan_off = CarePlan.model_validate(data)
    det = CueDetector.from_plan(plan_off, zone_id="living_room",
                                profile=RoutineProfile(subject_key="x"))
    assert det.no_movement_timeout_sec == 900
