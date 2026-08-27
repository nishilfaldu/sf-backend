"""Detect IPv4 addresses other devices on the same Wi-Fi can use to reach us."""

from __future__ import annotations

import socket


def _is_usable(ip: str) -> bool:
    if not ip or ip.startswith("127.") or ip.startswith("169.254."):
        return False
    if ip.startswith("::") or ":" in ip:
        return False
    return True


def _rank(ip: str) -> tuple[int, str]:
    """Prefer typical Wi-Fi ranges so a VPN or Docker bridge is not listed first."""
    if ip.startswith("192.168."):
        return (0, ip)
    if ip.startswith("10."):
        return (1, ip)
    parts = ip.split(".")
    if len(parts) == 4 and parts[0] == "172":
        try:
            second = int(parts[1])
        except ValueError:
            return (9, ip)
        if 16 <= second <= 31:
            return (2, ip)
    return (9, ip)


def lan_ipv4_addresses() -> list[str]:
    """Return unique non-loopback IPv4 addresses for this host, Wi-Fi-first."""
    found: set[str] = set()

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # TEST-NET-1: connecting sends no packets; it just asks the OS which
            # source address it would use for an outbound IPv4 route.
            sock.connect(("192.0.2.1", 80))
            ip = sock.getsockname()[0]
            if _is_usable(ip):
                found.add(ip)
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _is_usable(ip):
                found.add(ip)
    except OSError:
        pass

    return sorted(found, key=_rank)
