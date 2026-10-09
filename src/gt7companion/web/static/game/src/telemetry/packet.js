// Ein entschlüsseltes GT7-Telemetriepaket lesen. Reines Rechenmodul ohne DOM und ohne three.js.
//
// Die Pakete A (296 Byte), B (316) und C (368) teilen sich die ersten 296 Byte. Achsen der PS5: rechtshändig,
// Y nach oben, die Nase zeigt bei Einheitsquaternion nach −Z – genau wie in three.js. Längen in Metern.
// Offsets nach der Community-Referenz (Nenkai/PDTools, MacManley/gt7-udp) und dem Companion-Projekt.

export const MAGIC = 0x47375330;
export const BASE_SIZE = 296;
export const FULL_SIZE = 368;
export const PACKET_HZ = 59.94;      // Pakete je Sekunde; die Paketnummer ist die Uhr des Spiels
export const FRAME_MS = 1000 / 60;   // Spielzeit je Paket (die Rundenuhr läuft mit 60 Schritten je Sekunde)

/** Untergrund je Reifen in Paket C: T Asphalt, C Randstein, G Gras, S Sand, D Erde, s Schnee. */
export const SURFACE_OFFTRACK = 'GSDs';

/**
 * @param {Uint8Array} bytes entschlüsseltes Paket
 * @returns {object|null} Fahrdaten oder null, wenn es kein GT7-Paket ist
 */
export function parsePacket(bytes) {
  if (!bytes || bytes.length < BASE_SIZE) return null;
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (v.getUint32(0, true) !== MAGIC) return null;
  const flags = v.getUint16(0x8E, true);
  const qx = v.getFloat32(0x1C, true), qy = v.getFloat32(0x20, true);
  const qz = v.getFloat32(0x24, true), qw = v.getFloat32(0x28, true);
  const gears = bytes[0x90];
  const f = {
    pid: v.getInt32(0x70, true),
    x: v.getFloat32(0x04, true), y: v.getFloat32(0x08, true), z: v.getFloat32(0x0C, true),
    vx: v.getFloat32(0x10, true), vy: v.getFloat32(0x14, true), vz: v.getFloat32(0x18, true),
    qx, qy, qz, qw,
    // Kurs um die Hochachse: 0 = Nase nach −Z, positiv = nach links gedreht.
    yaw: Math.atan2(2 * (qx * qz + qw * qy), 1 - 2 * (qx * qx + qy * qy)),
    yawRate: v.getFloat32(0x30, true),
    speed: v.getFloat32(0x4C, true),          // m/s
    rpm: v.getFloat32(0x3C, true),
    lap: v.getInt16(0x74, true),              // 0 vor der ersten Linie, −1 im Menü
    totalLaps: v.getInt16(0x76, true),        // 0 = kein Rundenziel
    bestMs: v.getInt32(0x78, true),
    lastMs: v.getInt32(0x7C, true),
    onTrack: (flags & 0x1) !== 0,
    paused: (flags & 0x2) !== 0,
    loading: (flags & 0x4) !== 0,
    handbrake: (flags & 0x40) !== 0,
    gear: gears & 0x0F,
    throttle: bytes[0x91] / 255,
    brake: bytes[0x92] / 255,
    carId: v.getInt32(0x124, true),
    // Schlupf je Rad (VL, VR, HL, HR): Umfangsgeschwindigkeit des Reifens gegen das Tempo des Autos.
    // −1 = Rad steht (blockiert), 0 = rollt sauber, über 0 = dreht durch.
    slip: [0, 0, 0, 0],
    // Winkel zwischen Nase und Fahrtrichtung in rad (positiv = Nase zeigt weiter nach links): Driftwinkel.
    drift: 0,
    ext: false,
    steerWheel: 0,          // Lenkrad in rad, positiv = links
    surface: 'TTTT',        // VL, VR, HL, HR
    gameLapMs: -1,          // laufende Rundenuhr des Spiels
    wheelSteer: 0,          // mittlerer Einschlag der Vorderräder in rad, positiv = links
    carClass: '',
  };
  const ground = Math.hypot(f.vx, f.vz);
  for (let i = 0; i < 4; i++) {
    const rim = Math.abs(v.getFloat32(0xA4 + i * 4, true)) * v.getFloat32(0xB4 + i * 4, true);   // rad/s × m
    const slip = (rim - ground) / Math.max(ground, 6);
    f.slip[i] = Number.isFinite(slip) ? Math.max(-1, Math.min(slip, 3)) : 0;
  }
  if (ground > 4) {
    let drift = f.yaw - Math.atan2(-f.vx, -f.vz);
    drift = Math.atan2(Math.sin(drift), Math.cos(drift));
    f.drift = Math.abs(drift) < 2.2 ? drift : 0;        // rückwärts rollen ist kein Drift
  }
  if (bytes.length >= 316) {
    const steer = v.getFloat32(0x128, true);
    if (Number.isFinite(steer)) f.steerWheel = steer;
  }
  if (bytes.length >= FULL_SIZE) {
    f.ext = true;
    f.surface = String.fromCharCode(bytes[0x158], bytes[0x159], bytes[0x15A], bytes[0x15B]);
    f.gameLapMs = v.getInt32(0x15C, true);
    const left = v.getFloat32(0x160, true), right = v.getFloat32(0x164, true);
    if (Number.isFinite(left) && Number.isFinite(right)) f.wheelSteer = (left + right) / 2;
    let name = '';
    for (let i = 0x16C; i < 0x170; i++) {
      const c = bytes[i];
      if (c === 0) break;
      if (c > 32 && c < 127) name += String.fromCharCode(c);
    }
    f.carClass = name;
  }
  if (!Number.isFinite(f.x) || !Number.isFinite(f.z) || !Number.isFinite(f.yaw)) return null;
  return f;
}

/** Fährt das Auto gerade (auf der Strecke, nicht pausiert, nicht im Ladebildschirm, nicht im Menü)? */
export function isDriving(f) {
  return f.onTrack && !f.paused && !f.loading && f.lap >= 0;
}

/** Base64 → Bytes (im Browser und in Node gleich). */
export function fromBase64(text) {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}
