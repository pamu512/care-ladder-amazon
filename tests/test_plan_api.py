"""GET /plan: redacted care plan for the console's full-ladder rail."""

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore


def test_plan_returns_rungs_and_redacts_phones():
    with TestClient(create_app(store=AuditStore())) as client:
        r = client.get("/plan")
    assert r.status_code == 200
    plan = r.json()
    tools = [rung["tool"] for rung in plan["rungs"]]
    assert "dial_contact" in tools
    assert "emergency" in tools
    emergency = next(rung for rung in plan["rungs"] if rung["tool"] == "emergency")
    assert emergency["params"]["enabled"] is False
    # phones redacted: reserved demo numbers never served raw
    caregiver = plan["caregiver"]["phone_e164"]
    assert caregiver is not None and "0101" not in caregiver and caregiver.startswith("****")
    if plan.get("secondary"):
        assert "0102" not in (plan["secondary"]["phone_e164"] or "")
