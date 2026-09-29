"""FastAPI incident timeline + demo trigger (Task 8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_demo_run_returns_timeline_with_ordered_steps_and_caregiver_name():
    app = create_app(store=AuditStore())
    client = TestClient(app)

    run = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert run.status_code == 200
    body = run.json()
    assert "incident_id" in body
    incident_id = body["incident_id"]

    listed = client.get("/incidents")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert incident_id in ids

    detail = client.get(f"/incidents/{incident_id}")
    assert detail.status_code == 200
    incident = detail.json()
    assert incident["id"] == incident_id
    assert incident["cue"]["kind"] == "no_movement"

    events = incident["events"]
    assert len(events) >= 3
    tools = [e["tool"] for e in events]
    assert tools[0] == "cue"
    assert "speaker_prompt" in tools
    # Ordered: cue before speaker_prompt before (or with) dial/resolve path
    assert tools.index("cue") < tools.index("speaker_prompt")

    prompt_events = [e for e in events if e["tool"] == "speaker_prompt"]
    assert prompt_events
    prompt_text = prompt_events[0]["detail"]["text"]
    # Caregiver display_name from configs/demo_home.yaml
    assert "Alex" in prompt_text


def test_get_unknown_incident_returns_404():
    app = create_app(store=AuditStore())
    client = TestClient(app)
    resp = client.get("/incidents/does-not-exist")
    assert resp.status_code == 404


def test_demo_run_rejects_unknown_fixture():
    app = create_app(store=AuditStore())
    client = TestClient(app)
    resp = client.post("/demo/run", json={"fixture": "not_a_real_fixture"})
    assert resp.status_code == 400
