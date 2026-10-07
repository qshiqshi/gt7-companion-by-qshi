"""Who may do what.

Watching the dashboard is open to everyone in the home network. Changing
anything (layouts, settings) is possible right away on the computer the
program runs on; another device has to be paired once with the PIN that this
computer shows. Secrets (the API key) can only be set on the computer itself.

Two more rules keep web pages from the internet out, even though the program
only listens inside the home network:

* the ``Host`` of a request must be a local address or a local name, so a
  foreign domain that merely *resolves* to this computer is refused, and
* a page that was loaded from somewhere else may neither write nor open the
  live connection (``Origin`` must match ``Host``).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

OWNER = "owner"        # the computer the program runs on: may change everything
EDITOR = "editor"      # another device that was paired with the PIN: may edit layouts and settings
VIEWER = "viewer"      # any other device: may watch

COOKIE = "gt7c_pair"   # carries the token of a paired device

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


def role_of(connection: HTTPConnection, pairing: "Pairing | None" = None) -> str:
    """``owner`` for the computer itself, ``editor`` for a paired device, else ``viewer``."""
    client = connection.client
    # Behind a reverse proxy every request looks local; then nobody is the owner.
    proxied = any(header in connection.headers for header in _FORWARDING_HEADERS)
    if client is not None and is_loopback(client.host) and not proxied:
        return OWNER
    if pairing is not None and pairing.knows(connection.cookies.get(COOKIE)):
        return EDITOR
    return VIEWER


def may_edit(role: str) -> bool:
    return role in (OWNER, EDITOR)


class TooManyAttempts(Exception):
    """This device has to wait before it may try a PIN again."""


class Pairing:
    """The PIN shown on this computer and the devices that entered it.

    A device that enters the PIN gets a random token (as a cookie); only its
    hash is kept, and only in memory: after a restart devices pair again with
    the new PIN. Wrong PINs are counted per device and overall, so six digits
    cannot be guessed by trying.
    """

    DIGITS = 6
    WINDOW_S = 300.0           # wrong tries are remembered this long
    PER_DEVICE = 5             # wrong tries per device in that time
    OVERALL = 30               # wrong tries of all devices before the PIN is replaced
    MAX_DEVICES = 20

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._tokens: dict[str, float] = {}            # sha256(token) -> paired at
        self._misses: dict[str, list[float]] = {}      # device address -> times of wrong tries
        self._missed_overall = 0
        self.pin = self._new_pin()

    def _new_pin(self) -> str:
        self._missed_overall = 0
        return f"{secrets.randbelow(10 ** self.DIGITS):0{self.DIGITS}d}"

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()

    def knows(self, token: str | None) -> bool:
        return bool(token) and self._hash(token) in self._tokens

    def enter(self, pin: object, device: str) -> str | None:
        """Try a PIN for the device at this address. Returns the token for the
        device, ``None`` for a wrong PIN; raises :class:`TooManyAttempts`."""
        now = self._clock()
        misses = [t for t in self._misses.get(device, []) if now - t < self.WINDOW_S]
        if len(misses) >= self.PER_DEVICE:
            self._misses[device] = misses
            raise TooManyAttempts
        if isinstance(pin, str) and hmac.compare_digest(pin.strip().encode(), self.pin.encode()):
            self._misses.pop(device, None)
            token = secrets.token_urlsafe(32)
            if len(self._tokens) >= self.MAX_DEVICES:
                self._tokens.pop(min(self._tokens, key=self._tokens.get))
            self._tokens[self._hash(token)] = now
            return token
        misses.append(now)
        self._misses[device] = misses
        if len(self._misses) > 500:                    # forget devices that stopped trying
            self._misses = {d: ts for d, ts in self._misses.items() if ts and now - ts[-1] < self.WINDOW_S}
        self._missed_overall += 1
        if self._missed_overall >= self.OVERALL:
            self.pin = self._new_pin()                 # somebody is guessing: the old PIN is void
        return None

    def forget(self, token: str | None) -> None:
        if token:
            self._tokens.pop(self._hash(token), None)

    def reset(self) -> str:
        """New PIN, and every paired device has to pair again."""
        self._tokens.clear()
        self._misses.clear()
        self.pin = self._new_pin()
        return self.pin

    @property
    def devices(self) -> int:
        return len(self._tokens)
