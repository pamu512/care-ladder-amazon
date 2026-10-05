"""MCP server (Streamable HTTP): handshake, tool set, Path A via tools only."""

import json

import pytest
from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore

EXPECTED_TOOLS = {
    "start_or_resume_incident",
    "check_in_prompt",
    "advance_rung",
    "resolve_incident",
    "get_incident_status",
    "notify_caretaker",
    "request_call",
    "caregiver_ack",
    "caregiver_outcome",
    "defer_escalation",
    "tick_care_timers",
    "how_is_household",
    "confirm_schedule_pin",
}


def _mcp_post(client: TestClient, body: dict, session_id: str | None = None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return client.post("/mcp", json=body, headers=headers)


def _parse_sse_or_json(resp):
    """MCP streamable HTTP answers SSE or JSON depending on negotiation."""
    txt = resp.text
    if txt.startswith("event:") or txt.startswith("data:"):
        for line in txt.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"no data line in SSE: {txt[:200]}")
    return json.loads(txt)


def test_initialize_handshake_and_toolset():
    with TestClient(create_app(store=AuditStore())) as client:
        r = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "care-ladder-test", "version": "0.1"},
            },
        })
        assert r.status_code == 200, r.text
        result = _parse_sse_or_json(r)["result"]
        assert result["protocolVersion"]

        r2 = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
        })
        assert r2.status_code == 200, r2.text
        names = {t["name"] for t in _parse_sse_or_json(r2)["result"]["tools"]}
        assert names == EXPECTED_TOOLS, names



def _assert_session_snapshot(payload, household_id, incident_id, *, known=True):
    """Every MCP tool return carries one shared agent-memory block."""
    assert "session_snapshot" in payload, payload
    snap = payload["session_snapshot"]
    for key in ("household_id", "incident_id", "rung", "status", "tools"):
        assert key in snap, key
        assert key in payload, key
    assert snap["household_id"] == household_id
    assert payload["household_id"] == household_id
    if incident_id is not None:
        assert snap["incident_id"] == incident_id
        assert payload["incident_id"] == incident_id
    assert isinstance(snap["tools"], list)
    assert isinstance(payload["tools"], list)
    assert isinstance(snap["rung"], int)
    if known:
        assert snap["status"] in {"open", "resolved", "exhausted", "suppressed"}
        assert snap["rung"] >= 1
    else:
        assert snap["status"] == "unknown"
        assert snap["tools"] == []


def test_path_a_via_tool_calls_only():
    with TestClient(create_app(store=AuditStore())) as client:
        r = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}},
        })
        sid = r.headers.get("mcp-session-id")

        def call(name, args):
            resp = _mcp_post(client, {
                "jsonrpc": "2.0", "id": 99, "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }, session_id=sid)
            assert resp.status_code == 200, resp.text
            out = _parse_sse_or_json(resp)["result"]
            if isinstance(out, dict) and "structuredContent" in out:
                return out["structuredContent"]
            return out

        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        assert started["resumed"] is False
        _assert_session_snapshot(started, "amazon-demo-1", iid)

        resumed = call("start_or_resume_incident", {
            "cue_kind": "no_movement",
            "household_id": "amazon-demo-1",
            "incident_id": iid,
        })
        assert resumed["resumed"] is True
        assert resumed["incident_id"] == iid
        _assert_session_snapshot(resumed, "amazon-demo-1", iid)

        st = call("get_incident_status", {"household_id": "amazon-demo-1", "incident_id": iid})
        assert "alexa_checkin" in st["tools"]
        _assert_session_snapshot(st, "amazon-demo-1", iid)

        chk = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid, "utterance": "I'm fine",
        })
        assert chk["reply_kind"] == "ok"
        assert chk["response_intent"] == "clear_ok"
        assert chk["intent_label"] == "Clear OK"
        _assert_session_snapshot(chk, "amazon-demo-1", iid)
        after_chk = call("get_incident_status", {"household_id": "amazon-demo-1", "incident_id": iid})
        assert "alexa_checkin" in after_chk["tools"]
        assert "check_in_prompt" not in after_chk["tools"]

        mixed = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid,
            "utterance": "I'm okay but I think I'm hurt",
        })
        assert mixed["response_intent"] == "needs_human"
        assert mixed["reply_kind"] != "ok"
        _assert_session_snapshot(mixed, "amazon-demo-1", iid)

        groan = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid, "utterance": "nngh",
        })
        assert groan["response_intent"] == "unclear"
        assert groan["reply_kind"] == "silence"
        _assert_session_snapshot(groan, "amazon-demo-1", iid)

        adv = call("advance_rung", {"household_id": "amazon-demo-1", "incident_id": iid})
        _assert_session_snapshot(adv, "amazon-demo-1", iid)

        note = call("notify_caretaker", {"household_id": "amazon-demo-1", "incident_id": iid})
        _assert_session_snapshot(note, "amazon-demo-1", iid)

        res = call("resolve_incident", {
            "household_id": "amazon-demo-1", "incident_id": iid, "reason": "voice_ok",
        })
        assert res["status"] == "resolved"
        _assert_session_snapshot(res, "amazon-demo-1", iid)

        # double-resolve rejected
        res2 = call("resolve_incident", {
            "household_id": "amazon-demo-1", "incident_id": iid, "reason": "voice_ok",
        })
        assert res2.get("error") == "already_resolved"
        _assert_session_snapshot(res2, "amazon-demo-1", iid)


