"""RoutineProfile phase rules, timeouts, explain, freeze/reset (spec 2026-09-27)."""

from pathlib import Path

from care_ladder.learning.profile import (
    LearningConfig,
    RoutineProfile,
    effective_no_movement_timeout_sec,
    explain,
    freeze,
    mark_settled,
    record_incident_outcome,
    reset,
)
from care_ladder.learning.store import RoutineProfileJSONStore
from care_ladder.models import CarePlan
from care_ladder.plan_loader import load_care_plan

PLAN = Path(__file__).resolve().parents[1] / "configs" / "demo_home.yaml"


def _plan() -> CarePlan:
    return load_care_plan(PLAN)


def test_rapid_factor_shortens_timeout():
    plan = _plan()  # timeout 900
    profile = RoutineProfile(subject_key="demo-home-1")  # rapid
    eff = effective_no_movement_timeout_sec(plan, profile)
    assert eff == 360  # 900 * 0.4, above min 120, below plan


def test_rapid_factor_respects_min_floor():
    plan = _plan()
    cfg = LearningConfig(rapid_timeout_factor=0.05, min_no_movement_timeout_sec=120)
    profile = RoutineProfile(subject_key="x")
    assert effective_no_movement_timeout_sec(plan, profile, config=cfg) == 120


def test_disabled_and_missing_profile_use_plan_timeout():
    plan = _plan()
    assert effective_no_movement_timeout_sec(plan, None) == 900
    cfg = LearningConfig(enabled=False)
    profile = RoutineProfile(subject_key="x")
    assert effective_no_movement_timeout_sec(plan, profile, config=cfg) == 900


def test_frozen_serves_last_suggestion_or_plan():
    plan = _plan()
    profile = freeze(RoutineProfile(subject_key="x"))
    assert effective_no_movement_timeout_sec(plan, profile) == 900
    frozen_with_hint = RoutineProfile(
        subject_key="x", frozen=True, suggested_no_movement_timeout_sec=600
    )
    assert effective_no_movement_timeout_sec(plan, frozen_with_hint) == 600


def test_settled_blends_plan_and_suggestion():
    plan = _plan()
    profile = mark_settled(
        RoutineProfile(subject_key="x", suggested_no_movement_timeout_sec=600)
    )
    # blend(900, 600) = 750, within [120, 900]
    assert effective_no_movement_timeout_sec(plan, profile) == 750


def test_record_outcome_buckets_and_settles():
    profile = RoutineProfile(subject_key="x", settled_after_days=3)
    record_incident_outcome(profile, cue_kind="no_movement", cue_start_hour=7,
                            resolved_ok=True, ok_day="2026-09-27")
    record_incident_outcome(profile, cue_kind="no_movement", cue_start_hour=8,
                            resolved_ok=True, ok_day="2026-09-28")
    record_incident_outcome(profile, cue_kind="no_movement", cue_start_hour=7,
                            resolved_ok=True, ok_day="2026-09-28")  # same day: no bump
    assert profile.confirmed_ok_days == 2
    assert profile.learning_phase == "rapid"
    record_incident_outcome(profile, cue_kind="no_movement", cue_start_hour=9,
                            resolved_ok=True, ok_day="2026-09-29")
    assert profile.confirmed_ok_days == 3
    assert profile.learning_phase == "settled"
    assert profile.usual_still_end_hour is not None and 0 <= profile.usual_still_end_hour <= 23


def test_frozen_skips_updates():
    profile = freeze(RoutineProfile(subject_key="x"))
    record_incident_outcome(profile, cue_kind="no_movement", cue_start_hour=7,
                            resolved_ok=True, ok_day="d1")
    assert profile.confirmed_ok_days == 0
    assert sum(profile.still_hour_hist) == 0


