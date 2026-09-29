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

        st = call("get_incident_status", {"household_id": "amazon-demo-1", "incident_id": iid})
        assert "alexa_checkin" in st["tools"]

        chk = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid, "utterance": "I'm fine",
        })
        assert chk["reply_kind"] == "ok"
        assert chk["response_intent"] == "clear_ok"
        assert chk["intent_label"] == "Clear OK"

        mixed = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid,
            "utterance": "I'm okay but I think I'm hurt",
        })
        assert mixed["response_intent"] == "needs_human"
        assert mixed["reply_kind"] != "ok"

        groan = call("check_in_prompt", {
            "household_id": "amazon-demo-1", "incident_id": iid, "utterance": "nngh",
        })
        assert groan["response_intent"] == "unclear"
        assert groan["reply_kind"] == "silence"

        res = call("resolve_incident", {
            "household_id": "amazon-demo-1", "incident_id": iid, "reason": "voice_ok",
        })
        assert res["status"] == "resolved"

        # double-resolve rejected
        res2 = call("resolve_incident", {
            "household_id": "amazon-demo-1", "incident_id": iid, "reason": "voice_ok",
        })
        assert res2.get("error") == "already_resolved"


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
        out = call("request_call", {
            "household_id": "amazon-demo-1", "incident_id": started["incident_id"],
        })
        assert out["simulated"] is True
        assert out["phone_e164"] == "+12125550176"
        assert "911" not in out["phone_e164"]
