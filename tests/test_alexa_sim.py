"""Alexa+ sim client (MCP client over Streamable HTTP) drives a live server."""

import json
import threading
import time
import urllib.request

import uvicorn

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.mcp_server.alexa_sim import run_sim

import asyncio


def test_sim_silence_path_tools():
    config = uvicorn.Config(
        create_app(store=AuditStore()), host="127.0.0.1", port=8791, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8791/plan", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        log, final = asyncio.run(
            run_sim("http://127.0.0.1:8791", cue_kind="no_movement", answer="", verbose=False)
        )
        assert any("start_or_resume_incident" in line for line in log)
        assert any("notify_caretaker" in line for line in log)
        assert any("request_call" in line for line in log)
        assert any('"resumed": true' in line for line in log)
        assert final.get("status") in {"exhausted", "open"}
        assert any(line.startswith("SESSION ") and "rung=" in line and "status=" in line for line in log)
        iids = [line.split("incident=", 1)[1].split()[0] for line in log if line.startswith("SESSION ")]
        assert iids and len(set(iids)) == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sim_needs_human_does_not_resolve():
    config = uvicorn.Config(
        create_app(store=AuditStore()), host="127.0.0.1", port=8792, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8792/plan", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        log, final = asyncio.run(
            run_sim(
                "http://127.0.0.1:8792",
                cue_kind="no_movement",
                answer="I'm okay but I think I'm hurt",
                verbose=False,
            )
        )
        assert any("needs_human" in line for line in log)
        assert any("notify_caretaker" in line for line in log)
        assert not any("resolve_incident" in line for line in log)
        assert final.get("status") != "resolved"
        assert any('"resumed": true' in line for line in log)
        assert any(line.startswith("SESSION ") and "rung=" in line and "status=" in line for line in log)
        iids = [line.split("incident=", 1)[1].split()[0] for line in log if line.startswith("SESSION ")]
        assert iids and len(set(iids)) == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sim_soft_ok_resumes_same_incident():
    config = uvicorn.Config(
        create_app(store=AuditStore()), host="127.0.0.1", port=8793, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8793/plan", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        log, final = asyncio.run(
            run_sim(
                "http://127.0.0.1:8793",
                cue_kind="no_movement",
                answer="don't worry",
                verbose=False,
            )
        )
        assert any("clear_ok" in line for line in log)
        assert any("resolve_incident" in line for line in log)
        assert any('"resumed": true' in line for line in log)
        assert any(line.startswith("SESSION ") and "rung=" in line and "status=" in line for line in log)
        iids = [line.split("incident=", 1)[1].split()[0] for line in log if line.startswith("SESSION ")]
        assert iids and len(set(iids)) == 1
        assert final.get("status") == "resolved"
        listing = json.loads(
            urllib.request.urlopen("http://127.0.0.1:8793/incidents", timeout=2).read()
        )
        mine = [i for i in listing if i["household_id"] == "amazon-demo-1"]
        assert mine, listing
        full = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:8793/incidents/{mine[-1]['id']}", timeout=2
            ).read()
        )
        assert full["status"] == "resolved"
        assert any(e["tool"] == "resolve" for e in full["events"])
        agent = json.loads(
            urllib.request.urlopen("http://127.0.0.1:8793/mcp-agent", timeout=2).read()
        )
        assert agent["active"] is True
        assert agent["incident_id"] == full["id"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)