def test_reset_clears_to_rapid():
    profile = mark_settled(RoutineProfile(subject_key="x"))
    profile.still_hour_hist[7] = 5
    fresh = reset(profile)
    assert fresh.learning_phase == "rapid"
    assert sum(fresh.still_hour_hist) == 0
    assert fresh.confirmed_ok_days == 0


def test_explain_string_is_non_clinical():
    plan = _plan()
    profile = RoutineProfile(subject_key="x", usual_still_end_hour=9)
    text = explain(profile, plan_timeout_sec=900, effective_sec=360)
    assert "timeout 6m (learning (rapid))" in text
    assert "usual still often ends by 09:00" in text
    for banned in ("risk", "clinical", "diagnos", "911"):
        assert banned not in text.lower()


def test_json_store_roundtrip(tmp_path: Path):
    store = RoutineProfileJSONStore(tmp_path / "rp")
    p = store.get_or_create("demo-home-1")
    record_incident_outcome(p, cue_kind="no_movement", cue_start_hour=7,
                            resolved_ok=True, ok_day="2026-09-27")
    store.save(p)
    loaded = store.get("demo-home-1")
    assert loaded is not None
    assert loaded.confirmed_ok_days == 1
    assert loaded.still_hour_hist[7] == 1
    assert store.get("never-seen") is None


def test_json_store_safe_keys(tmp_path: Path):
    store = RoutineProfileJSONStore(tmp_path / "rp")
    store.save(RoutineProfile(subject_key="../../etc/evil"))
    files = list((tmp_path / "rp").iterdir())
    assert len(files) == 1
    # sanitized: no path traversal separators survive
    assert "/" not in files[0].name and files[0].name.startswith("_etc_evil") is False
    assert files[0].parent == store.root  # stayed inside the store root

def test_tenant_scoped_subject_keys(tmp_path):
    """Galuxium hook (spec section 4): tenant_id + monitored id as subject key.
    JSON store today; Postgres routine_profiles table when tenancy lands."""
    from care_ladder.learning.store import RoutineProfileJSONStore as S

    store = S(tmp_path / "rp")
    a = store.get_or_create("tenant-42:monitored-7")
    b = store.get_or_create("tenant-99:monitored-7")
    assert a.subject_key != b.subject_key
    store.save(a)
    assert store.get("tenant-42:monitored-7").subject_key == "tenant-42:monitored-7"
    # tenant-99 never saved: get returns None until created
    assert store.get("tenant-99:monitored-7") is None
    assert store.get_or_create("tenant-99:monitored-7").confirmed_ok_days == 0


def test_ok_day_dedupe_survives_restart(tmp_path):
    """Two OK resolves on the same calendar day = 1 day bump, even after a
    save/load round-trip (process restart). Regression: the transient-attr
    version double-counted after a redeploy."""
    from care_ladder.learning.store import RoutineProfileJSONStore

    store = RoutineProfileJSONStore(tmp_path / "rp")
    p1 = store.get_or_create("hh-1")
    record_incident_outcome(p1, cue_kind="no_movement", cue_start_hour=8,
                            resolved_ok=True, ok_day="2026-09-27")
    store.save(p1)

    reloaded = store.get("hh-1")          # simulates a process restart
    record_incident_outcome(reloaded, cue_kind="no_movement", cue_start_hour=9,
                            resolved_ok=True, ok_day="2026-09-27")
    assert reloaded.confirmed_ok_days == 1
    assert reloaded.last_confirmed_ok_date is not None


def test_subject_key_factory():
    from care_ladder.learning.profile import subject_key
    import pytest

    assert subject_key(household_id="demo-home-1") == "demo-home-1"
    assert subject_key(tenant_id="t42", monitored_id="m7") == "t42:m7"
    assert subject_key(tenant_id="t42") == "t42"
    assert subject_key(tenant_id="t42", monitored_id="  ") == "t42"
    with pytest.raises(ValueError):
        subject_key(household_id="   ")
    with pytest.raises(ValueError):
        subject_key()
