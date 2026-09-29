"""Alexa+ sim client (MCP client over Streamable HTTP) drives a live server."""

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
        assert final.get("status") in {"exhausted", "open"}
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
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _session_ids(log):
    ids = []
    for line in log:
        if line.startswith("SESSION ") and " rung=" in line and " status=" in line:
            body = line.split("SESSION ", 1)[1]
            key = body.split(" rung=", 1)[0]
            ids.append(key.split(":", 1)[1])
    return ids


def test_sim_session_banner_same_incident_silence_path():
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
            run_sim("http://127.0.0.1:8793", cue_kind="no_movement", answer="", verbose=False)
        )
        banners = [line for line in log if line.startswith("SESSION ") and "rung=" in line]
        assert banners, log
        assert all(" status=" in line for line in banners)
        ids = _session_ids(log)
        assert ids and len(set(ids)) == 1
        assert final.get("incident_id") == ids[0]
        assert any("start_or_resume_incident" in line for line in log)
        assert any("notify_caretaker" in line for line in log)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sim_soft_ok_resume_same_incident():
    config = uvicorn.Config(
        create_app(store=AuditStore()), host="127.0.0.1", port=8794, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8794/plan", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        log, final = asyncio.run(
            run_sim(
                "http://127.0.0.1:8794",
                cue_kind="no_movement",
                answer="don't worry",
                verbose=False,
            )
        )
        assert any("resume-same-incident" in line for line in log)
        assert any("check_in_prompt" in line for line in log)
        assert any("resolve_incident" in line for line in log)
        ids = _session_ids(log)
        assert ids and len(set(ids)) == 1
        assert final.get("incident_id") == ids[0]
        assert final.get("status") == "resolved"
        assert any("SESSION " in line and "status=resolved" in line for line in log)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_sim_needs_human_resume_same_incident():
    config = uvicorn.Config(
        create_app(store=AuditStore()), host="127.0.0.1", port=8795, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            urllib.request.urlopen("http://127.0.0.1:8795/plan", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    try:
        log, final = asyncio.run(
            run_sim(
                "http://127.0.0.1:8795",
                cue_kind="no_movement",
                answer="I'm okay but I think I'm hurt",
                verbose=False,
            )
        )
        assert any("resume-same-incident" in line for line in log)
        assert any("check_in_prompt" in line for line in log)
        assert any("notify_caretaker" in line for line in log)
        assert not any("resolve_incident" in line for line in log)
        ids = _session_ids(log)
        assert ids and len(set(ids)) == 1
        assert final.get("incident_id") == ids[0]
        assert final.get("status") != "resolved"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
