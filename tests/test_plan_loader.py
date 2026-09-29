from pathlib import Path
from care_ladder.plan_loader import load_care_plan

def test_loads_demo_home_and_keeps_emergency_disabled():
    plan = load_care_plan(Path("configs/demo_home.yaml"))
    assert plan.caregiver.display_name == "Alex"
    assert plan.caregiver.phone_e164.startswith("+121255501")
    assert plan.triggers.no_movement.timeout_sec == 900
    assert plan.rungs[0].tool == "reperceive"
    ask = next(r for r in plan.rungs if r.tool == "speaker_prompt")
    assert "Are you okay?" in ask.params["text"]
    assert "Alex" in ask.params["text"]
    emergency = next(r for r in plan.rungs if r.tool == "emergency")
    assert emergency.params.get("enabled") is False


def test_demo_env_accepts_reserved_555_phones(monkeypatch, tmp_path):
    import os

    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    yaml_text = """
household_id: t
caregiver:
  display_name: Alex
  phone_e164: "+12125550101"
monitored:
  display_name: Pat
triggers:
  no_movement:
    enabled: true
    timeout_sec: 10
rungs:
  - id: ask
    tool: speaker_prompt
    params: { text: "ok?" }
"""
    p = tmp_path / "ok.yaml"
    p.write_text(yaml_text)
    plan = load_care_plan(p)
    assert plan.caregiver.phone_e164 == "+12125550101"


def test_demo_env_rejects_emergency_like_phone(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    yaml_text = """
household_id: t
caregiver:
  display_name: Bad
  phone_e164: "+1911"
monitored:
  display_name: Pat
triggers:
  no_movement:
    enabled: true
    timeout_sec: 10
rungs:
  - id: ask
    tool: speaker_prompt
    params: { text: "ok?" }
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_text)
    with pytest.raises(ValueError, match="(?i)emergency|911|reserved|demo"):
        load_care_plan(p)


def test_demo_env_rejects_non_reserved_mobile(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setenv("CARE_LADDER_ENV", "demo")
    yaml_text = """
household_id: t
caregiver:
  display_name: Real
  phone_e164: "+14155552671"
monitored:
  display_name: Pat
triggers:
  no_movement:
    enabled: true
    timeout_sec: 10
rungs:
  - id: ask
    tool: speaker_prompt
    params: { text: "ok?" }
"""
    p = tmp_path / "real.yaml"
    p.write_text(yaml_text)
    with pytest.raises(ValueError, match="(?i)reserved|555|demo"):
        load_care_plan(p)
