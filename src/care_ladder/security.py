"""API bearer token + camera URL allowlist (audit §02)."""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse, urlunparse

TOKEN_ENV = "CARE_LADDER_API_TOKEN"
INSECURE_LOCAL_ENV = "CARE_LADDER_ALLOW_INSECURE_LOCAL"
MCP_HOSTS_ENV = "CARE_LADDER_MCP_HOSTS"
CAMERA_HOSTS_ENV = "CARE_LADDER_CAMERA_HOSTS"

_ALLOWED_SCHEMES = frozenset({"rtsp", "http", "https"})
_DEFAULT_CAMERA_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.com",
        "metadata.aws.internal",
    }
)
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("169.254.170.2"),
        ipaddress.ip_address("fd00:ec2::254"),
        ipaddress.ip_address("100.100.100.200"),
    }
)
_DEFAULT_MCP_HOSTS = (
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
    "testserver",
    "testserver:*",
)


def configured_token() -> str | None:
    token = os.environ.get(TOKEN_ENV, "").strip()
    return token or None


def insecure_local_allowed() -> bool:
    return os.environ.get(INSECURE_LOCAL_ENV, "").strip().lower() in {"1", "true", "yes"}


def auth_required() -> bool:
    """Fail closed unless a token is set or the documented local opt-out is on."""
    if configured_token():
        return True
    return not insecure_local_allowed()


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, rest = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return rest.strip()


def mcp_allowed_hosts() -> list[str]:
    hosts = list(_DEFAULT_MCP_HOSTS)
    extra = os.environ.get(MCP_HOSTS_ENV, "")
    for raw in extra.split(","):
        host = raw.strip()
        if not host:
            continue
        hosts.append(host)
        if not _host_has_port(host):
            hosts.append(f"{host}:*")
    return hosts


def _host_has_port(host: str) -> bool:
    if host.endswith(":*"):
        return True
    if host.startswith("["):
        return "]:" in host
    # "example.com:443" vs "127.0.0.1" — one colon that is a port, not IPv6.
    return host.count(":") == 1


def camera_allowed_hosts() -> set[str]:
    hosts = set(_DEFAULT_CAMERA_HOSTS)
    extra = os.environ.get(CAMERA_HOSTS_ENV, "")
    for raw in extra.split(","):
        host = raw.strip().lower()
        if host:
            hosts.add(host)
    return hosts


def _ip_from_host(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host.isdigit():
            try:
                ip = ipaddress.ip_address(int(host))
            except ValueError:
                return None
        else:
            return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_metadata_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip in _METADATA_IPS


def _resolved_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = _ip_from_host(host)
    if literal is not None:
        return [literal]
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        for info in socket.getaddrinfo(host, None):
            parsed = _ip_from_host(info[4][0])
            if parsed is not None:
                found.append(parsed)
    except OSError:
        return []
    return found


def redact_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    return f"****{phone[-2:]}" if len(phone) >= 2 else "****"


def redact_phones(obj: Any) -> Any:
    """Walk JSON-ish structures and mask every ``phone_e164`` field."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key == "phone_e164" and isinstance(value, str):
                out[key] = redact_phone(value)
            else:
                out[key] = redact_phones(value)
        return out
    if isinstance(obj, list):
        return [redact_phones(item) for item in obj]
    return obj


def _pinned_url(source: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Rewrite the URL host to an IP literal so later connect cannot DNS-rebind."""
    parsed = urlparse(source)
    host = f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunparse(
        (
            parsed.scheme,
            f"{userinfo}{host}{port}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def validate_camera_source(source: object) -> object:
    """Allow device indices; restrict URL sources to scheme+host allowlist.

    Cloud-metadata IPs/hosts are always rejected, even if listed in env.
    Hostname URLs are rewritten to the resolved IP so VideoCapture cannot
    rebind DNS between check and connect.
    """
    if isinstance(source, bool):
        raise ValueError("source must be a device index or rtsp/http URL")
    if isinstance(source, int):
        if source < 0:
            raise ValueError("device index must be >= 0")
        return source
    if isinstance(source, str) and source.isdigit():
        return source
    if not isinstance(source, str):
        raise ValueError("source must be a device index or rtsp/http URL")

    parsed = urlparse(source)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("source must be a device index or rtsp/http URL")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("camera URL host is missing")
    if host in _METADATA_HOSTS:
        raise ValueError("camera URL host is not allowlisted")

    ips = _resolved_ips(host)
    if _ip_from_host(host) is None and not ips:
        raise ValueError("camera URL host could not be resolved")
    if any(_is_metadata_ip(ip) for ip in ips):
        raise ValueError("camera URL host is not allowlisted")

    allowed = camera_allowed_hosts()
    if host not in allowed and not any(str(ip) in allowed for ip in ips):
        raise ValueError("camera URL host is not allowlisted")
    if _ip_from_host(host) is not None or not ips:
        return source
    return _pinned_url(source, ips[0])
