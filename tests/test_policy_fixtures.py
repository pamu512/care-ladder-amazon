"""Quiet-hours suppression + no_visibility demo fixtures (P1.4)."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_quiet_hours_suppressed_fixture():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "quiet_hours_suppressed"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["status"] == "suppressed"
        tools = [e["tool"] for e in inc["events"]]
        assert "suppress" in tools
        sup = next(e for e in inc["events"] if e["tool"] == "suppress")
        assert sup["detail"]["reason"] == "quiet_hours"
        # nothing dialed during quiet hours
        assert "dial_contact" not in tools


def test_no_visibility_fixture():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.post("/demo/run", json={"fixture": "no_visibility"})
        assert r.status_code == 200
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        assert inc["cue"]["kind"] == "no_visibility"
        assert inc["status"] in ("resolved", "suppressed")
