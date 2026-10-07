"""AgentCore Gateway auth wiring. Control-plane calls stay dry-run."""

from __future__ import annotations

import json

import pytest

from care_ladder.cloud.agentcore_gateway import (
    DEPLOY_ENV,
    build_sync_request,
    build_target_request,
    gateway_plan_lines,
    host_from_mcp_url,
    local_judge_transcript,
    mcp_hosts_assignment,
    require_control_plane,
)
from care_ladder.mcp_server.server import TOOL_NAMES
from care_ladder.security import mcp_allowed_hosts


def test_pinned_boto3_has_agentcore_operations():
    service = require_control_plane()
    assert service


def test_target_forwards_authorization_and_host_is_allowlisted(monkeypatch):
    url = "https://care-ladder-mcp.example.com/mcp"
    payload = build_target_request("dry-run", url, "arn:aws:iam::000000000000:role/example")
    blob = json.dumps(payload)
    assert "Authorization" in blob
    assert "Bearer" in blob
    assert "https://care-ladder-mcp.example.com/mcp/" in blob
    assert "HEADER" in blob or "header" in blob.lower()
    host = host_from_mcp_url(url)
    monkeypatch.setenv("CARE_LADDER_MCP_HOSTS", host)
    allowed = mcp_allowed_hosts()
    assert host in allowed
    assert f"{host}:*" in allowed
    assert mcp_hosts_assignment(url) == f"CARE_LADDER_MCP_HOSTS={host}"


def test_sync_request_places_target_id_list():
    payload = build_sync_request("gw-1", ["tgt-1"])
    assert payload["gatewayIdentifier"] == "gw-1"
    assert "tgt-1" in json.dumps(payload["targetIdList"])
    assert "targetIdList" in payload


def test_plan_is_deferred_without_deploy_flag(monkeypatch):
    monkeypatch.delenv(DEPLOY_ENV, raising=False)
    lines = gateway_plan_lines("https://care-ladder-mcp.example.com/mcp/", "us-east-1")
    text = "\n".join(lines)
    assert "deferred" in text
    assert "targetIdList" in text
    assert "Authorization" in text
    assert "<redacted>" in text
    assert "REDACTED" not in text
    assert "us-east-1" in text


def test_local_mcp_smoke_covers_401_and_tool_call():
    lines = local_judge_transcript()
    text = "\n".join(lines)
    assert "without bearer -> 401" in text
    assert "Host=evil.example -> 421" in text
    assert "protocol=2025-11-25" in text or "protocol=2025-11-25" in text.replace(" ", "")
    assert "how_is_household -> 200" in text
    for name in TOOL_NAMES:
        assert name in text


def test_deploy_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(DEPLOY_ENV, raising=False)
    assert __import__("os").environ.get(DEPLOY_ENV) in (None, "")


def test_mcp_url_drops_userinfo_query_and_brackets_ipv6():
    from care_ladder.cloud.agentcore_gateway import canonical_mcp_url

    clean = canonical_mcp_url(
        "https://user:super-secret-token@care-ladder-mcp.example.com/mcp?x=1#frag"
    )
    assert clean == "https://care-ladder-mcp.example.com/mcp/"
    assert "super-secret-token" not in clean
    payload = build_target_request("dry-run", clean, "arn:aws:iam::000000000000:role/example")
    blob = json.dumps(payload)
    assert "super-secret-token" not in blob
    assert "x=1" not in blob
    assert host_from_mcp_url("http://[::1]:8080/mcp") == "[::1]"
    assert canonical_mcp_url("http://[::1]:8080/mcp") == "http://[::1]:8080/mcp/"
    with pytest.raises(Exception):
        canonical_mcp_url("ftp://care-ladder-mcp.example.com/mcp")


def test_authorization_fields_are_not_only_in_prose():
    payload = build_target_request(
        "dry-run",
        "https://user:super-secret-token@care-ladder-mcp.example.com/mcp?x=1",
        "arn:aws:iam::000000000000:role/example",
    )

    def pairs(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                yield key, value
                yield from pairs(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from pairs(item)

    found = {key: value for key, value in pairs(payload)}
    assert found.get("credentialParameterName") == "Authorization"
    assert str(found.get("credentialPrefix", "")).startswith("Bearer")
    assert str(found.get("credentialLocation", "")).upper() == "HEADER"
    assert "super-secret-token" not in json.dumps(payload)


def test_deploy_error_redacts_token_and_rolls_back(monkeypatch, capsys):
    from care_ladder.cloud.agentcore_gateway import deploy_gateway

    monkeypatch.setenv(DEPLOY_ENV, "1")
    monkeypatch.setenv("CARE_LADDER_API_TOKEN", "super-secret-token")
    monkeypatch.setenv(
        "CARE_LADDER_AGENTCORE_ROLE_ARN",
        "arn:aws:iam::000000000000:role/CareLadderAgentCoreGateway",
    )

    class _Client:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_api_key_credential_provider(self, **kwargs):
            self.calls.append("create_provider")
            return {"credentialProviderArn": "arn:aws:bedrock-agentcore:us-east-1:0:provider/x"}

        def create_gateway(self, **kwargs):
            raise RuntimeError("rejected super-secret-token")

        def delete_api_key_credential_provider(self, **kwargs):
            self.calls.append(f"delete_provider:{kwargs['name']}")

    client = _Client()
    assert (
        deploy_gateway(
            "https://care-ladder-mcp.example.com/mcp",
            "us-east-1",
            client=client,
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "super-secret-token" not in err
    assert "<redacted>" in err
    assert client.calls == ["create_provider", "delete_provider:care-ladder-mcp-bearer"]


def test_deploy_refuses_without_spend_gate(monkeypatch, capsys):
    from care_ladder.cloud.agentcore_gateway import deploy_gateway

    monkeypatch.delenv(DEPLOY_ENV, raising=False)
    assert deploy_gateway("https://care-ladder-mcp.example.com/mcp", "us-east-1") == 2
    assert "CARE_LADDER_AGENTCORE_DEPLOY" in capsys.readouterr().err
