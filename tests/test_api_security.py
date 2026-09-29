"""Bearer auth on mutating/MCP routes + camera URL allowlist (audit §02)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from care_ladder.api.app import create_app
from care_ladder.audit.store import AuditStore
from care_ladder.security import validate_camera_source


def _client():
    return TestClient(create_app(store=AuditStore()))


def _mcp_initialize_body() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "auth-test", "version": "0"},
        },
    }


def _mcp_headers(token: str | None = None, host: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
    return headers


def test_demo_run_and_mcp_require_bearer_when_token_set(monkeypatch):
    monkeypatch.delenv("CARE_LADDER_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.setenv("CARE_LADDER_API_TOKEN", "secret-token")

    with _client() as client:
        bare = client.post("/demo/run", json={"fixture": "alexa_path_a_soft_ok"})
        assert bare.status_code == 401

        mcp_bare = client.post("/mcp", json=_mcp_initialize_body(), headers=_mcp_headers())
        assert mcp_bare.status_code == 401

        ok = client.post(
            "/demo/run",
            json={"fixture": "alexa_path_a_soft_ok"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert ok.status_code == 200, ok.text

        mcp_ok = client.post(
            "/mcp",
            json=_mcp_initialize_body(),
            headers=_mcp_headers("secret-token"),
        )
        assert mcp_ok.status_code == 200, mcp_ok.text


def test_mutating_routes_fail_closed_without_token_or_local_opt_out(monkeypatch):
    monkeypatch.delenv("CARE_LADDER_ALLOW_INSECURE_LOCAL", raising=False)
    monkeypatch.delenv("CARE_LADDER_API_TOKEN", raising=False)

    with _client() as client:
        assert client.post("/demo/run", json={"fixture": "alexa_path_a_soft_ok"}).status_code == 401
        assert client.post("/demo/camera/stop").status_code == 401
        assert client.post("/incidents/nope/ack", json={}).status_code == 401
        assert client.post("/learning/demo-home-1/reset").status_code == 401
        # Read-only surfaces stay up so ALB / Fire TV polls still work.
        assert client.get("/plan").status_code == 200
        assert client.get("/incidents").status_code == 200


def test_mcp_rejects_foreign_host_when_dns_rebinding_on(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CARE_LADDER_API_TOKEN", raising=False)

    with _client() as client:
        r = client.post(
            "/mcp",
            json=_mcp_initialize_body(),
            headers=_mcp_headers(host="evil.example"),
        )
        assert r.status_code == 421, r.text


def test_validate_camera_source_allows_device_and_localhost_rejects_ssrf():
    validate_camera_source(0)
    validate_camera_source("rtsp://127.0.0.1:8554/cam")
    validate_camera_source("http://localhost/stream")

    for bad in (
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/v2/metadata",
        "http://[fd00:ec2::254]/latest/meta-data/",
        "http://metadata.google.internal/",
        "rtsp://evil.example/stream",
        "https://example.com/cam",
        "file:///etc/passwd",
    ):
        try:
            validate_camera_source(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected reject: {bad}")


def test_camera_start_rejects_metadata_url_before_open(monkeypatch):
    monkeypatch.setenv("CARE_LADDER_ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CARE_LADDER_API_TOKEN", raising=False)
    opened: list[object] = []

    def _should_not_open(**kwargs):
        opened.append(kwargs.get("source"))
        raise AssertionError("camera source must be rejected before VideoCapture")

    monkeypatch.setattr("care_ladder.vision.camera.start_session", _should_not_open)

    with _client() as client:
        r = client.post(
            "/demo/camera/start",
            json={"source": "http://169.254.169.254/latest/meta-data/"},
        )
        assert r.status_code == 400, r.text
        assert opened == []

        remote = client.post(
            "/demo/camera/start",
            json={"source": "rtsp://evil.example/stream"},
        )
        assert remote.status_code == 400, remote.text
        assert opened == []
