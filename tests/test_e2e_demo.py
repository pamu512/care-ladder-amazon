"""End-to-end demo path: fixture → incident timeline with ≥3 audit events."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_e2e_demo_fixture_produces_incident_with_at_least_three_audit_events():
    app = create_app(store=AuditStore())
    client = TestClient(app)

    run = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert run.status_code == 200
    incident_id = run.json()["incident_id"]

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
    assert "dial_contact" in tools or "resolve" in tools


def test_e2e_opencv_stillness_fixture_uses_detector_cue():
    app = create_app(store=AuditStore())
    client = TestClient(app)

    run = client.post("/demo/run", json={"fixture": "opencv_stillness"})
    assert run.status_code == 200
    incident_id = run.json()["incident_id"]

    detail = client.get(f"/incidents/{incident_id}")
    assert detail.status_code == 200
    incident = detail.json()

    assert incident["cue"]["kind"] == "no_movement"
    assert incident["cue"]["detail"].get("source") == "opencv_cue_detector"
    assert len(incident["events"]) >= 3
    if incident.get("pre_event_frame_count", 0) > 0:
        assert incident.get("privacy") in {"blur", "silhouette"}
        assert incident["events"][0]["detail"].get("privacy") in {"blur", "silhouette"}
