"""Event-Erkennung aus Telemetrie-Frames.

Alle Detektoren arbeiten O(1) pro Frame und sind durch ``frame.is_driving``
plus eine konfigurierbare Warmup-Phase gegated, um Artefakte aus Menues,
Replays und Pit-Teleports zu unterdruecken.

Erkannte Events (publiziert auf dem Bus):
  - event.lap_done, event.best_lap, event.race_start, event.final_lap, event.race_end
  - event.spin, event.crash, event.offtrack
  - event.fuel_low, event.fuel_critical
  - event.tyre_hot

Abgeleitet aus dem privaten GT7 Companion von qshi (siehe PROVENANCE.md):
Schwellenwerte stehen hier statt in einer Konfigdatei, Hinweise sind Codes
statt deutscher Saetze (die Texte dazu waehlt, wer sie ausgibt).
"""
from __future__ import annotations

import logging
import math
import time

from .bus import EventBus
from .models import TelemetryFrame

log = logging.getLogger("detectors")

# Positionen der vier Reifen (Index in tyre_temp / wheel_rps / tyre_radius)
_TYRE_POS = ("FL", "FR", "RL", "RR")

# Schwellenwerte; einzelne lassen sich beim Erzeugen ueberschreiben.
DEFAULTS: dict = {
    "spin_min_speed_mps": 8.0,
    "spin_aoa_trigger_deg": 35.0,
    "spin_sustain_frames": 12,
    "spin_cooldown_frames": 180,
    "crash_minor_dv": 1.5,
    "crash_major_dv": 3.5,
    "crash_severe_dv": 7.0,
    "crash_min_speed_mps": 5.0,
    "crash_cooldown_frames": 60,
    "offtrack_slip_ratio": 0.35,
    "offtrack_sustain_frames": 10,
    "offtrack_cooldown_frames": 240,
    "fuel_low_laps": 3,
    "fuel_critical_laps": 1,
    "pit_call_laps": 2,
    "tyre_hot_temp": 95.0,
    "warmup_frames": 30,
}

# Interne Schwelle fuer Gierrate, ab der ein Frame als potentieller
# Dreher-Frame zaehlt.  Nicht in der Config, da eng mit der Physik-Logik
# verknuepft.
_YAW_RATE_THRESHOLD = 1.0   # rad/s (~57 deg/s)

# Mindest-Cooldown fuer Reifen-Events (Sekunden, pro Ecke).
_TYRE_SELF_COOLDOWN_S = 30.0


