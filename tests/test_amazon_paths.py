"""Amazon demo fixtures: Path A (stillness) and Path B (occlusion, never distress)."""

import json
import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_alexa_path_a_full_ladder():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_a"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        tools = [e["tool"] for e in inc["events"]]
        assert "alexa_checkin" in tools
        assert "wait_window" in tools
        assert "notify_caretaker" in tools
        assert "request_call" in tools
        assert "dial_contact" not in tools  # Amazon path never dials for real
        assert inc["household_id"] == "amazon-demo-1"
        checkins = [e for e in inc["events"] if e["tool"] == "alexa_checkin"]
        assert checkins, "Path A must quote Alexa+ prompts on the TV transcript"
        for ev in checkins:
            prompt = ev["detail"]["prompt"]
            assert "Meera" not in prompt and "Anoop" not in prompt
            assert "resident" in prompt.lower() or "primary contact" in prompt.lower()


def test_alexa_path_b_never_claims_distress():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_b"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["cue"]["kind"] == "no_visibility"
        blob = json.dumps(inc)
        assert "distress_heuristic" not in blob
        notify = next(e for e in inc["events"] if e["tool"] == "notify_caretaker")
        assert notify["detail"]["basis"] == "camera_health_inform"
        # occlusion prompt was the blanket ask, not a distress prompt
        checkins = [e for e in inc["events"] if e["tool"] == "alexa_checkin"]
        assert any("blanket" in e["detail"]["prompt"] for e in checkins)
        for ev in checkins:
            prompt = ev["detail"]["prompt"]
            assert "Meera" not in prompt and "Anoop" not in prompt


def test_alexa_path_a_soft_ok_fixture():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_a_soft_ok"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["status"] == "resolved"
        chk = next(e for e in inc["events"] if e["tool"] == "alexa_checkin")
        assert chk["detail"]["response_intent"] == "clear_ok"
        assert "okay" not in chk["detail"]["reply_raw"].lower()
        assert "Meera" not in json.dumps(inc) and "Anoop" not in json.dumps(inc)


def test_alexa_path_a_needs_human_fixture():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_a_needs_human"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["status"] != "resolved"
        chk = next(e for e in inc["events"] if e["tool"] == "alexa_checkin")
        assert chk["detail"]["response_intent"] == "needs_human"
        assert chk["detail"]["intent_label"] == "Needs human"
        notify = next(e for e in inc["events"] if e["tool"] == "notify_caretaker")
        assert notify["detail"]["basis"] == "needs_human"
        assert "Meera" not in json.dumps(inc) and "Anoop" not in json.dumps(inc)


def test_alexa_path_a_unclear_fixture():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "alexa_path_a_unclear"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["status"] != "resolved"
        checkins = [e for e in inc["events"] if e["tool"] == "alexa_checkin"]
        assert all(e["detail"]["response_intent"] == "unclear" for e in checkins)
        assert any(e["tool"] == "notify_caretaker" for e in inc["events"])
        assert not any(e["tool"] == "resolve" for e in inc["events"])


def test_amazon_plan_not_the_opencv_default():
    # the OpenCV fixtures still use demo_home.yaml (Alex/Sam household)
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "no_movement_silence"})
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["household_id"] == "demo-home-1"
        tools = [e["tool"] for e in inc["events"]]
        assert "speaker_prompt" in tools and "alexa_checkin" not in tools


def test_friction_log_covers_demo_video_surfaces():
    """Rank 4: no pending demo-path surfaces; each surface has the rubric triple."""
    text = Path("docs/friction-log.md").read_text()
    assert "Pending surfaces" not in text
    assert "Fire TV" in text
    assert "1280×720" in text or "1280x720" in text
    assert "local-only MCP" in text
    assert "CloudFront" in text
    assert "uvicorn" in text.lower() or "FastAPI mount" in text
    # rubric fields appear for the filled surfaces (not just the intro)
    assert text.lower().count("severity") >= 4
    assert text.lower().count("workaround") >= 4
    assert text.lower().count("suggestion") >= 4


def test_amazon_demo_path_script_is_the_one_story():
    text = Path("scripts/amazon_demo_path.sh").read_text()
    assert "don't worry" in text
    assert "/firetv/" in text
    assert "alexa_sim" in text
    assert "Acknowledge" in text
    assert "1280×720" in text or "1280x720" in text
    assert "shots 3" in text
    assert "never open" in text.lower() or "Never open" in text


def test_amazon_demo_path_check_mode_cold_run():
    """Third-party CHECK=1 path: sim mutations visible on /incidents."""
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "CHECK": "1", "PORT": "8798", "HOST": "127.0.0.1"}
    r = subprocess.run(
        ["bash", str(root / "scripts" / "amazon_demo_path.sh")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    assert "same incident resolved" in out
    assert "notify stays up" in out
