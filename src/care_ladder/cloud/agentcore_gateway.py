"""AgentCore Gateway plan for the care-ladder MCP tools.

Self-hosted /mcp and alexa_sim stay the Alexa+ path. This module builds the
control-plane requests: credential provider, Authorization header forwarded
to the MCP target, and the target hostname for CARE_LADDER_MCP_HOSTS.

Live create stays off unless CARE_LADDER_AGENTCORE_DEPLOY=1.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

from care_ladder.aws_shape import (
    AwsShapeError,
    _structure_members,
    build_operation,
    input_shape,
    service_model,
    strings_as_list_member,
    validate_payload,
)
from care_ladder.mcp_server.server import TOOL_NAMES
from care_ladder.security import MCP_HOSTS_ENV

DEPLOY_ENV = "CARE_LADDER_AGENTCORE_DEPLOY"
CONTROL_CANDIDATES = ("bedrock-agentcore-control", "bedrock-agentcore")
REQUIRED_OPS = (
    "CreateGateway",
    "CreateGatewayTarget",
    "SynchronizeGatewayTargets",
    "CreateApiKeyCredentialProvider",
)
_PLACEHOLDER_ROLE = "arn:aws:iam::000000000000:role/CareLadderAgentCoreGateway"
_PLACEHOLDER_PROVIDER = (
    "arn:aws:bedrock-agentcore:us-east-1:000000000000:"
    "token-vault/care-ladder/apikeycredentialprovider/care-ladder-mcp-bearer"
)


class AgentCoreConfigError(RuntimeError):
    """The pinned SDK cannot express the gateway request, or config is incomplete."""


logger = logging.getLogger("care_ladder.agentcore_gateway")
_SECRET_FIELD_PREFERENCE = ("apiKey", "apiKeyValue", "secret", "token", "credential")


def control_service() -> str:
    errors: list[str] = []
    for name in CONTROL_CANDIDATES:
        try:
            model = service_model(name)
        except AwsShapeError as exc:
            errors.append(str(exc))
            continue
        if "CreateGateway" in model.operation_names:
            return name
        errors.append(f"{name} has no CreateGateway")
    raise AgentCoreConfigError(
        "pinned boto3 has no AgentCore CreateGateway. " + "; ".join(errors)
    )


def require_control_plane() -> str:
    service = control_service()
    model = service_model(service)
    missing = [op for op in REQUIRED_OPS if op not in model.operation_names]
    if missing:
        similar = [
            n
            for n in model.operation_names
            if "Gateway" in n or "Credential" in n or "ApiKey" in n
        ]
        raise AgentCoreConfigError(
            f"{service} missing {missing}. Similar: {similar[:30]}"
        )
    return service


def canonical_mcp_url(mcp_url: str) -> str:
    """scheme://host[:port]/path/ with userinfo, query, and fragment removed."""
    parsed = urlparse(mcp_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AgentCoreConfigError("MCP url needs an http(s) host")
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunparse((parsed.scheme, netloc, path, "", "", ""))


def host_from_mcp_url(mcp_url: str) -> str:
    parsed = urlparse(canonical_mcp_url(mcp_url))
    host = parsed.hostname
    if not host:
        raise AgentCoreConfigError("MCP url needs an http(s) host")
    if ":" in host:
        return f"[{host}]"
    return host


def mcp_hosts_assignment(mcp_url: str) -> str:
    """Env line the ALB/target task must set so the Host header passes the allowlist."""
    return f"{MCP_HOSTS_ENV}={host_from_mcp_url(mcp_url)}"


def region_note(region: str) -> str:
    import boto3

    service = control_service()
    regions = boto3.Session().get_available_regions(service)
    if not regions:
        return (
            f"{service}: SDK lists no regions. "
            f"Requested {region}. A URL target can still be used if that is deliberate."
        )
    if region in regions:
        return f"{service} region {region} is in the SDK list ({len(regions)} regions)"
    return (
        f"{service} region {region} is not in the SDK list. "
        "URL targets can still be used if this mismatch is deliberate. "
        f"Listed: {', '.join(regions)}"
    )


def _api_key_field(shape: Any) -> str:
    model = getattr(shape, "_shape_model", None) or {}
    raw = model.get("members") or {}
    shape_map = shape._shape_resolver._shape_map

    def _type_name(ref: Any) -> str:
        if not isinstance(ref, dict) or "shape" not in ref:
            return ""
        return str(shape_map.get(ref["shape"], {}).get("type", ""))

    members = {name: _type_name(ref) for name, ref in raw.items()}
    for name in _SECRET_FIELD_PREFERENCE:
        if members.get(name) == "string":
            return name
    for member_name, type_name in members.items():
        if type_name != "string":
            continue
        lowered = member_name.lower()
        if any(bad in lowered for bad in ("arn", "description", "url")):
            continue
        if any(token in lowered for token in ("key", "secret", "token", "credential")):
            return member_name
    raise AgentCoreConfigError(
        "CreateApiKeyCredentialProvider has no string secret field: "
        + ", ".join(members)
    )


def build_api_key_request(name: str, api_key: str) -> dict[str, Any]:
    if not name.strip():
        raise AgentCoreConfigError("credential provider name is empty")
    if not api_key.strip():
        raise AgentCoreConfigError("API key is empty")
    service = require_control_plane()
    shape = input_shape(service, "CreateApiKeyCredentialProvider")
    member_names = list((getattr(shape, "_shape_model", None) or {}).get("members") or {})
    if "name" not in member_names:
        raise AgentCoreConfigError(
            "CreateApiKeyCredentialProvider has no name field: "
            + ", ".join(member_names)
        )
    secret_field = _api_key_field(shape)
    payload = {"name": name, secret_field: api_key}
    validate_payload(service, "CreateApiKeyCredentialProvider", payload)
    return payload


def build_gateway_request(name: str, role_arn: str) -> dict[str, Any]:
    service = require_control_plane()
    return build_operation(
        service,
        "CreateGateway",
        {
            "name": name,
            "roleArn": role_arn,
            "protocolType": "MCP",
            "authorizerType": "AWS_IAM",
        },
        {
            "description": "Care Ladder MCP front door. Not a medical device.",
            "instructions": (
                "Household care-ladder tools. Not a medical device. "
                "Do not call emergency services."
            ),
            "searchType": "SEMANTIC",
            "supportedVersions": ["2025-11-25"],
        },
    )


def build_target_request(gateway_id: str, mcp_url: str, provider_arn: str) -> dict[str, Any]:
    """Credential provider at the gateway; Authorization forwarded to the MCP URL."""
    endpoint = canonical_mcp_url(mcp_url)
    service = require_control_plane()
    return build_operation(
        service,
        "CreateGatewayTarget",
        {
            "gatewayIdentifier": gateway_id,
            "name": "care-ladder-mcp",
            "endpoint": endpoint,
            "credentialProviderType": "API_KEY",
            "providerArn": provider_arn,
            "credentialLocation": "HEADER",
            "credentialParameterName": "Authorization",
            "credentialPrefix": "Bearer",
        },
        {
            "description": "Forwards Authorization to self-hosted /mcp. Does not replace alexa_sim.",
        },
    )


def build_sync_request(gateway_id: str, target_ids: list[str]) -> dict[str, Any]:
    if (
        not isinstance(gateway_id, str)
        or not gateway_id.strip()
        or not target_ids
        or any(not isinstance(item, str) or not item.strip() for item in target_ids)
    ):
        raise AgentCoreConfigError(
            "SynchronizeGatewayTargets needs a gateway id and targetIdList"
        )
    service = require_control_plane()
    shape = input_shape(service, "SynchronizeGatewayTargets")
    members = dict(_structure_members(shape))
    if "gatewayIdentifier" not in members or "targetIdList" not in members:
        raise AgentCoreConfigError(
            "SynchronizeGatewayTargets members: " + ", ".join(sorted(members))
        )
    ids = [item.strip() for item in target_ids]
    payload = {
        "gatewayIdentifier": gateway_id.strip(),
        "targetIdList": strings_as_list_member(members["targetIdList"], ids),
    }
    missing = sorted(
        name
        for name in (getattr(shape, "required_members", []) or [])
        if name not in payload
    )
    if missing:
        raise AgentCoreConfigError(
            "SynchronizeGatewayTargets also requires " + ", ".join(missing)
        )
    validate_payload(service, "SynchronizeGatewayTargets", payload)
    return payload


def redact(obj: Any, secrets: set[str]) -> Any:
    usable = {s for s in secrets if isinstance(s, str) and len(s) >= 8}
    if isinstance(obj, dict):
        return {k: redact(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        if obj in secrets:
            return "<redacted>"
        out = obj
        for secret in usable:
            out = out.replace(secret, "<redacted>")
        return out
    return obj


def public_error(exc: BaseException, secret: str) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if len(secret) >= 8:
        text = text.replace(secret, "<redacted>")
    return text


def find_arn(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if (
                isinstance(value, str)
                and key.lower().endswith("arn")
                and value.startswith("arn:")
            ):
                return value
        for value in obj.values():
            found = find_arn(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_arn(item)
            if found:
                return found
    return None


def _rollback_call(client: Any, method: str, kwargs: dict[str, Any]) -> None:
    fn = getattr(client, method, None)
    if fn is None:
        return
    try:
        fn(**kwargs)
    except Exception as exc:
        logger.warning("rollback %s failed: %s", method, type(exc).__name__)


def _rollback_gateway(
    client: Any,
    *,
    provider_name: str | None,
    gateway_id: str | None,
    target_id: str | None,
) -> None:
    if gateway_id and target_id:
        _rollback_call(
            client,
            "delete_gateway_target",
            {"gatewayIdentifier": gateway_id, "targetId": target_id},
        )
    if gateway_id:
        _rollback_call(client, "delete_gateway", {"gatewayIdentifier": gateway_id})
    if provider_name:
        _rollback_call(
            client,
            "delete_api_key_credential_provider",
            {"name": provider_name},
        )


def _gateway_id(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for key in ("gatewayId", "gatewayIdentifier"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for value in obj.values():
        if isinstance(value, dict):
            found = _gateway_id(value)
            if found:
                return found
    return None


def _target_id(obj: Any) -> str | None:
    if not isinstance(obj, dict):
        return None
    for key in ("targetId", "gatewayTargetId"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def provision_gateway(
    client: Any,
    *,
    api_request: dict[str, Any],
    gateway_request: dict[str, Any],
    mcp_url: str,
) -> str:
    """Create provider, gateway, target, then sync. Roll back earlier resources on failure."""
    provider_name = api_request.get("name")
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise AgentCoreConfigError("credential provider request has no name")
    provider = client.create_api_key_credential_provider(**api_request)
    provider_arn = find_arn(provider)
    if not provider_arn:
        _rollback_gateway(
            client, provider_name=provider_name, gateway_id=None, target_id=None
        )
        raise AgentCoreConfigError("create_api_key_credential_provider returned no arn")
    gateway_id: str | None = None
    target_id: str | None = None
    try:
        gateway = client.create_gateway(**gateway_request)
        gateway_id = _gateway_id(gateway)
        if not gateway_id:
            raise AgentCoreConfigError("create_gateway returned no id")
        target = client.create_gateway_target(
            **build_target_request(gateway_id, mcp_url, provider_arn)
        )
        target_id = _target_id(target)
        if not target_id:
            raise AgentCoreConfigError("create_gateway_target returned no id")
        client.synchronize_gateway_targets(
            **build_sync_request(gateway_id, [target_id])
        )
        return gateway_id
    except Exception:
        _rollback_gateway(
            client,
            provider_name=provider_name,
            gateway_id=gateway_id,
            target_id=target_id,
        )
        raise


def _parse_mcp(resp: Any) -> dict[str, Any]:
    text = resp.text
    if text.startswith("event:") or text.startswith("data:"):
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AgentCoreConfigError(f"no data line in MCP response: {text[:200]}")
    return json.loads(text)


def _mcp_post(
    client: Any,
    body: dict[str, Any],
    *,
    token: str | None = None,
    host: str | None = None,
    session_id: str | None = None,
) -> Any:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if host:
        # Match the request target to Host. A Host that disagrees with the
        # testclient base is not what the app checks, and the /mcp -> /mcp/
        # redirect then drops Authorization and comes back 401.
        return client.post(
            f"http://{host}/mcp",
            json=body,
            headers=headers,
            follow_redirects=False,
        )
    return client.post("/mcp", json=body, headers=headers)


def _initialize_body() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "care-ladder-gateway-smoke", "version": "0"},
        },
    }


def local_judge_transcript() -> list[str]:
    """initialize, tools/list, tools/call against in-process /mcp. No AWS calls."""
    from fastapi.testclient import TestClient

    from care_ladder.api.app import create_app
    from care_ladder.audit.store import AuditStore

    token = "phase-a-smoke-token"
    saved = {
        "CARE_LADDER_API_TOKEN": os.environ.get("CARE_LADDER_API_TOKEN"),
        "CARE_LADDER_ALLOW_INSECURE_LOCAL": os.environ.get("CARE_LADDER_ALLOW_INSECURE_LOCAL"),
    }
    os.environ["CARE_LADDER_API_TOKEN"] = token
    os.environ.pop("CARE_LADDER_ALLOW_INSECURE_LOCAL", None)
    lines: list[str] = []
    names: list[str] = []
    try:
        with TestClient(create_app(store=AuditStore())) as client:
            bare = _mcp_post(client, _initialize_body())
            lines.append(f"POST /mcp initialize without bearer -> {bare.status_code}")
            foreign = _mcp_post(client, _initialize_body(), token=token, host="evil.example")
            lines.append(f"POST /mcp initialize Host=evil.example -> {foreign.status_code}")
            ok = _mcp_post(client, _initialize_body(), token=token)
            parsed = _parse_mcp(ok)
            protocol = (parsed.get("result") or {}).get("protocolVersion")
            session_id = ok.headers.get("mcp-session-id")
            lines.append(
                f"POST /mcp initialize -> {ok.status_code} protocol={protocol}"
            )
            listed = _mcp_post(
                client,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                token=token,
                session_id=session_id,
            )
            tools = _parse_mcp(listed).get("result", {}).get("tools") or []
            names = sorted(tool.get("name", "") for tool in tools)
            lines.append(
                f"POST /mcp tools/list -> {listed.status_code} tools={','.join(names)}"
            )
            called = _mcp_post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "how_is_household",
                        "arguments": {"household_id": "amazon-demo-1"},
                    },
                },
                token=token,
                session_id=session_id,
            )
            lines.append(f"POST /mcp tools/call how_is_household -> {called.status_code}")
            if "quiet" not in called.text.lower():
                raise AgentCoreConfigError(
                    "how_is_household response did not include the quiet-household line"
                )
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if names != sorted(TOOL_NAMES):
        raise AgentCoreConfigError(f"tools/list {names} != {sorted(TOOL_NAMES)}")
    return lines


def gateway_plan_lines(mcp_url: str, region: str) -> list[str]:
    """Dry-run control-plane bodies. Prints no live gateway id."""
    service = require_control_plane()
    secret = "REDACTED"
    api_req = build_api_key_request("care-ladder-mcp-bearer", secret)
    gateway_req = build_gateway_request("care-ladder", _PLACEHOLDER_ROLE)
    target_req = build_target_request("dry-run", mcp_url, _PLACEHOLDER_PROVIDER)
    sync_req = build_sync_request("dry-run", ["dry-run"])
    shown = redact(
        {
            "service": service,
            "CreateApiKeyCredentialProvider": api_req,
            "CreateGateway": gateway_req,
            "CreateGatewayTarget": target_req,
            "SynchronizeGatewayTargets": sync_req,
        },
        {secret},
    )
    blob = json.dumps(shown)
    if "Authorization" not in blob:
        raise AgentCoreConfigError("gateway target does not forward Authorization")
    if "HEADER" not in blob and "header" not in blob.lower():
        raise AgentCoreConfigError("gateway target does not set a header credential location")
    lines = [
        region_note(region),
        mcp_hosts_assignment(mcp_url),
        "shared opencv ALB is not the default target: /mcp 404 there as of docs/friction-log.md (2026-09-29)",
        "credential provider: API key at the gateway, value redacted, Authorization prefix Bearer",
        "payload: " + blob,
    ]
    if "2025-11-25" not in json.dumps(gateway_req):
        lines.append(
            "gateway request did not keep supportedVersions 2025-11-25. "
            "Self-hosted /mcp still negotiates that date. Gateway protocol list is whatever the SDK accepted."
        )
    lines.append(
        "gateway id: deferred "
        f"({DEPLOY_ENV} is not 1; /mcp and alexa_sim are unchanged)"
    )
    return lines


def deploy_gateway(mcp_url: str, region: str, *, client: Any | None = None) -> int:
    """Create the provider, gateway, target, and sync. Spend gate is the env flag."""
    if os.environ.get(DEPLOY_ENV, "").strip() != "1":
        print(f"BLOCKER: deploy requires {DEPLOY_ENV}=1", file=sys.stderr)
        return 2
    token = os.environ.get("CARE_LADDER_API_TOKEN", "").strip()
    role = os.environ.get("CARE_LADDER_AGENTCORE_ROLE_ARN", "").strip()
    if not token or not role:
        print(
            "BLOCKER: deploy needs CARE_LADDER_API_TOKEN and CARE_LADDER_AGENTCORE_ROLE_ARN",
            file=sys.stderr,
        )
        return 2
    try:
        canonical_mcp_url(mcp_url)
        api_request = build_api_key_request("care-ladder-mcp-bearer", token)
        gateway_request = build_gateway_request("care-ladder", role)
        if client is None:
            import boto3

            service = require_control_plane()
            client = boto3.client(service, region_name=region)
        gateway_id = provision_gateway(
            client,
            api_request=api_request,
            gateway_request=gateway_request,
            mcp_url=mcp_url,
        )
    except Exception as exc:
        print(f"BLOCKER: {public_error(exc, token)}", file=sys.stderr)
        return 2
    print(f"gateway id: {gateway_id}")
    print(mcp_hosts_assignment(mcp_url))
    print("token was stored in the credential provider and is not printed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentCore Gateway smoke for Care Ladder MCP")
    parser.add_argument(
        "--mcp-url",
        default=os.environ.get(
            "CARE_LADDER_GATEWAY_MCP_URL",
            "https://care-ladder-mcp.example.com/mcp/",
        ),
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("CARE_LADDER_AGENTCORE_REGION", "us-east-1"),
    )
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args(argv)
    try:
        for line in local_judge_transcript():
            print(line)
        for line in gateway_plan_lines(args.mcp_url, args.region):
            print(line)
    except (AgentCoreConfigError, AwsShapeError, OSError, ValueError) as exc:
        print(f"BLOCKER: {exc}", file=sys.stderr)
        return 2
    if args.deploy:
        return deploy_gateway(args.mcp_url, args.region)
    return 0


if __name__ == "__main__":
    sys.exit(main())
