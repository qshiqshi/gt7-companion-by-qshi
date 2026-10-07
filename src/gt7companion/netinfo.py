"""Which home networks is this computer part of?

Used for two things: finding the PS5 (a heartbeat goes to every address of
each own network) and telling the user under which address other devices
reach the dashboard.
"""
from __future__ import annotations

import ipaddress
import logging
import socket

log = logging.getLogger("netinfo")

# A home network is at most this large for our purposes: bigger networks are
# only searched in the /24 around the own address.
_MAX_PREFIX = 24


def _usable(ip: ipaddress.IPv4Address) -> bool:
    """Private LAN address (no loopback, no self-assigned 169.254.x.x)."""
    return ip.is_private and not ip.is_loopback and not ip.is_link_local


def _default_route_address() -> str | None:
    """Address of the interface that would reach the internet (no packet is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))          # TEST-NET-1, never routed
            return probe.getsockname()[0]
    except OSError:
        return None


def local_networks() -> list[ipaddress.IPv4Interface]:
    """Own private IPv4 addresses with their network, default route first."""
    found: dict[str, ipaddress.IPv4Interface] = {}
    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for entry in adapter.ips:
                if not entry.is_IPv4:
                    continue
                try:
                    interface = ipaddress.IPv4Interface(f"{entry.ip}/{entry.network_prefix}")
                except ValueError:
                    continue
                if _usable(interface.ip):
                    found.setdefault(str(interface.ip), interface)
    except Exception:  # missing module or an adapter the library cannot read
        log.debug("Could not list network adapters", exc_info=True)

    first = _default_route_address()
    if first and first not in found:
        try:
            address = ipaddress.IPv4Address(first)
            if _usable(address):
                found[first] = ipaddress.IPv4Interface(f"{first}/{_MAX_PREFIX}")
        except ValueError:
            pass
    return sorted(found.values(), key=lambda item: (str(item.ip) != first, str(item.ip)))


def local_addresses() -> list[str]:
    """Own private IPv4 addresses as text, default route first."""
    return [str(interface.ip) for interface in local_networks()]


def sweep_targets(networks: list[ipaddress.IPv4Interface] | None = None) -> list[str]:
    """Every other host address in the own home networks (at most a /24 each)."""
    networks = local_networks() if networks is None else networks
    targets: list[str] = []
    seen = {str(interface.ip) for interface in networks}       # never ourselves
    for interface in networks:
        prefix = max(interface.network.prefixlen, _MAX_PREFIX)
        network = ipaddress.IPv4Network(f"{interface.ip}/{prefix}", strict=False)
        for host in network.hosts():
            text = str(host)
            if text not in seen:
                seen.add(text)
                targets.append(text)
    return targets
