"""POST /incidents/{id}/ack: caregiver human-in-the-loop acknowledgement."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def _incident(client) -> str:
    r = client.post("/demo/run", json={"fixture": "no_movement_silence"})
    assert r.status_code == 200
    return r.json()["incident_id"]


def test_ack_appends_audit_event_and_stamps_fields():
    with TestClient(create_app(store=AuditStore())) as client:
        iid = _incident(client)
        r = client.post(f"/incidents/{iid}/ack", json={"contact": "caregiver", "note": "called mom"})
        assert r.status_code == 200
        body = r.json()
        assert body["acked_by"] == "caregiver"
        assert body["acked_at"]

        inc = client.get(f"/incidents/{iid}").json()
        assert inc["acked_by"] == "caregiver"
        assert inc["acked_at"] is not None
        # status unchanged: resolved stays resolved
        assert inc["status"] == "resolved"
        ack = [e for e in inc["events"] if e["tool"] == "notify"]
        assert ack, "caregiver_ack audit event missing"
        assert ack[-1]["detail"]["action"] == "caregiver_ack"
        assert ack[-1]["detail"]["contact"] == "caregiver"
        assert ack[-1]["detail"]["note"] == "called mom"


def test_ack_idempotent_second_call_409():
    with TestClient(create_app(store=AuditStore())) as client:
        iid = _incident(client)
        assert client.post(f"/incidents/{iid}/ack", json={}).status_code == 200
        assert client.post(f"/incidents/{iid}/ack", json={}).status_code == 409


def test_ack_unknown_incident_404():
    with TestClient(create_app(store=AuditStore())) as client:
        assert client.post("/incidents/nope/ack", json={}).status_code == 404


def test_ui_has_acknowledge_button():
    html = open("src/care_ladder/api/static/index.html", encoding="utf-8").read()
    assert 'data-ack=' in html
    assert "Acknowledge" in html
