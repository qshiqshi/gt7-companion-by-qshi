"""GT7-Telemetrie: UDP-Empfaenger (PS5) und Replay-Modus.

Realer Modus: asyncio DatagramProtocol auf Port 33740, Salsa20-Entschluesselung,
Heartbeat an die PS5 (Standard b'C', siehe ``telemetry.packet``), Watchdog bei
Verbindungsverlust. Ist keine Adresse bekannt, wird die PS5 im Heimnetz gesucht.

Paketformate (Heartbeat-Byte -> Groesse): A 296, B 316, C 368 Byte. Jedes ist
eine Obermenge des vorigen; geparst wird nach der Laenge des Datagramms, also
immer das, was die PS5 tatsaechlich schickt. Quellen fuer Lage und IV-Konstante:
MacManley/gt7-udp, ThrottleGeist/gt7-telemetry-relay, jbhoorasingh/gt7-datalogger,
zetetos/gt-telemetry, Nenkai/PDTools.

Replay-Modus: spielt einen Mitschnitt (``.gt7r``: je Record 8 Byte Timestamp
double + 296 Byte Frame; Zusatzbytes eines C-Pakets daneben in ``.gt7x``) mit
Original-Timing auf den Bus — die Demo und die Tests laufen so ohne PS5.

Abgeleitet aus dem privaten GT7 Companion von qshi (siehe PROVENANCE.md):
ohne Mitschnitt, ohne Simulator, PS5-Adresse per Rueckruf statt Konfigdatei.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import pathlib
import struct
import time

from Crypto.Cipher import Salsa20

from .bus import EventBus
from .models import TelemetryFrame
from .netinfo import sweep_targets

log = logging.getLogger("telemetry")

# ── Salsa20-Konstanten ──────────────────────────────────────────
_KEY = b'Simulator Interface Packet GT7 ver 0.0'[:32]
_IV_XOR = 0xDEADBEAF          # Paket A
_IV_XOR_EXT = 0xDEADBEEF      # Paket B und C
_IV_XOR_TILDE = 0x55FABB4F    # Paket "~" (wird nicht angefordert, nur erkannt)
_MAGIC = 0x47375330       # b'G7S0' little-endian
_MIN_PACKET = 296          # Packet-A-Mindestgroesse
_PACKET_SIZES = {"A": 296, "B": 316, "C": 368}
_PACKET_BY_SIZE = {296: "A", 316: "B", 344: "~", 368: "C"}
_IV_XOR_BY_SIZE = {296: _IV_XOR, 316: _IV_XOR_EXT, 344: _IV_XOR_TILDE, 368: _IV_XOR_EXT}
_EXT_SIZE = _PACKET_SIZES["C"] - _MIN_PACKET   # 72 Zusatzbytes (B + "~" + C)

# ── Netzwerk ────────────────────────────────────────────────────
_RECV_PORT = 33740
_SEND_PORT = 33739
_FALLBACK_AFTER_S = 60.0   # Stille, nach der einmal je Minute Paket A probiert wird
_LAPSE_S = 20.0            # erste Sendepause, damit der Datenstrom der PS5 abreisst
_LAPSE_MAX_S = 80.0        # Obergrenze, wenn die Pause wiederholt und verdoppelt wird
_UNREADABLE_RUN = 120      # so viele unlesbare Pakete in Folge (~2 s) loesen den Rueckfall aus

# ── Replay-Mitschnitte ──────────────────────────────────────────
_RECORD_SIZE = 8 + _MIN_PACKET      # double Timestamp + Frame
_EXT_RECORD_SIZE = 8 + _EXT_SIZE    # derselbe Timestamp + Zusatzbytes (.gt7x)
_EXT_SUFFIX = ".gt7x"


# ================================================================
#  Factory
# ================================================================

def create_receiver(cfg: dict, bus: EventBus, *, on_ip=None):
    """UDP-Empfaenger fuer die echte PS5 (``async start()`` / ``async stop()``).

    ``cfg``: ``{"ps5_ip": str, "telemetry": {"packet": "A"|"B"|"C"}}``; eine
    leere Adresse heisst: im Heimnetz suchen. ``on_ip(ip)`` wird gerufen, sobald
    die PS5 unter einer (neuen) Adresse antwortet."""
    return _RealReceiver(cfg, bus, on_ip=on_ip)


def create_replay_receiver(bus: EventBus, file: pathlib.Path, *, speed: float = 1.0,
                           loop: bool = False, transform=None, on_done=None):
    """Replay-Empfaenger fuer einen ``.gt7r``-Mitschnitt (Demo, Tests).
    ``on_done`` (async callable) wird nach natuerlichem Dateiende gerufen."""
    return _ReplayReceiver(bus, file, speed=speed, loop=loop,
                           transform=transform, on_done=on_done)


def read_extension(recording: pathlib.Path) -> dict[bytes, bytes]:
    """Zusatzbytes zu einem Mitschnitt: {8 Byte Timestamp: 72 Byte ab 0x128}.

    Leer, wenn die Fahrt mit Paket A aufgezeichnet wurde oder die Nebendatei
    fehlt. Schluessel sind die unveraenderten Timestamp-Bytes des Archivrecords."""
    path = pathlib.Path(recording).with_suffix(_EXT_SUFFIX)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("Zusatzdaten nicht lesbar: %s", path.name, exc_info=True)
        return {}
    return {raw[off: off + 8]: raw[off + 8: off + _EXT_RECORD_SIZE]
            for off in range(0, len(raw) - _EXT_RECORD_SIZE + 1, _EXT_RECORD_SIZE)}


# ================================================================
#  Entschluesselung & Parsing
# ================================================================

def _decrypt(data: bytes) -> bytes | None:
    """Salsa20-Entschluesselung eines GT7-Rohdatagramms (Paket A, B, "~" oder C).

    Die IV-Konstante haengt vom Paketformat ab und wird aus der Laenge
    gewaehlt; passt sie nicht, werden die uebrigen probiert. Gibt die
    entschluesselten Bytes zurueck oder ``None`` bei ungueltigem Magic-Wert
    (kein GT7-Paket oder falscher Schluessel/IV).
    """
    if len(data) < _MIN_PACKET:
        return None
    iv1 = struct.unpack_from('<I', data, 0x40)[0]
    first = _IV_XOR_BY_SIZE.get(len(data), _IV_XOR)
    for xor in (first, *(x for x in (_IV_XOR, _IV_XOR_EXT, _IV_XOR_TILDE) if x != first)):
        nonce = (iv1 ^ xor).to_bytes(4, 'little') + iv1.to_bytes(4, 'little')
        dec = Salsa20.new(key=_KEY, nonce=nonce).decrypt(data)
        if struct.unpack_from('<I', dec, 0x00)[0] == _MAGIC:
            return dec
    return None


def _encrypt(plain: bytes, seed: int = 0x12345678) -> bytes:
    """Gegenstueck zu ``_decrypt`` fuer Tests und Werkzeuge: verschluesselt ein
    Klartextpaket so, wie die PS5 es senden wuerde (Seed unverschluesselt an 0x40)."""
    xor = _IV_XOR_BY_SIZE.get(len(plain), _IV_XOR)
    nonce = (seed ^ xor).to_bytes(4, 'little') + seed.to_bytes(4, 'little')
    out = bytearray(Salsa20.new(key=_KEY, nonce=nonce).encrypt(bytes(plain)))
    out[0x40:0x44] = seed.to_bytes(4, 'little')
    return bytes(out)


def _clean_ascii(raw: bytes) -> str:
    """Bytes eines Textfelds bis zum ersten NUL, nur druckbares ASCII."""
    text = bytes(raw).split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return "".join(ch for ch in text if " " < ch < "\x7f")


def _parse_extension(d: bytes) -> dict:
    """Zusatzfelder der Pakete B (ab 0x128) und C (ab 0x158); leer bei Paket A."""
    size = len(d)
    out: dict = {"packet_type": _PACKET_BY_SIZE.get(size, "A" if size < 316 else "?")}
    if size >= _PACKET_SIZES["B"]:
        steer = struct.unpack_from('<f', d, 0x128)[0]
        out["steering_wheel_rad"] = steer if math.isfinite(steer) else None
    if size >= _PACKET_SIZES["C"]:
        surface = bytes(d[0x158:0x15C]).decode("ascii", errors="replace")
        out["surface"] = surface if surface.strip("\x00 ") else None
        out["game_lap_ms"] = struct.unpack_from('<i', d, 0x15C)[0]
        left, right = struct.unpack_from('<2f', d, 0x160)
        out["wheel_steer_rad"] = ((left, right) if math.isfinite(left)
                                  and math.isfinite(right) else None)
        wheelbase = struct.unpack_from('<f', d, 0x168)[0]
        out["wheelbase_m"] = wheelbase if math.isfinite(wheelbase) and wheelbase > 0 else None
        out["car_class"] = _clean_ascii(d[0x16C:0x170]) or None
    return out


def _safe_extension(d: bytes) -> dict:
    """Zusatzfelder lesen; ein Fehler dort laesst das Grundpaket unberuehrt."""
    try:
        return _parse_extension(d)
    except Exception:
        log.debug("Zusatzfelder nicht lesbar (%d Byte)", len(d), exc_info=True)
        return {}


def _parse(d: bytes) -> TelemetryFrame:
    """Entschluesseltes Paket (A 296, B 316 oder C 368 Bytes) in ein
    ``TelemetryFrame`` wandeln. Die ersten 296 Bytes sind in allen Formaten
    gleich; Zusatzfelder bleiben ``None``, wenn das Paket sie nicht enthaelt.

    Byte-Offsets gemaess Community-Referenz (MacManley, Nenkai, Bornhall).
    """
    flags = struct.unpack_from('<H', d, 0x8E)[0]
    gb = d[0x90]
    cur_gear = gb & 0x0F          # low nibble: aktueller Gang
    sug_gear = (gb >> 4) & 0x0F   # high nibble: vorgeschlagener Gang

    return TelemetryFrame(
        packet_id=struct.unpack_from('<i', d, 0x70)[0],
        car_id=struct.unpack_from('<i', d, 0x124)[0],
        # Position
        pos_x=struct.unpack_from('<f', d, 0x04)[0],
        pos_y=struct.unpack_from('<f', d, 0x08)[0],
        pos_z=struct.unpack_from('<f', d, 0x0C)[0],
        # Geschwindigkeit (Weltkoordinaten)
        vel_x=struct.unpack_from('<f', d, 0x10)[0],
        vel_y=struct.unpack_from('<f', d, 0x14)[0],
        vel_z=struct.unpack_from('<f', d, 0x18)[0],
        # Orientierung (normalisiert -1..1)
        rot_pitch=struct.unpack_from('<f', d, 0x1C)[0],
        rot_yaw=struct.unpack_from('<f', d, 0x20)[0],
        rot_roll=struct.unpack_from('<f', d, 0x24)[0],
        orientation_north=struct.unpack_from('<f', d, 0x28)[0],
        # Winkelgeschwindigkeit (rad/s)
        ang_vel_x=struct.unpack_from('<f', d, 0x2C)[0],
        ang_vel_y=struct.unpack_from('<f', d, 0x30)[0],
        ang_vel_z=struct.unpack_from('<f', d, 0x34)[0],
        body_height=struct.unpack_from('<f', d, 0x38)[0],
        # Geschwindigkeit (skalar)
        speed_mps=struct.unpack_from('<f', d, 0x4C)[0],
        # Motor
        rpm=struct.unpack_from('<f', d, 0x3C)[0],
        boost=struct.unpack_from('<f', d, 0x50)[0],
        oil_pressure=struct.unpack_from('<f', d, 0x54)[0],
        oil_temp=struct.unpack_from('<f', d, 0x5C)[0],
        water_temp=struct.unpack_from('<f', d, 0x58)[0],
        # Antrieb (15 = neutral / kein Vorschlag -> -1)
        gear=-1 if cur_gear == 15 else cur_gear,
        suggested_gear=-1 if sug_gear == 15 else sug_gear,
        throttle=d[0x91] / 255.0,
        brake=d[0x92] / 255.0,
        clutch=struct.unpack_from('<f', d, 0xF4)[0],
        clutch_engagement=struct.unpack_from('<f', d, 0xF8)[0],
        clutch_rpm=struct.unpack_from('<f', d, 0xFC)[0],
        transmission_top_speed=struct.unpack_from('<f', d, 0x100)[0],
        gear_ratios=struct.unpack_from('<7f', d, 0x104),
        min_alert_rpm=struct.unpack_from('<H', d, 0x88)[0],
        max_alert_rpm=struct.unpack_from('<H', d, 0x8A)[0],
        # Sprit
        # PDTools-Referenz: 0x44 = FuelLevel (faellt beim Fahren),
        # 0x48 = FuelCapacity (konstant) — NICHT vertauschen!
        fuel_level=struct.unpack_from('<f', d, 0x44)[0],
        fuel_capacity=struct.unpack_from('<f', d, 0x48)[0],
        # Reifen (VL, VR, HL, HR)
        tyre_temp=struct.unpack_from('<4f', d, 0x60),
        wheel_rps=struct.unpack_from('<4f', d, 0xA4),
        tyre_radius=struct.unpack_from('<4f', d, 0xB4),
        susp_height=struct.unpack_from('<4f', d, 0xC4),
        road_plane=struct.unpack_from('<3f', d, 0x94),
        road_plane_distance=struct.unpack_from('<f', d, 0xA0)[0],
        # Runden / Rennen
        current_lap=struct.unpack_from('<h', d, 0x74)[0],
        total_laps=struct.unpack_from('<h', d, 0x76)[0],
        best_lap_ms=struct.unpack_from('<i', d, 0x78)[0],
        last_lap_ms=struct.unpack_from('<i', d, 0x7C)[0],
        day_progression_ms=struct.unpack_from('<i', d, 0x80)[0],
        race_start_position=struct.unpack_from('<h', d, 0x84)[0],
        pre_race_num_cars=struct.unpack_from('<h', d, 0x86)[0],
        calc_max_speed=struct.unpack_from('<h', d, 0x8C)[0],
        # Flags (Bitfeld 0x8E)
        on_track=bool(flags & 0x0001),
        paused=bool(flags & 0x0002),
        loading=bool(flags & 0x0004),
        in_gear=bool(flags & 0x0008),
        has_turbo=bool(flags & 0x0010),
        rev_limiter=bool(flags & 0x0020),
        handbrake=bool(flags & 0x0040),
        asm_active=bool(flags & 0x0400),
        tcs_active=bool(flags & 0x0800),
        **_safe_extension(d),
    )


# ================================================================
#  UDP-Protokoll
# ================================================================

class _GT7Protocol(asyncio.DatagramProtocol):
    """asyncio-DatagramProtocol fuer GT7-Pakete A/B/C (Salsa20)."""

    def __init__(self, bus: EventBus, on_packet: callable,
                 on_undecodable: callable | None = None) -> None:
        self._bus = bus
        self._on_packet = on_packet
        self._on_undecodable = on_undecodable
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        dec = _decrypt(data)
        if dec is None:
            if self._on_undecodable is not None:
                self._on_undecodable(addr, len(data))
            return
        try:
            frame = _parse(dec)
        except Exception:
            log.exception("Fehler beim Parsen eines GT7-Pakets")
            return
        self._on_packet(addr, dec, frame)
        asyncio.get_running_loop().create_task(
            self._bus.publish("telemetry.frame", frame)
        )

    def error_received(self, exc: Exception) -> None:
        # debug statt warning: beim Discovery-Sweep antworten hunderte
        # Adressen mit ICMP-Unreachable — das wuerde das Log fluten
        log.debug("UDP-Socket-Fehler: %s", exc)


# ================================================================
#  Realer UDP-Empfaenger
# ================================================================

class _RealReceiver:
    """Empfaengt echte GT7-Telemetrie ueber UDP (Port 33740) von der PS5.

    Sendet periodisch einen Heartbeat an ``(ps5_ip, 33739)``, damit die
    Konsole weiter Pakete liefert. Das Heartbeat-Byte waehlt das Paketformat
    (``telemetry.packet``, Standard ``C``). Die PS5 bleibt bei dem Format des
    ersten Heartbeats, bis ihr Datenstrom einmal abgerissen ist; kommt ein
    kleineres Format an als angefordert, laeuft alles weiter und nur die
    Zusatzanzeigen bleiben leer.
    """

    def __init__(self, cfg: dict, bus: EventBus, *, on_ip=None) -> None:
        self._bus = bus
        self._cfg = cfg
        # Leer = Adresse unbekannt: die PS5 wird im Heimnetz gesucht.
        self._ps5_ip: str = str(cfg.get("ps5_ip") or "").strip()
        self._on_ip = on_ip                    # callable(ip) | None: neue Adresse merken
        self._port: int = int(cfg.get("telemetry", {}).get("port", _RECV_PORT))
        self._send_port: int = int(cfg.get("telemetry", {}).get("send_port", _SEND_PORT))
        self._transport: asyncio.DatagramTransport | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._last_packet: float = 0.0
        self._connected: bool = False
        # ── Paketformat ──
        wanted = str(cfg.get("telemetry", {}).get("packet", "C")).strip().upper()
        if wanted not in _PACKET_SIZES:
            log.warning("Unbekanntes telemetry.packet %r — verwende C", wanted)
            wanted = "C"
        self._packet: str = wanted
        self._heartbeat: bytes = wanted.encode("ascii")
        self._format: str | None = None       # zuletzt empfangenes Format
        self._last_fallback_probe: float = 0.0
        # Unlesbare Pakete der PS5 (falsches Format/Schluessel): zaehlen und
        # notfalls dauerhaft auf Paket A zurueckgehen.
        self._bad_count: int = 0              # unlesbare Pakete in Folge
        self._bad_last: float = 0.0           # Zeitpunkt des letzten davon
        self._silence_until: float = 0.0
        self._lapse_s: float = _LAPSE_S
        self._fell_back: bool = False

    # ── Lifecycle ──

    async def start(self) -> None:
        """Bindet den UDP-Port. ``OSError`` (Port belegt) geht an den Aufrufer."""
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _GT7Protocol(self._bus, self._on_packet, self._on_undecodable),
            local_addr=("0.0.0.0", self._port),
        )
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        log.info("UDP-Empfaenger gestartet (Port %d, Ziel %s, Paket %s)",
                 self._port, self._ps5_ip or "wird gesucht", self._packet)

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
        for task in (self._heartbeat_task, self._watchdog_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if self._connected:
            self._connected = False
            with contextlib.suppress(Exception):
                await self._bus.publish("telemetry.status", {"connected": False})
        log.info("UDP-Empfaenger gestoppt")

    @property
    def ps5_ip(self) -> str:
        return self._ps5_ip

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def packet_format(self) -> dict:
        """Angefordertes und zuletzt tatsaechlich empfangenes Paketformat."""
        return {"requested": self._packet, "received": self._format,
                "fallback_to_a": self._fell_back}

    # ── Paket-Callback ──

    def _on_packet(self, addr: tuple, dec: bytes, frame: TelemetryFrame) -> None:
        """Wird von ``_GT7Protocol`` bei jedem gueltig entschluesselten Paket
        aufgerufen (synchron, aus ``datagram_received``)."""
        frame.received_at_s = self._last_packet = time.monotonic()
        self._bad_count = 0
        if frame.packet_type != self._format:
            self._note_format(frame.packet_type)
        # Auto-Discovery: Antwortet eine andere IP (z.B. nach DHCP-Wechsel
        # oder Subnetz-Sweep), wird sie ab sofort als PS5-Adresse verwendet
        # und dem Aufrufer gemeldet (der sie in den Einstellungen sichert).
        sender = addr[0]
        if sender != self._ps5_ip:
            log.info("PS5 unter neuer IP entdeckt: %s (vorher %s)", sender,
                     self._ps5_ip or "unbekannt")
            self._ps5_ip = sender
            if self._on_ip is not None:
                try:
                    self._on_ip(sender)
                except Exception:
                    log.exception("Neue PS5-IP konnte nicht gesichert werden")
        if not self._connected:
            self._connected = True
            log.info("PS5-Verbindung hergestellt (%s)", self._ps5_ip)
            asyncio.get_running_loop().create_task(
                self._bus.publish("telemetry.status", {"connected": True})
            )

    def _on_undecodable(self, addr: tuple, size: int) -> None:
        """Paket der PS5 kam an, liess sich aber nicht entschluesseln."""
        if addr[0] != self._ps5_ip:
            return
        now = time.monotonic()
        if now - self._bad_last > 2.0:
            self._bad_count = 0               # alte Folge ist beendet
        self._bad_last = now
        self._bad_count += 1

    def _unreadable_stream(self, now: float) -> bool:
        """Die PS5 sendet gerade laufend Pakete, von denen keines lesbar ist
        (zu kurz oder nicht zu entschluesseln). Jedes gueltige Paket setzt die
        Folge zurueck; eine bereits beendete Folge zaehlt nicht mehr."""
        return self._bad_count >= _UNREADABLE_RUN and now - self._bad_last <= 2.0

    def _note_format(self, received: str) -> None:
        """Formatwechsel einmal protokollieren (nicht je Paket)."""
        self._format = received
        wanted, got = _PACKET_SIZES.get(self._packet, 0), _PACKET_SIZES.get(received, 0)
        if got >= wanted:
            log.info("PS5 sendet Paket %s", received)
            return
        log.warning("PS5 sendet Paket %s statt %s: Untergrund, Lenkwinkel und "
                    "Fahrzeugklasse fehlen, bis der Datenstrom einmal neu "
                    "aufgebaut wurde (Companion beenden, 20 s warten, neu starten).",
                    received, self._packet)
        # Ab jetzt genau das Format anfordern, das die PS5 liefert. Ob sie einen
        # Heartbeat mit anderem Buchstaben als Lebenszeichen wertet, ist nicht
        # belegt; so bleibt der laufende Strom in jedem Fall erhalten.
        if received in _PACKET_SIZES and self._heartbeat != received.encode("ascii"):
            self._heartbeat = received.encode("ascii")
            self._fell_back = received == "A"

    # ── Hintergrund-Tasks ──

    async def _heartbeat_loop(self) -> None:
        """Sendet das Heartbeat-Byte des gewuenschten Paketformats jede Sekunde.

        Wird seit >5s kein Paket empfangen, wird ein zusaetzlicher Heartbeat
        gesendet. Bei laengerer Stille (>10s, oder nie verbunden) laeuft alle
        15s ein Subnetz-Sweep: Heartbeat an alle Adressen der eigenen Heimnetze
        — antwortet die PS5 unter neuer IP, uebernimmt ``_on_packet`` sie.
        Ist noch gar keine Adresse bekannt, wird sofort und dann alle 5s gesucht.

        Sicherheitsnetz: Bleibt die PS5 eine volle Minute stumm, geht einmal
        pro Minute statt des gewuenschten Bytes ein ``b'A'`` hinaus. Eine
        Konsole oder ein Spielmodus, der das erweiterte Format nicht bedient,
        liefert dann wenigstens Paket A (ohne Zusatzanzeigen).
        """
        started = time.monotonic()
        last_sweep = 0.0
        while True:
            try:
                now = time.monotonic()
                if now >= self._silence_until and self._unreadable_stream(now):
                    # Es kommen Pakete an, aber keines ist lesbar: nicht mehr
                    # senden, bis der Strom abreisst, danach Paket A anfordern.
                    # Laeuft der unlesbare Strom nach der Pause weiter, war sie
                    # zu kurz: naechste Pause doppelt so lang.
                    if self._fell_back and self._heartbeat == b"A" and self._silence_until > 0:
                        self._lapse_s = min(self._lapse_s * 2.0, _LAPSE_MAX_S)
                    log.error("PS5 sendet Pakete, die sich nicht lesen lassen (angefordert %s). "
                              "Sendepause %.0f s, danach Paket A; Untergrund, Lenkwinkel und "
                              "Klasse entfallen.", self._packet, self._lapse_s)
                    self._heartbeat, self._fell_back = b"A", True
                    self._bad_count = 0
                    self._silence_until = now + self._lapse_s
                if now < self._silence_until:
                    await asyncio.sleep(1.0)
                    continue
                silent = (now - self._last_packet) if self._last_packet > 0 else (now - started)
                beat = self._heartbeat
                if (beat != b"A" and silent > _FALLBACK_AFTER_S
                        and now - self._last_fallback_probe > _FALLBACK_AFTER_S):
                    self._last_fallback_probe = now
                    beat = b"A"
                    log.info("PS5 seit %.0f s stumm: Probe mit Paket A", silent)
                if self._ps5_ip:
                    self._transport.sendto(beat, (self._ps5_ip, self._send_port))
                    if self._last_packet > 0 and now - self._last_packet > 5.0:
                        self._transport.sendto(beat, (self._ps5_ip, self._send_port))
                sweep_every = 15.0 if self._ps5_ip else 5.0
                if (silent > 10.0 or not self._ps5_ip) and now - last_sweep > sweep_every:
                    last_sweep = now
                    self._sweep_subnet()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Heartbeat-Fehler: %s", exc)
            await asyncio.sleep(1.0)

    def _sweep_subnet(self) -> None:
        """Schickt einen Heartbeat an alle Hosts der eigenen Heimnetze (je /24)."""
        targets = sweep_targets()
        if not targets:
            return
        log.debug("PS5-Discovery: Sweep ueber %d Adressen", len(targets))
        for host in targets:
            with contextlib.suppress(Exception):
                self._transport.sendto(self._heartbeat, (host, self._send_port))

    async def _watchdog_loop(self) -> None:
        """Publiziert ``telemetry.status connected=False`` wenn >5s lang kein
        Paket empfangen wird. Bei Wiederempfang publiziert ``_on_packet``
        automatisch ``connected=True``."""
        while True:
            await asyncio.sleep(1.0)
            if self._connected and self._last_packet > 0:
                if time.monotonic() - self._last_packet > 5.0:
                    self._connected = False
                    log.warning("PS5-Verbindung verloren (>5s ohne Paket)")
                    await self._bus.publish("telemetry.status", {"connected": False})


# ================================================================
#  Replay-Empfaenger
# ================================================================

class _ReplayReceiver:
    """Spielt einen ``.gt7r``-Mitschnitt mit Original-Timing wieder ab.

    Timestamp-Luecken (Pause/Menue beim Aufzeichnen) werden auf 0,5s gekappt.
    Mit ``loop=True`` beginnt die Datei nach dem Ende von vorn (Demo-Betrieb);
    ``transform(frame, durchlauf)`` darf jeden Frame vor dem Versand anpassen.
    Ohne Schleife wird nach dem Dateiende ``on_done`` gerufen.
    """

    def __init__(self, bus: EventBus, file: pathlib.Path, *, speed: float = 1.0,
                 loop: bool = False, transform=None, on_done=None) -> None:
        self._bus = bus
        self._file = pathlib.Path(file)
        self._speed = max(0.1, min(10.0, float(speed)))
        self._loop = bool(loop)
        self._transform = transform
        self._on_done = on_done
        self._task: asyncio.Task | None = None
        self._running = False
        self.passes = 0                        # vollstaendige Durchlaeufe

    @property
    def replay_file(self) -> str:
        return self._file.name

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("Replay gestartet: %s (Tempo %.1fx%s)",
                 self._file.name, self._speed, ", Schleife" if self._loop else "")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        log.info("Replay gestoppt")

    async def _run(self) -> None:
        try:
            raw = await asyncio.to_thread(self._file.read_bytes)
        except Exception:
            log.exception("Replay-Datei nicht lesbar: %s", self._file)
            raw = b""

        n = len(raw) // _RECORD_SIZE
        if n < 2:
            log.warning("Replay-Datei leer/zu kurz: %s", self._file.name)
            if self._on_done is not None:
                await self._on_done()
            return
        extension = await asyncio.to_thread(read_extension, self._file)

        await self._bus.publish("telemetry.status", {"connected": True})
        try:
            while self._running:
                prev_ts: float | None = None
                for i in range(n):
                    if not self._running:
                        return
                    off = i * _RECORD_SIZE
                    ts = struct.unpack_from("<d", raw, off)[0]
                    dec = raw[off + 8: off + _RECORD_SIZE]
                    extra = extension.get(raw[off: off + 8]) if extension else None
                    if extra is not None:
                        dec = dec + extra
                    try:
                        frame = _parse(dec)
                        if self._transform is not None:
                            frame = self._transform(frame, self.passes) or frame
                    except Exception:
                        continue
                    await self._bus.publish("telemetry.frame", frame)
                    if prev_ts is not None:
                        dt = min(max((ts - prev_ts), 0.0), 0.5) / self._speed
                        await asyncio.sleep(dt)
                    else:
                        await asyncio.sleep(0)
                    prev_ts = ts
                self.passes += 1
                if not self._loop:
                    break
            log.info("Replay beendet: %s (%d Frames)", self._file.name, n)
        finally:
            with contextlib.suppress(Exception):
                await self._bus.publish("telemetry.status", {"connected": False})
        if self._on_done is not None:
            await self._on_done()
