"""Learning API wiring (Tasks 2-3): endpoints, fixture wiring, audit event."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_learning_endpoints_roundtrip():
    with TestClient(create_app(store=AuditStore())) as client:
        hh = "demo-home-1"
        # reset to a known rapid state first
        client.post(f"/learning/{hh}/reset")
        r = client.get(f"/learning/{hh}")
        assert r.status_code == 200
        data = r.json()
        assert data["learning_phase"] == "rapid"
        assert data["frozen"] is False
        assert data["effective_no_movement_timeout_sec"] == 360  # 900 * 0.4
        assert data["plan_timeout_sec"] == 900

        # freeze serves plan timeout when no suggestion exists
        client.post(f"/learning/{hh}/freeze")
        frozen = client.get(f"/learning/{hh}").json()
        assert frozen["frozen"] is True
        assert frozen["effective_no_movement_timeout_sec"] == 900

        # settle promotes phase
        client.post(f"/learning/{hh}/reset")
        client.post(f"/learning/{hh}/settle")
        settled = client.get(f"/learning/{hh}").json()
        assert settled["learning_phase"] == "settled"


def test_fixture_incident_carries_learning_detail_and_audit():
    with TestClient(create_app(store=AuditStore())) as client:
        client.post("/learning/demo-home-1/reset")
        r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
        iid = r.json()["incident_id"]
        inc = client.get(f"/incidents/{iid}").json()
        learning = inc["cue"]["detail"].get("learning")
        assert learning is not None
        assert learning["learning_phase"] in {"rapid", "settled"}
        assert learning["effective_timeout_sec"] > 0
        assert "explain" in learning and "timeout" in learning["explain"]
        # audit event recorded
        updates = [e for e in inc["events"] if e["tool"] == "routine_profile_update"]
        assert updates
        assert "frozen" in updates[0]["detail"]


def test_learning_never_touches_clinical_or_emergency_copy():
    with TestClient(create_app(store=AuditStore())) as client:
        client.post("/learning/demo-home-1/reset")
        r = client.post("/demo/run", json={"fixture": "no_movement_ok"})
        inc = client.get(f"/incidents/{r.json()['incident_id']}").json()
        blob = str(inc).lower()
        for banned in ("risk score", "clinical", "diagnos"):
            assert banned not in blob
