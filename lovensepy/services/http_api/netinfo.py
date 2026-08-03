"""Local network discovery so a phone can open the control panel without typing IPs."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

_DISCOVERY_TARGETS: tuple[tuple[str, int], ...] = (("192.168.255.255", 9), ("8.8.8.8", 53))


def primary_lan_ipv4() -> str | None:
    """Best guess for this host's LAN IPv4, using an unconnected UDP socket (no traffic)."""
    for host, port in _DISCOVERY_TARGETS:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.4)
            try:
                sock.connect((host, port))
                candidate = sock.getsockname()[0]
            except OSError:
                continue
        if _is_usable_ipv4(candidate):
            return candidate
    return None


def _is_usable_ipv4(value: str) -> bool:
    try:
        addr = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return not (addr.is_loopback or addr.is_link_local or addr.is_unspecified or addr.is_multicast)


def local_ipv4_addresses() -> list[str]:
    """All routable-looking IPv4 addresses of this host, primary interface first."""
    found: list[str] = []
    primary = primary_lan_ipv4()
    if primary:
        found.append(primary)
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        addr = str(info[4][0])
        if _is_usable_ipv4(addr) and addr not in found:
            found.append(addr)
    return found


def network_info(
    *,
    scheme: str,
    port: int | None,
    host_header: str | None = None,
    tunnel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """URLs that reach this service, for QR codes and "open on your phone" hints."""
    effective_port = port or (443 if scheme == "https" else 80)
    default_port = (scheme == "https" and effective_port == 443) or (
        scheme == "http" and effective_port == 80
    )

    def _url(host: str) -> str:
        return f"{scheme}://{host}" if default_port else f"{scheme}://{host}:{effective_port}"

    addresses = local_ipv4_addresses()
    lan_urls = [_url(addr) for addr in addresses]
    tunnel_url = None
    if tunnel and isinstance(tunnel.get("url"), str) and tunnel["url"].strip():
        tunnel_url = str(tunnel["url"]).rstrip("/")
    # Prefer the public HTTPS tunnel when present — phones off this Wi-Fi can use it,
    # and browsers treat it as a secure context (clipboard / wake lock work).
    primary = tunnel_url or (lan_urls[0] if lan_urls else _url("127.0.0.1"))
    return {
        "scheme": scheme,
        "port": effective_port,
        "hostname": socket.gethostname(),
        "local_url": _url("127.0.0.1"),
        "lan_addresses": addresses,
        "lan_urls": lan_urls,
        "primary_url": primary,
        "tunnel_url": tunnel_url,
        "tunnel": tunnel,
        "request_host": host_header,
        "secure_context": scheme == "https" or bool(tunnel_url),
    }