class DetectorSuite:
    """Buendelt alle Event-Detektoren und abonniert ``telemetry.frame``.

    Kein ``start()``/``stop()`` noetig, da ausschliesslich Frame-getrieben.
    """

    def __init__(self, bus: EventBus, overrides: dict | None = None) -> None:
        self._bus = bus
        d = {**DEFAULTS, **(overrides or {})}

        # ── Schwellenwerte aus Config ──
        self._warmup_max         = d["warmup_frames"]

        self._spin_min_speed     = d["spin_min_speed_mps"]
        self._spin_angle_deg     = d["spin_aoa_trigger_deg"]
        self._spin_sustain       = d["spin_sustain_frames"]
        self._spin_cd_max        = d["spin_cooldown_frames"]

        self._crash_dv_minor     = d["crash_minor_dv"]
        self._crash_dv_major     = d["crash_major_dv"]
        self._crash_dv_severe    = d["crash_severe_dv"]
        self._crash_min_speed    = d["crash_min_speed_mps"]
        self._crash_cd_max       = d["crash_cooldown_frames"]

        self._offtrack_slip      = d["offtrack_slip_ratio"]
        self._offtrack_sustain   = d["offtrack_sustain_frames"]
        self._offtrack_cd_max    = d["offtrack_cooldown_frames"]

        self._fuel_low_laps      = d["fuel_low_laps"]
        self._fuel_crit_laps     = d["fuel_critical_laps"]
        self._pit_call_laps      = d.get("pit_call_laps", 2)

        self._tyre_hot_temp      = d["tyre_hot_temp"]

        self.reset()
        bus.subscribe("telemetry.frame", self._on_frame)
        log.info("DetectorSuite initialisiert (%d Warmup-Frames)", self._warmup_max)

    def reset(self) -> None:
        """Alles Gemerkte vergessen (neue Quelle, neue Sitzung)."""
        # ── Warmup / Gate ──
        self._warmup_counter = 0
        self._prev_driving   = False
        self._prev_speed     = 0.0
        self._prev_frame: TelemetryFrame | None = None
        self._pit_candidate: tuple[TelemetryFrame, float] | None = None
        self._pit_confirm_frames = 0
        self._pit_exit_frames = 0

        # ── Spin ──
        self._spin_frames       = 0
        self._spin_cd           = 0
        self._spin_accum_deg    = 0.0
        self._spin_entry_speed  = 0.0

        # ── Crash ──
        self._crash_cd = 0

        # ── Offtrack ──
        self._offtrack_frames      = 0
        self._offtrack_cd          = 0
        self._offtrack_entry_speed = 0.0

        # ── Runden ──
        self._prev_lap       = 0
        self._session_best   = -1   # eigener Session-Bestwert (ms)
        self._laps_completed = 0

        # ── Sprit ──
        self._fuel_at_lap_start = -1.0
        self._fuel_history: list[float] = []   # letzte 3 Verbraeuche
        self._fuel_low_fired  = False
        self._fuel_crit_fired = False
        self._pit_call_fired  = False
        self._pit_entry_fired  = False
        self._stint_lap_times: list[int] = []
        self._drift_frames    = 0
        self._drift_cooldown  = 0
        self._drift_peak_kmh  = 0.0

        # ── Reifen (Monotonic-Zeitstempel pro Ecke) ──
        self._tyre_last: dict[str, float] = {p: 0.0 for p in _TYRE_POS}

    # ================================================================
    #  Haupt-Handler
    # ================================================================

    async def _on_frame(self, frame: TelemetryFrame) -> None:
        driving = frame.is_driving
        prev = self._prev_frame
        self._prev_frame = frame
        discontinuity = (prev is not None and (
            frame.current_lap < prev.current_lap
            or frame.car_id != prev.car_id
            or (frame.packet_id > 0 and prev.packet_id > 0
                and not 0 < frame.packet_id - prev.packet_id <= 15)))
        if discontinuity or frame.loading or frame.current_lap < 0:
            self._prev_driving = False
            self._pit_entry_fired = False
            self._pit_candidate = None
            self._pit_confirm_frames = self._pit_exit_frames = 0

        # Warmup bei Wechsel nicht-fahrend -> fahrend
        if driving and not self._prev_driving:
            self._warmup_counter = 0
            # Physik-Zustand zuruecksetzen, um Sprung-Artefakte zu vermeiden
            self._prev_speed = frame.speed_mps
            self._spin_frames = 0
            self._spin_accum_deg = 0.0
            self._offtrack_frames = 0
        self._prev_driving = driving

        # Rundenlogik laeuft immer (Spielzustand, nicht Physik)
        await self._check_laps(frame)

        if not driving:
            self._prev_speed = frame.speed_mps
            return

        # Boxen-Uebernahme vor der Physik pruefen: GT7 friert das Fahrzeug
        # beim Eintritt in die Boxensequenz ein (auch bei on_track=True).
        await self._check_pit_entry(frame, prev if not discontinuity else None)
        frame.in_pit = self._pit_entry_fired or self._pit_candidate is not None
        if frame.in_pit:
            self._spin_frames = self._spin_accum_deg = 0
            self._offtrack_frames = self._drift_frames = 0
            self._warmup_counter = 0
            self._prev_speed = frame.speed_mps
            return

        if self._warmup_counter < self._warmup_max:
            self._warmup_counter += 1
            self._prev_speed = frame.speed_mps
            return

        # Physik-basierte Detektoren (O(1) pro Frame)
        await self._check_spin(frame)
        await self._check_crash(frame)
        await self._check_offtrack(frame)
        await self._check_tyres(frame)
        await self._check_drift(frame)

        self._prev_speed = frame.speed_mps

    # ================================================================
    #  Drift (kontrollierter Slide — unterhalb der Dreher-Schwelle)
    # ================================================================

    async def _check_drift(self, frame: TelemetryFrame) -> None:
        """Drift = anhaltende Gierrate MIT Gas bei Tempo, ohne dass es ein
        Dreher wird. Feuert am DRIFT-ENDE (damit die Ansage nicht mitten
        im Slide kommt), fruehestens nach ~0,75 s Querfahrt."""
        yaw = abs(frame.ang_vel_y)
        if self._drift_cooldown > 0:
            self._drift_cooldown -= 1
        if yaw >= 1.1:
            # Das kippt Richtung Dreher — zaehlt nicht als Drift
            self._drift_frames = 0
            return
        drifting = (frame.speed_kmh > 60.0 and frame.throttle > 0.35
                    and yaw > 0.35)
        if drifting:
            self._drift_frames += 1
            self._drift_peak_kmh = max(self._drift_peak_kmh, frame.speed_kmh)
        else:
            if self._drift_frames >= 45 and self._drift_cooldown == 0:
                await self._bus.publish("event.drift", {
                    "duration_s": round(self._drift_frames / 60.0, 1),
                    "speed_kmh": round(self._drift_peak_kmh),
                })
                self._drift_cooldown = 60 * 15  # 15 s Ruhe
                log.info("Drift erkannt (%.1f s)", self._drift_frames / 60.0)
            self._drift_frames = 0
            self._drift_peak_kmh = 0.0

    # ================================================================
    #  Boxeneinfahrt
    # ================================================================

    async def _check_pit_entry(self, frame: TelemetryFrame,
                               prev: TelemetryFrame | None = None) -> None:
        """Boxensequenz aus Stillsetzen + entkoppeltem Antrieb erkennen.

        Packet A enthaelt kein Boxenflag. Acht bestaetigte Frames (~133 ms)
        unterscheiden die eingefrorene Boxenkamera von einem Einschlag.
        Ein verworfener Kandidat wird nachtraeglich als Crash geprueft.
        """
        if (frame.current_lap < 1
                or (frame.total_laps > 0 and frame.current_lap > frame.total_laps)):
            self._pit_entry_fired = False
            self._pit_candidate = None
            return
        if self._pit_entry_fired:
            manual = frame.speed_mps > 8 and (frame.throttle > 0.2 or frame.brake > 0.2)
            self._pit_exit_frames = self._pit_exit_frames + 1 if manual else 0
            if self._pit_exit_frames >= 12:
                self._pit_entry_fired = False
                self._pit_exit_frames = 0
                await self._bus.publish("event.pit_exit", {})
            return

        frozen = (frame.speed_mps < 0.05 and not frame.in_gear
                  and frame.throttle < 0.01 and frame.brake < 0.01
                  and not frame.handbrake
                  and all(abs(w) < 0.05 for w in frame.wheel_rps))
        if (self._pit_candidate is None and frozen and prev is not None
                and prev.is_driving and prev.speed_kmh > 50
                and prev.current_lap == frame.current_lap
                and math.hypot(frame.pos_x - prev.pos_x, frame.pos_z - prev.pos_z) < 3):
            self._pit_candidate = (frame, prev.speed_mps)
            self._pit_confirm_frames = 0
        if self._pit_candidate is None:
            return
        entry, entry_speed = self._pit_candidate
        stationary = math.hypot(frame.pos_x - entry.pos_x, frame.pos_z - entry.pos_z) < 0.1
        if frozen and stationary:
            self._pit_confirm_frames += 1
            if self._pit_confirm_frames >= 8:
                self._pit_entry_fired = True
                self._pit_candidate = None
                advice = self._pit_advice(frame)
                await self._bus.publish("event.pit_entry", advice)
                log.info("Boxeneinfahrt erkannt: %s", advice)
        else:
            self._pit_candidate = None
            saved_speed = self._prev_speed
            self._prev_speed = entry_speed
            await self._check_crash(entry)
            self._prev_speed = saved_speed

    def _pit_advice(self, frame: TelemetryFrame) -> dict:
        """Tank- und Reifenempfehlung aus Verbrauch und Stint-Zeiten."""
        advice: dict = {"laps_remaining": None, "fuel_target_l": None,
                        "fuel_add_l": None, "tyre_hint": None}
        remaining = (frame.total_laps - frame.current_lap + 1
                     if frame.total_laps > 0 else None)
        advice["laps_remaining"] = remaining
        if self._fuel_history and frame.fuel_capacity > 0 and remaining:
            avg = sum(self._fuel_history) / len(self._fuel_history)
            target = min(frame.fuel_capacity, (remaining + 0.7) * avg)
            advice["fuel_target_l"] = round(target)
            advice["fuel_add_l"] = max(0, round(target - frame.fuel_level))
        # Reifen: Rundenzeit-Abfall im Stint als Verschleiss-Indikator
        stint = self._stint_lap_times
        if len(stint) >= 6:
            early = sum(stint[:3]) / 3
            late = sum(stint[-3:]) / 3
            if late - early > early * 0.012:
                advice["tyre_hint"] = "fresh"        # Zeiten fallen spuerbar ab
            else:
                advice["tyre_hint"] = "keep"         # Zeiten sind stabil
        else:
            advice["tyre_hint"] = "unknown"          # zu wenig Stint-Daten
        return advice

    # ================================================================
    #  Runden / Rennen
    # ================================================================

    async def _check_laps(self, frame: TelemetryFrame) -> None:
        new = frame.current_lap
        old = self._prev_lap

        if new == old:
            return

        # ── Rennstart: 0 -> 1 bei mehrrundigen Rennen ──
        if old == 0 and new == 1 and frame.total_laps > 0:
            await self._bus.publish("event.race_start", {})
            self._fuel_at_lap_start = frame.fuel_level
            self._fuel_low_fired = False
            self._fuel_crit_fired = False
            self._pit_call_fired = False
            self._pit_entry_fired = False
            self._stint_lap_times.clear()
            self._fuel_history.clear()
            self._laps_completed = 0
            self._session_best = -1
            log.info("Rennstart erkannt (Runde 1 von %d)", frame.total_laps)

        # ── Runde abgeschlossen ──
        if new == old + 1 and old >= 1:
            lap_number = old
            last_ms = frame.last_lap_ms
            best_ms = frame.best_lap_ms

            diff_ms: int | None = None
            if self._session_best > 0:
                diff_ms = last_ms - self._session_best

            await self._bus.publish("event.lap_done", {
                "last_ms": last_ms,
                "best_ms": best_ms,
                "diff_ms": diff_ms,
                "lap_number": lap_number,
            })
            self._laps_completed += 1

            # Bestwert: erste Runde = Baseline (kein Event)
            if last_ms > 0:
                if self._session_best > 0 and last_ms < self._session_best:
                    await self._bus.publish("event.best_lap", {
                        "lap_time_ms": last_ms,
                        "lap_number": lap_number,
                    })
                    log.info("Neuer Session-Bestwert: %d ms (Runde %d)",
                             last_ms, lap_number)
                # Bestwert aktualisieren
                if self._session_best < 0 or last_ms < self._session_best:
                    self._session_best = last_ms

            # Spritverbrauch bei Rundenende pruefen
            await self._check_fuel(frame)

        # ── Letzte Runde ──
        if (new == frame.total_laps > 0
                and new == old + 1):
            await self._bus.publish("event.final_lap", {})
            log.info("Letzte Runde (Runde %d von %d)", new, frame.total_laps)

        # ── Rennende: current_lap faellt auf 0 ──
        if new == 0 and old > 0 and self._laps_completed > 0:
            await self._bus.publish("event.race_end", {})
            log.info("Rennen beendet (%d Runden gefahren)", self._laps_completed)

        self._prev_lap = new

    # ================================================================
    #  Sprit
    # ================================================================

    async def _check_fuel(self, frame: TelemetryFrame) -> None:
        """Wird bei jedem ``lap_done`` aufgerufen.  Berechnet rollierenden
        Durchschnittsverbrauch (letzte 3 Runden) und feuert ``fuel_low`` /
        ``fuel_critical`` wenn die Restreichweite zu niedrig ist."""
        if frame.fuel_capacity <= 0:
            return  # EV oder kein Verbrauch

        if self._fuel_at_lap_start >= 0:
            consumption = self._fuel_at_lap_start - frame.fuel_level
            if consumption < 0:
                # Getankt — Flags und Stint-Daten zuruecksetzen
                self._fuel_low_fired = False
                self._fuel_crit_fired = False
                self._pit_call_fired = False
                self._stint_lap_times.clear()
            elif consumption > 0.01:
                self._fuel_history.append(consumption)
                if len(self._fuel_history) > 3:
                    self._fuel_history = self._fuel_history[-3:]

        self._fuel_at_lap_start = frame.fuel_level

        # Stint-Rundenzeiten fuer die Reifenempfehlung mitschreiben
        if frame.last_lap_ms > 0:
            self._stint_lap_times.append(frame.last_lap_ms)
            if len(self._stint_lap_times) > 30:
                self._stint_lap_times = self._stint_lap_times[-30:]

        if not self._fuel_history:
            return

        avg = sum(self._fuel_history) / len(self._fuel_history)
        if avg <= 0:
            return

        laps_left = frame.fuel_level / avg

        # Muss ueberhaupt getankt werden? Nur wenn der Sprit NICHT bis zum
        # Ziel reicht (bei Rennen ohne Rundenlimit: immer relevant).
        if frame.total_laps > 0:
            remaining = frame.total_laps - frame.current_lap + 1
            pit_needed = laps_left < remaining
        else:
            pit_needed = True

        # Kritisch hat Vorrang
        if (laps_left <= self._fuel_crit_laps and pit_needed
                and not self._fuel_crit_fired):
            await self._bus.publish("event.fuel_critical", {})
            self._fuel_crit_fired = True
            log.info("Sprit KRITISCH (~%.1f Runden verbleibend)", laps_left)
        elif (laps_left <= self._pit_call_laps and pit_needed
                and not self._pit_call_fired):
            # Rechtzeitiger Box-Ruf: Stopp noetig und Reichweite wird knapp —
            # inklusive Tank-/Reifenempfehlung zum Vorbereiten
            await self._bus.publish("event.pit_call",
                                    {"laps_left": max(1, int(laps_left)),
                                     **self._pit_advice(frame)})
            self._pit_call_fired = True
            log.info("Box-Ruf (~%.1f Runden Reichweite, Stopp noetig)", laps_left)
        elif laps_left <= self._fuel_low_laps and not self._fuel_low_fired:
            await self._bus.publish("event.fuel_low", {"laps_left": int(laps_left)})
            self._fuel_low_fired = True
            log.info("Sprit niedrig (~%d Runden verbleibend)", int(laps_left))

    # ================================================================
    #  Spin (Dreher)
    # ================================================================

    async def _check_spin(self, frame: TelemetryFrame) -> None:
        """Erkennt Dreher via Gierrate (``ang_vel_y``).

        Logik:
        1. ``|ang_vel_y|`` > Schwelle UND speed > Minimum -> Frame zaehlen
        2. Kumulierte Drehung (Integration ueber Gierrate) berechnen
        3. Ausloesung wenn Frames >= ``spin_sustain`` UND Drehung >= ``spin_aoa_trigger_deg``
        4. Zusatzbedingung: Gas niedrig ODER Geschwindigkeit sinkt (filtert Donuts)
        """
        if self._spin_cd > 0:
            self._spin_cd -= 1
            return

        speed = frame.speed_mps
        yaw_rate = abs(frame.ang_vel_y)  # rad/s

        if speed < self._spin_min_speed:
            self._spin_frames = 0
            self._spin_accum_deg = 0.0
            return

        if yaw_rate > _YAW_RATE_THRESHOLD:
            if self._spin_frames == 0:
                self._spin_entry_speed = speed
            self._spin_frames += 1
            # Grad pro Frame = deg/s * (1/60 s)
            self._spin_accum_deg += math.degrees(yaw_rate) / 60.0

            if (self._spin_frames >= self._spin_sustain
                    and self._spin_accum_deg >= self._spin_angle_deg):
                # Kein absichtlicher Donut: Gas niedrig oder Geschwindigkeit faellt
                if frame.throttle < 0.3 or speed < self._spin_entry_speed - 2.0:
                    angle = round(self._spin_accum_deg, 1)
                    spd_kmh = round(self._spin_entry_speed * 3.6, 1)
                    await self._bus.publish("event.spin", {
                        "angle_deg": angle,
                        "speed_kmh": spd_kmh,
                    })
                    log.info("Dreher: ~%.0f Grad bei %.0f km/h", angle, spd_kmh)
                    self._spin_cd = self._spin_cd_max
                    self._spin_frames = 0
                    self._spin_accum_deg = 0.0
                    return
        else:
            self._spin_frames = 0
            self._spin_accum_deg = 0.0

    # ================================================================
    #  Crash (Aufprall)
    # ================================================================

    async def _check_crash(self, frame: TelemetryFrame) -> None:
        """Erkennt Aufpralle via Geschwindigkeitsverlust pro Frame.

        ``dv = prev_speed - speed`` in m/s pro Tick (1/60s).
        Schwellen aus Config: minor / major / severe.
        """
        if self._crash_cd > 0:
            self._crash_cd -= 1
            return

        dv = self._prev_speed - frame.speed_mps  # positiv = Verzoegerung

        if dv < self._crash_dv_minor:
            return
        if self._prev_speed < self._crash_min_speed:
            return

        if dv >= self._crash_dv_severe:
            severity = "severe"
        elif dv >= self._crash_dv_major:
            severity = "major"
        else:
            severity = "minor"

        spd_kmh = round(self._prev_speed * 3.6, 1)
        await self._bus.publish("event.crash", {
            "severity": severity,
            "speed_kmh": spd_kmh,
        })
        log.info("Crash (%s) bei %.0f km/h (dv=%.2f m/s pro Tick)",
                 severity, spd_kmh, dv)
        self._crash_cd = self._crash_cd_max

    # ================================================================
    #  Offtrack (Streckenabkommen)
    # ================================================================

    async def _check_offtrack(self, frame: TelemetryFrame) -> None:
        """Fallback-Heuristik ohne Extended Packets:  Alle 4 Raeder zeigen
        hohes Schlupfverhaeltnis waehrend die Geschwindigkeit sinkt.

        Schlupf = |wheel_rps * tyre_radius - speed_mps| / max(speed_mps, 1)
        """
        if self._offtrack_cd > 0:
            self._offtrack_cd -= 1
            self._offtrack_frames = 0
            return

        speed = frame.speed_mps
        if (speed < 5.0 or frame.brake > 0.7
                or any(r <= 0 for r in frame.tyre_radius)):
            self._offtrack_frames = 0
            return

        # Schlupfverhaeltnis aller 4 Raeder pruefen
        all_slipping = True
        for i in range(4):
            wheel_speed = abs(frame.wheel_rps[i]) * frame.tyre_radius[i]
            slip = abs(wheel_speed - speed) / max(speed, 1.0)
            if slip <= self._offtrack_slip:
                all_slipping = False
                break

        if all_slipping:
            if self._offtrack_frames == 0:
                self._offtrack_entry_speed = speed
            self._offtrack_frames += 1

            # Geschwindigkeit muss insgesamt gesunken sein
            speed_dropping = speed < self._offtrack_entry_speed

            if self._offtrack_frames >= self._offtrack_sustain and speed_dropping:
                await self._bus.publish("event.offtrack", {})
                log.info("Streckenabkommen erkannt (%.0f -> %.0f km/h)",
                         self._offtrack_entry_speed * 3.6, speed * 3.6)
                self._offtrack_cd = self._offtrack_cd_max
                self._offtrack_frames = 0
        else:
            self._offtrack_frames = 0

    # ================================================================
    #  Reifen (Temperatur)
    # ================================================================

    async def _check_tyres(self, frame: TelemetryFrame) -> None:
        """Meldet heisse Reifen (pro Ecke max alle 30s eigenstaendiger Cooldown,
        zusaetzlich zum Director-Cooldown)."""
        now = time.monotonic()
        for i, pos in enumerate(_TYRE_POS):
            temp = frame.tyre_temp[i]
            if temp > self._tyre_hot_temp:
                if now - self._tyre_last[pos] >= _TYRE_SELF_COOLDOWN_S:
                    await self._bus.publish("event.tyre_hot", {
                        "pos": pos,
                        "temp": round(temp, 1),
                    })
                    self._tyre_last[pos] = now
                    log.info("Reifen %s heiss: %.0f C (Schwelle %.0f C)",
                             pos, temp, self._tyre_hot_temp)
