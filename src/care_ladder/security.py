"""API bearer token + camera URL allowlist (audit §02)."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

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


def validate_camera_source(source: object) -> None:
    """Allow device indices; restrict URL sources to scheme+host allowlist.

    Cloud-metadata IPs/hosts are always rejected, even if listed in env.
    """
    if isinstance(source, bool):
        raise ValueError("source must be a device index or rtsp/http URL")
    if isinstance(source, int):
        if source < 0:
            raise ValueError("device index must be >= 0")
        return
    if isinstance(source, str) and source.isdigit():
        return
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

    ip = _ip_from_host(host)
    if ip is not None and _is_metadata_ip(ip):
        raise ValueError("camera URL host is not allowlisted")

    if host not in camera_allowed_hosts() and (ip is None or str(ip) not in camera_allowed_hosts()):
        raise ValueError("camera URL host is not allowlisted")
