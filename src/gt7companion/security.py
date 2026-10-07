"""Who may do what.

Watching the dashboard is open to everyone in the home network. Changing
anything (layouts, settings) is only possible on the computer the program
runs on – other devices need the PIN (see ``pairing`` further down the road).

Two more rules keep web pages from the internet out, even though the program
only listens inside the home network:

* the ``Host`` of a request must be a local address or a local name, so a
  foreign domain that merely *resolves* to this computer is refused, and
* a page that was loaded from somewhere else may neither write nor open the
  live connection (``Origin`` must match ``Host``).
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

OWNER = "owner"        # the computer the program runs on: may change everything
VIEWER = "viewer"      # any other device: may watch

# Names that only exist inside a home network (never in the public DNS).
_LOCAL_SUFFIXES = (".local", ".localhost", ".lan", ".home", ".home.arpa", ".internal",
                   ".localdomain", ".fritz.box")
_FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


def _hostname(netloc: str) -> str:
    """``host`` of ``host:port``; IPv6 literals come without their brackets."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[1:].split("]", 1)[0]
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def is_loopback(host: str | None) -> bool:
    address = _address(host or "")
    return address is not None and address.is_loopback


def host_allowed(connection: HTTPConnection) -> bool:
    """The request names this computer by a local address or a local name."""
    host = _hostname(connection.headers.get("host", ""))
    if not host:
        return False
    address = _address(host)
    if address is not None:
        return address.is_loopback or address.is_private or address.is_link_local
    return "." not in host or host == "localhost" or host.endswith(_LOCAL_SUFFIXES)


def same_origin(connection: HTTPConnection) -> bool:
    """No ``Origin`` (not a browser page) or an ``Origin`` equal to ``Host``."""
    origin = connection.headers.get("origin")
    if origin is None:
        return True
    parts = urlsplit(origin)
    return (parts.scheme in ("http", "https")
            and parts.netloc.lower() == connection.headers.get("host", "").strip().lower())


def role_of(connection: HTTPConnection) -> str:
    """``owner`` for the computer itself, ``viewer`` for every other device."""
    client = connection.client
    if client is None or not is_loopback(client.host):
        return VIEWER
    # Behind a reverse proxy every request looks local; then nobody is the owner.
    if any(header in connection.headers for header in _FORWARDING_HEADERS):
        return VIEWER
    return OWNER