def test_unknown_incident_tools_return_error():
    with TestClient(create_app(store=AuditStore())) as client:
        r = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}},
        })
        sid = r.headers.get("mcp-session-id")

        resp = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_incident_status",
                       "arguments": {"household_id": "amazon-demo-1", "incident_id": "nope"}},
        }, session_id=sid)
        out = _parse_sse_or_json(resp)["result"]
        assert "unknown incident" in str(out)
        payload = out["structuredContent"] if isinstance(out, dict) and "structuredContent" in out else out
        _assert_session_snapshot(payload, "amazon-demo-1", "nope", known=False)


def test_request_call_is_simulated_with_reserved_number():
    with TestClient(create_app(store=AuditStore())) as client:
        r = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}},
        })
        sid = r.headers.get("mcp-session-id")

        def call(name, args):
            resp = _mcp_post(client, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                      "params": {"name": name, "arguments": args}},
                             session_id=sid)
            out = _parse_sse_or_json(resp)["result"]
            if isinstance(out, dict) and "structuredContent" in out:
                return out["structuredContent"]
            return out

        started = call("start_or_resume_incident", {"cue_kind": "no_visibility"})
        iid = started["incident_id"]
        _assert_session_snapshot(started, "amazon-demo-1", iid)
        out = call("request_call", {
            "household_id": "amazon-demo-1", "incident_id": iid,
        })
        assert out["simulated"] is True
        assert out["phone_e164"] == "+12125550176"
        assert "911" not in out["phone_e164"]
        _assert_session_snapshot(out, "amazon-demo-1", iid)


def _init_and_caller(client: TestClient):
    r = _mcp_post(client, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}},
    })
    sid = r.headers.get("mcp-session-id")

    def call(name, args):
        resp = _mcp_post(client, {
            "jsonrpc": "2.0", "id": 99, "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }, session_id=sid)
        assert resp.status_code == 200, resp.text
        out = _parse_sse_or_json(resp)["result"]
        if isinstance(out, dict) and "structuredContent" in out:
            return out["structuredContent"]
        return out

    return call


def test_mcp_mutations_land_in_same_store_firetv_polls():
    """alexa_sim / MCP tools must write the incident Fire TV GET /incidents reads."""
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]

        listing = client.get("/incidents").json()
        mine = [i for i in listing if i["household_id"] == "amazon-demo-1"]
        assert any(i["id"] == iid for i in mine), listing

        inc = client.get(f"/incidents/{iid}").json()
        assert inc["household_id"] == "amazon-demo-1"
        assert inc["status"] in {"open", "exhausted"}
        tools = [e["tool"] for e in inc["events"]]
        assert "alexa_checkin" in tools
        assert any(e.get("detail", {}).get("via") == "mcp" for e in inc["events"])

        chk = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid,
            "utterance": "don't worry",
        })
        assert chk["response_intent"] == "clear_ok"
        inc2 = client.get(f"/incidents/{iid}").json()
        last_chk = next(
            e for e in reversed(inc2["events"]) if e["tool"] == "alexa_checkin"
        )
        assert last_chk["detail"]["reply_raw"] == "don't worry"
        assert last_chk["detail"]["response_intent"] == "clear_ok"
        assert last_chk["detail"]["via"] == "mcp"

        call("resolve_incident", {
            "household_id": "amazon-demo-1", "incident_id": iid, "reason": "voice_ok",
        })
        inc3 = client.get(f"/incidents/{iid}").json()
        assert inc3["status"] == "resolved"
        assert any(e["tool"] == "resolve" and e["detail"].get("via") == "mcp"
                   for e in inc3["events"])

        ack = client.post(
            f"/incidents/{iid}/ack",
            json={"contact": "primary contact", "via": "fire_tv"},
        )
        assert ack.status_code == 200


def test_mcp_needs_human_stays_notify_on_firetv_store():
    with TestClient(create_app(store=AuditStore())) as client:
        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid,
            "utterance": "I'm okay but I think I'm hurt",
        })
        call("notify_caretaker", {"household_id": "amazon-demo-1", "incident_id": iid})
        inc = client.get(f"/incidents/{iid}").json()
        assert inc["status"] != "resolved"
        tools = [e["tool"] for e in inc["events"]]
        assert "notify_caretaker" in tools
        assert "resolve" not in tools
        listing = client.get("/incidents").json()
        row = next(i for i in listing if i["id"] == iid)
        assert row["status"] != "resolved"


def test_mcp_agent_active_while_driving_then_auto_clears():
    store = AuditStore()
    with TestClient(create_app(store=store)) as client:
        idle = client.get("/mcp-agent").json()
        assert idle["active"] is False

        call = _init_and_caller(client)
        started = call("start_or_resume_incident", {"cue_kind": "no_movement"})
        iid = started["incident_id"]
        driving = client.get("/mcp-agent").json()
        assert driving["active"] is True
        assert driving["household_id"] == "amazon-demo-1"
        assert driving["incident_id"] == iid

        store.mark_mcp_driving("amazon-demo-1", iid, ttl_sec=0)
        cleared = client.get("/mcp-agent").json()
        assert cleared["active"] is False
