// Die 3D-Ansicht: Schreibtisch, Kreidespur, Bahn, Autos, Münzen, Öl, Requisiten, Rauch und Kamera.
// Bekommt Ereignisse des Spiels erst dann, wenn auch das gezeichnete Auto dort angekommen ist.

import * as THREE from 'three';
import { ps1Material, ps1Texture, createRenderer, shared } from './ps1.js';
import { buildTrackGeometry, templateFromMesh, fallbackTemplate } from './trackmesh.js';
import { findNode, firstMesh } from './assets.js';
import { ghostPose } from '../race/duel.js';
import { lerpAngle, wrapAngle } from '../telemetry/timeline.js';
import { placeWorld, placeSurvey } from '../world/placement.js';
import { noteFor } from '../world/notes.js';
import { KERB_LENGTH, KERB_WIDTH } from '../track/kerbs.js';

export const CAR_SCALE = 1.7;         // das Auto wird größer gezeichnet, als es ist: Spielzeug-Proportion
export const FRONT_STEER_GAIN = 1.5;  // stärker sichtbarer GT7-Lenkwinkel, nur an den Vorderrädern
export const TRACK_TOP = 0.15;        // Höhe der Fahrfläche über dem Tisch
export const COLORS = { player: 0xf2f2ee, best: 0x3f6df0, last: 0xe2382c };
const DESK_CELL = 16, DESK_CELLS = 28;
const WHEELS = [[-0.78, 1.33], [0.78, 1.33], [-0.78, -1.33], [0.78, -1.33]];   // rechts, vorn (VL VR HL HR)
const NOTE_W = 11, NOTE_H = 13.75;
const SHADOW_SIZE = [2.9, 5.7];       // Schatten unter dem Auto (vor CAR_SCALE): Breite, Länge in Metern
const SHADOW_HEIGHT = 0.7;            // so weit fällt er von der Lampe weg (in Metern je Metern Höhe: Lichtwinkel)
const COIN_SCALE = 2;                 // Münzen ebenfalls größer, damit man sie bei 320×240 sieht

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

// ── Kreidespur ────────────────────────────────────────────────────────────────────────────────────────

class Chalk {
  constructor(material, capacity = 16000) {
    this.capacity = capacity;
    this.position = new Float32Array(capacity * 6);
    this.uv = new Float32Array(capacity * 4);
    this.index = new Uint32Array(capacity * 6);
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute('position', new THREE.BufferAttribute(this.position, 3));
    this.geometry.setAttribute('uv', new THREE.BufferAttribute(this.uv, 2));
    this.geometry.setIndex(new THREE.BufferAttribute(this.index, 1));
    this.mesh = new THREE.Mesh(this.geometry, material);
    this.mesh.frustumCulled = false;
    this.reset();
  }

  reset() {
    this.built = 0;
    this.indexCount = 0;
    this.quadEnd = [];
    this.dist = [];
    this.breaks = new Set();
    this.geometry.setDrawRange(0, 0);
  }

  sync(trail, origin, half = 0.55, y = 0.05) {
    const n = Math.min(trail.x.length, this.capacity);
    if (n === this.built) return;
    for (const b of trail.breaks) this.breaks.add(b);
    const pos = this.position, uv = this.uv;
    for (let i = Math.max(this.built - 1, 0); i < n; i++) {
      const a = i > 0 && !this.breaks.has(i) ? i - 1 : i;
      const b = i < n - 1 && !this.breaks.has(i + 1) ? i + 1 : i;
      let dx = trail.x[b] - trail.x[a], dz = trail.z[b] - trail.z[a];
      const len = Math.hypot(dx, dz);
      if (len > 0) { dx /= len; dz /= len; } else { dx = 0; dz = -1; }
      const x = trail.x[i] - origin.x, z = trail.z[i] - origin.z;
      pos.set([x + dz * half, y, z - dx * half, x - dz * half, y, z + dx * half], i * 6);
      if (i >= this.built) {
        const step = i > 0 && !this.breaks.has(i) ? Math.hypot(trail.x[i] - trail.x[i - 1], trail.z[i] - trail.z[i - 1]) : 0;
        this.dist[i] = (i > 0 && !this.breaks.has(i) ? this.dist[i - 1] : 0) + step;
      }
      const u = this.dist[i] / 8;
      uv.set([u, 0, u, 1], i * 4);
    }
    for (let i = Math.max(this.built, 1); i < n; i++) {
      if (!this.breaks.has(i)) {
        const a = (i - 1) * 2, b = i * 2;
        this.index.set([a, a + 1, b, b, a + 1, b + 1], this.indexCount);
        this.indexCount += 6;
      }
      this.quadEnd[i] = this.indexCount;
    }
    this.quadEnd[0] = 0;
    this.built = n;
    this.geometry.attributes.position.needsUpdate = true;
    this.geometry.attributes.uv.needsUpdate = true;
    this.geometry.index.needsUpdate = true;
  }

  /** Nur so weit zeigen, wie das gezeichnete Auto schon gefahren ist. */
  showUntil(trail, pid) {
    let lo = 0, hi = this.built - 1;
    if (hi < 0) return;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (trail.pid[mid] <= pid) lo = mid; else hi = mid - 1;
    }
    this.geometry.setDrawRange(0, trail.pid[lo] <= pid ? this.quadEnd[lo] : 0);
  }
}

// ── Reifenspuren (Ringpuffer aus einzelnen Vierecken) ─────────────────────────────────────────────────

class SkidMarks {
  constructor(material, capacity = 1400) {
    this.capacity = capacity;
    this.next = 0;
    this.position = new Float32Array(capacity * 12);
    const uv = new Float32Array(capacity * 8), index = new Uint32Array(capacity * 6);
    for (let i = 0; i < capacity; i++) {
      uv.set([0, 0, 0, 1, 1, 0, 1, 1], i * 8);
      index.set([i * 4, i * 4 + 1, i * 4 + 2, i * 4 + 2, i * 4 + 1, i * 4 + 3], i * 6);
    }
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute('position', new THREE.BufferAttribute(this.position, 3));
    this.geometry.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    this.geometry.setIndex(new THREE.BufferAttribute(index, 1));
    this.mesh = new THREE.Mesh(this.geometry, material);
    this.mesh.frustumCulled = false;
  }

  reset() {
    this.position.fill(0);
    this.next = 0;
    this.geometry.attributes.position.needsUpdate = true;
  }

  add(ax, az, bx, bz, y, half) {
    let dx = bx - ax, dz = bz - az;
    const len = Math.hypot(dx, dz);
    if (len < 0.05 || len > 8) return;
    dx /= len; dz /= len;
    this.position.set([ax + dz * half, y, az - dx * half, ax - dz * half, y, az + dx * half,
      bx + dz * half, y, bz - dx * half, bx - dz * half, y, bz + dx * half], this.next * 12);
    this.next = (this.next + 1) % this.capacity;
    this.geometry.attributes.position.needsUpdate = true;
  }
}

// ── Rauch und Staub: kleine Wolken, die der Kamera zugewandt aufsteigen ───────────────────────────────

class Smoke {
  constructor(material, count = 64) {
    this.count = count;
    this.mesh = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), material, count);
    this.mesh.frustumCulled = false;
    this.parts = Array.from({ length: count }, () => ({ life: 0, age: 1, x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0, size: 1 }));
    this.next = 0;
    this.matrix = new THREE.Matrix4();
    this.scale = new THREE.Vector3();
    this.position = new THREE.Vector3();
    this.color = new THREE.Color();
    for (let i = 0; i < count; i++) this.mesh.setColorAt(i, this.color.setRGB(1, 1, 1));
    this.reset();
  }

  reset() {
    for (const p of this.parts) p.life = 0;
    this.matrix.makeScale(0, 0, 0);
    for (let i = 0; i < this.count; i++) this.mesh.setMatrixAt(i, this.matrix);
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  spawn(x, y, z, vx, vz, size, life, r, g, b) {
    const p = this.parts[this.next];
    Object.assign(p, { x, y, z, vx, vy: 1.6 + Math.random() * 1.4, vz, size, life, age: 0 });
    this.mesh.setColorAt(this.next, this.color.setRGB(r, g, b));
    this.mesh.instanceColor.needsUpdate = true;
    this.next = (this.next + 1) % this.count;
  }

  update(dt, camera) {
    for (let i = 0; i < this.count; i++) {
      const p = this.parts[i];
      if (p.life <= 0) continue;
      p.age += dt;
      if (p.age >= p.life) {
        p.life = 0;
        this.matrix.makeScale(0, 0, 0);
      } else {
        const k = p.age / p.life;
        p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
        p.vx *= 0.96; p.vz *= 0.96;
        const s = p.size * (0.5 + 1.6 * k) * (k > 0.7 ? 1 - (k - 0.7) / 0.3 * 0.6 : 1);
        this.matrix.compose(this.position.set(p.x, p.y, p.z), camera.quaternion, this.scale.set(s, s, s));
      }
      this.mesh.setMatrixAt(i, this.matrix);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }
}

// ── Auto ──────────────────────────────────────────────────────────────────────────────────────────────

class CarView {
  constructor(assets, color) {
    this.root = new THREE.Group();          // Ort und Kurs
    this.spinner = new THREE.Group();       // zusätzliche Drehung (Ölfleck)
    this.root.add(this.spinner);
    this.materials = [];
    this.wheels = [];
    this.wheelRadius = 0.33;
    const model = assets.models.r34;
    if (model) {
      const body = model.clone(true);
      body.traverse((node) => {
        if (!node.isMesh) return;
        const source = node.material;
        const paint = /paint/i.test(source.name);
        const material = ps1Material({ map: source.map ?? null, color: paint ? color : 0xffffff, name: source.name });
        node.material = material;
        this.materials.push(material);
      });
      for (const name of ['WheelFL', 'WheelFR', 'WheelRL', 'WheelRR']) {
        const wheel = body.getObjectByName(name);
        if (wheel) { wheel.rotation.order = 'YXZ'; this.wheels.push(wheel); }
      }
      const box = new THREE.Box3().setFromObject(firstMesh(this.wheels[0]) ?? body);
      if (this.wheels.length) this.wheelRadius = Math.max((box.max.y - box.min.y) / 2, 0.2);
      this.spinner.add(body);
    } else {
      // Ersatz ohne Modell: Kasten mit Dach und vier Rädern
      const paint = ps1Material({ color });
      const dark = ps1Material({ color: 0x20242c });
      const lower = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.62, 4.5), paint);
      lower.position.y = 0.55;
      const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.55, 0.5, 2.1), dark);
      cabin.position.set(0, 1.08, 0.25);
      const wing = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.08, 0.35), paint);
      wing.position.set(0, 1.12, 2.05);
      this.spinner.add(lower, cabin, wing);
      for (const [x, z] of WHEELS) {
        const wheel = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.66, 0.66), dark);
        wheel.position.set(x, 0.33, -z);
        wheel.rotation.order = 'YXZ';
        this.spinner.add(wheel);
        this.wheels.push(wheel);
      }
      this.materials.push(paint, dark);
    }
    this.spinner.scale.setScalar(CAR_SCALE);
    // Leichter Schlagschatten: weich ausgeblendet, von der Lampe weg versetzt (siehe place)
    this.shadow = new THREE.Mesh(new THREE.PlaneGeometry(SHADOW_SIZE[0] * CAR_SCALE, SHADOW_SIZE[1] * CAR_SCALE),
      ps1Material({ map: assets.tex.shadow, lit: false, affine: 0, offset: 2, depthWrite: false, fog: false, soft: true }));
    this.shadow.rotation.x = -Math.PI / 2;
    this.shadow.position.y = 0.04;
    this.root.add(this.shadow);
    this.spinTime = 0;
  }

  set stipple(on) {
    for (const material of this.materials) material.uniforms.uStipple.value = on ? 1 : 0;
  }

  /** Ölfleck: zwei schnelle Drehungen auf der Stelle (nur gezeichnet, das echte Auto fährt weiter). */
  spin() {
    this.spinTime = 0.9;
  }

  place(x, y, z, yaw, steer, speed, dt) {
    this.root.position.set(x, y, z);
    this.root.rotation.y = yaw;
    // Der Schatten fällt in der Welt immer zur selben Seite, nicht mit dem Auto gedreht
    const light = shared.uLightDir.value;
    const dx = -light.x / light.y * SHADOW_HEIGHT, dz = -light.z / light.y * SHADOW_HEIGHT;
    const c = Math.cos(yaw), s = Math.sin(yaw);
    this.shadow.position.set(dx * c - dz * s, 0.04, dx * s + dz * c);
    if (this.spinTime > 0) {
      this.spinTime = Math.max(0, this.spinTime - dt);
      const k = 1 - this.spinTime / 0.9;
      this.spinner.rotation.y = Math.PI * 4 * (1 - (1 - k) * (1 - k));
    } else this.spinner.rotation.y = 0;
    const roll = speed / this.wheelRadius * dt;
    this.wheels.forEach((wheel, i) => {
      wheel.rotation.x -= roll;
      if (i < 2) wheel.rotation.y = clamp(steer, -0.6, 0.6) * FRONT_STEER_GAIN;
    });
  }
}

// ── Die Ansicht ───────────────────────────────────────────────────────────────────────────────────────

export class View {
  constructor(canvas, assets, { width = 640, height = 480 } = {}) {
    this.assets = assets;
    this.width = width; this.height = height;
    this.renderer = createRenderer(canvas, width, height);
    this.scene = new THREE.Scene();
    // Nah-Ebene weit vorn: Die Kamera ist nie näher als 20 m an irgendetwas, und ein grober Tiefenpuffer
    // (manche Browser geben nur 16 Bit) trennt so auch in der Ferne Kreide, Tisch und Bahn sauber.
    this.camera = new THREE.PerspectiveCamera(34, width / height, 8, 460);
    this.cam = { yaw: 0, dist: 60, x: 0, z: 0, ready: false };
    const tex = assets.tex;

    // Schreibtisch: ein Gitter, das mit der Kamera wandert; die Maserung hängt am Ort in der Welt.
    const desk = new THREE.PlaneGeometry(DESK_CELL * DESK_CELLS, DESK_CELL * DESK_CELLS, DESK_CELLS, DESK_CELLS);
    desk.rotateX(-Math.PI / 2);
    this.desk = new THREE.Mesh(desk, ps1Material({ map: tex.desk_wood, uvWorld: 1 / 28, affine: 0.3 }));
    this.desk.frustumCulled = false;
    this.scene.add(this.desk);

    this.chalk = new Chalk(ps1Material({ map: tex.chalk, lit: false, affine: 0, doubleSide: true }));
    this.scene.add(this.chalk.mesh);
    this.skids = new SkidMarks(ps1Material({ map: tex.skid, lit: false, affine: 0, doubleSide: true, offset: 3 }));
    this.scene.add(this.skids.mesh);
    this.smoke = new Smoke(ps1Material({ map: tex.chalk_dust, lit: false, affine: 0, stipple: true,
      doubleSide: true, depthWrite: false }));
    this.scene.add(this.smoke.mesh);

    // Bahn
    const kit = assets.models.kit;
    const pieceMesh = firstMesh(findNode(kit, 'PieceStraight'));
    this.template = pieceMesh ? templateFromMesh(pieceMesh) : fallbackTemplate();
    this.trackMaterial = ps1Material({ map: pieceMesh?.material.map ?? tex.track, reveal: true, affine: 0.5 });
    this.trackGroup = new THREE.Group();
    this.scene.add(this.trackGroup);
    this.world = new THREE.Group();           // Requisiten, Zettel, Startbogen
    this.scene.add(this.world);
    this.propWorld = new THREE.Group();
    this.scene.add(this.propWorld);
    this.propMaterials = new Map();
    // Randsteine: Stücke aus dem Bausatz, dort wo die PS5 welche gemeldet hat
    const kerbMesh = firstMesh(findNode(kit, 'Kerb'));
    let kerbGeometry = kerbMesh?.geometry;
    if (!kerbGeometry) {
      kerbGeometry = new THREE.BoxGeometry(1, 0.12, 1);
      kerbGeometry.translate(0.5, 0.06, -0.5);
    }
    this.kerbs = new THREE.InstancedMesh(kerbGeometry, ps1Material({ map: kerbMesh?.material.map ?? null,
      color: kerbMesh ? 0xffffff : 0xd8362c, doubleSide: true }), 600);
    this.kerbs.frustumCulled = false;
    this.kerbs.count = 0;
    this.scene.add(this.kerbs);

    // Autos
    this.player = new CarView(assets, COLORS.player);
    this.scene.add(this.player.root);
    this.ghosts = new Map();                  // id → { car, align, blink }
    for (const id of ['best', 'last']) {
      const car = new CarView(assets, COLORS[id]);
      car.root.visible = false;
      this.scene.add(car.root);
      this.ghosts.set(id, { car, align: null, focusWeight: 0, hint: -1 });
    }

    // Münzen und Öl
    const coinMesh = firstMesh(findNode(assets.models.props, 'Coin'));
    let coinGeometry;
    if (coinMesh) coinGeometry = coinMesh.geometry;
    else {
      coinGeometry = new THREE.CylinderGeometry(0.9, 0.9, 0.25, 8);
      coinGeometry.rotateZ(Math.PI / 2);
      coinGeometry.translate(0, 0.9, 0);
    }
    this.propsMap = coinMesh?.material.map ?? null;
    this.propsMaterial = this.propsMap ? ps1Material({ map: this.propsMap, vertexColors: !!coinMesh.geometry.attributes.color }) : null;
    this.coins = new THREE.InstancedMesh(coinGeometry,
      coinMesh ? this.propsMaterial : ps1Material({ color: 0xf2c230 }), 160);
    this.coins.frustumCulled = false;
    this.scene.add(this.coins);
    const oil = new THREE.PlaneGeometry(6.4, 6.4);
    oil.rotateX(-Math.PI / 2);
    this.oils = new THREE.InstancedMesh(oil, ps1Material({ map: tex.oil, lit: false, affine: 0, offset: 3 }), 48);
    this.oils.frustumCulled = false;
    this.scene.add(this.oils);
    this.sparks = new Smoke(ps1Material({ map: tex.spark, lit: false, affine: 0, doubleSide: true, depthWrite: false,
      fog: false }), 16);
    this.scene.add(this.sparks.mesh);

    this.matrix = new THREE.Matrix4();
    this.quat = new THREE.Quaternion();
    this.vec = new THREE.Vector3();
    this.unit = new THREE.Vector3(1, 1, 1);
    this.coinScale = new THREE.Vector3(COIN_SCALE, COIN_SCALE, COIN_SCALE);
    this.up = new THREE.Vector3(0, 1, 0);
    this.reset();
  }

  resize(width, height) {
    this.width = width; this.height = height;
    this.renderer.setSize(width, height, false);
    shared.uRes.value.set(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.cam.ready = false;
    this.cam.frameX = this.cam.frameZ = 0;
    this.cam.frameScale = 1;
  }

  // ── Zustand ───────────────────────────────────────────────────────────────────────────────────────

  reset() {
    this.origin = null;
    this.track = null;
    this.surface = 0;                 // Höhe, auf der das Auto fährt
    this.reveal = { value: 1e9, target: 1e9, rate: 0 };
    this.trackMaterial.uniforms.uReveal.value = 1e9;
    this.clearGroup(this.trackGroup);
    this.clearGroup(this.world);
    this.clearGroup(this.propWorld);
    this.propsLayout = [];
    this.propSlots = [];
    this.surveyAt = 0;
    this.idleProps = false;
    this.notes = [];
    this.noteMeshes = [];
    this.noteLap = 0;
    this.items = new Map();           // id → { item, slot, kind }
    this.hideItems();
    if (this.kerbs) this.kerbs.count = 0;
    this.chalk.reset();
    this.chalk.mesh.visible = true;
    this.skids.reset();
    this.smoke.reset();
    this.sparks.reset();
    this.prevWheels = null;
    this.hint = -1;
    this.playerS = 0;
    this.cam.ready = false;
    this.cam.frameX = this.cam.frameZ = 0;
    this.cam.frameScale = 1;
    for (const ghost of this.ghosts.values()) { ghost.align = null; ghost.focusWeight = 0; ghost.car.root.visible = false; }
    this.player.root.visible = false;
  }

  clearGroup(group) {
    for (const child of [...group.children]) {
      group.remove(child);
      if (child.isInstancedMesh) child.dispose();
      if (child.userData.ownGeometry) child.geometry.dispose();
      if (child.userData.ownMaterial) { child.material.uniforms?.map?.value?.dispose(); child.material.dispose(); }
    }
  }

  hideItems() {
    this.matrix.makeScale(0, 0, 0);
    for (let i = 0; i < this.coins.count; i++) this.coins.setMatrixAt(i, this.matrix);
    for (let i = 0; i < this.oils.count; i++) this.oils.setMatrixAt(i, this.matrix);
    this.coins.instanceMatrix.needsUpdate = true;
    this.oils.instanceMatrix.needsUpdate = true;
  }

  // ── Ereignisse des Spiels ─────────────────────────────────────────────────────────────────────────

  /** @param {boolean} instant ohne Einblendung (beim Nachholen nach dem Laden der Seite) */
  handle(e, game, instant = false) {
    switch (e.type) {
      case 'reset': this.reset(); break;
      case 'track': this.setTrack(e.track, e.how, instant); break;
      case 'ghosts':
        for (const [id, ghost] of this.ghosts) {
          const next = e.ghosts.find((g) => g.id === id);
          ghost.align = next ?? null;
        }
        if (!e.newMatch) this.nextNotes();
        break;
      case 'items': this.setItems(e.items); break;
      case 'kerbs': this.setKerbs(e.pieces); break;
      case 'drop': this.addItem(e.item); break;
      case 'coin': case 'oil': case 'expire': this.takeItem(e, instant); break;
      default: break;
    }
  }

  setTrack(track, how, instant) {
    if (!this.origin) this.origin = { x: Math.round(track.x[0]), z: Math.round(track.z[0]) };
    this.track = track;
    this.hint = -1;
    this.clearGroup(this.trackGroup);
    const here = this.lastPose ? track.project(this.lastPose.x, this.lastPose.z, -1).s : 0;
    const built = buildTrackGeometry(track, this.template, { origin: this.origin, firstS: here });
    for (const geometry of built.geometries) {
      const mesh = new THREE.Mesh(geometry, this.trackMaterial);
      mesh.userData.ownGeometry = true;
      this.trackGroup.add(mesh);
    }
    if (how === 'neu' && !instant) {
      // Die Teile klicken der Reihe nach ein: einmal rundherum in gut drei Sekunden.
      this.reveal = { value: 0, target: built.pieces + 1, rate: built.pieces / 3.2 };
      this.chalk.mesh.visible = true;
    } else {
      this.reveal = { value: 1e9, target: 1e9, rate: 0 };
      this.chalk.mesh.visible = false;
      this.surface = TRACK_TOP;
    }
    this.trackMaterial.uniforms.uReveal.value = this.reveal.value;
    if (how !== 'ränder') this.setWorld(placeWorld(track, { previous: how === 'neu' ? [] : this.propsLayout.filter((p) => p.group) }), instant);
  }

  setProps(list, instant = false) {
    const before = new Map(this.propsLayout.map((p) => [p.id, p]));
    this.clearGroup(this.propWorld);
    this.propsLayout = list;
    this.propSlots = [];
    const origin = this.origin ?? { x: 0, z: 0 };
    const byType = new Map();
    for (const prop of list) (byType.get(prop.type) ?? byType.set(prop.type, []).get(prop.type)).push(prop);
    for (const [type, group] of byType) {
      const source = firstMesh(findNode(this.assets.models.desk, type) ?? findNode(this.assets.models.props, type));
      if (!source) continue;
      source.updateWorldMatrix(true, false);
      if (!this.propMaterials.has(type)) this.propMaterials.set(type,
        ps1Material({ map: source.material.map, vertexColors: !!source.geometry.attributes.color }));
      const mesh = new THREE.InstancedMesh(source.geometry, this.propMaterials.get(type), group.length);
      mesh.name = type;
      source.geometry.computeBoundingBox();
      const bounds = source.geometry.boundingBox;
      group.forEach((prop, slot) => {
        const base = new THREE.Matrix4().compose(new THREE.Vector3(prop.x - origin.x, prop.y ?? 0, prop.z - origin.z),
          new THREE.Quaternion().setFromAxisAngle(this.up, prop.rot), this.unit).multiply(source.matrixWorld);
        const old = before.get(prop.id);
        const growth = instant || old && old.x === prop.x && old.z === prop.z ? 1 : 0.05;
        mesh.setMatrixAt(slot, base);
        this.propSlots.push({ mesh, slot, prop, base, growth, hidden: false,
          height: bounds.max.y, radius: Math.max(Math.hypot(bounds.min.x, bounds.min.z), Math.hypot(bounds.max.x, bounds.max.z)) });
      });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.computeBoundingSphere();
      this.propWorld.add(mesh);
    }
  }

  setWorld(world, instant = false) {
    this.clearGroup(this.world);
    const { assets, origin } = this;
    this.setProps([...world.props, ...world.cones.map((c, i) => ({ ...c, type: 'Cone', id: `cone-${i}`, rot: 0 }))], instant);
    // Zettel: liniertes Papier mit Handschrift
    this.notes = world.notes;
    this.noteMeshes = [];
    for (const note of world.notes) {
      const texture = this.noteTexture(noteFor(note.index, this.noteLap).text);
      const geometry = new THREE.PlaneGeometry(NOTE_W, NOTE_H);
      geometry.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geometry, ps1Material({ map: texture, lit: false, affine: 0.4, offset: 1 }));
      mesh.position.set(note.x - origin.x, 0.06, note.z - origin.z);
      mesh.rotation.y = note.rot + 0.12 * (note.index % 2 ? 1 : -1);
      mesh.userData.ownGeometry = mesh.userData.ownMaterial = true;
      this.world.add(mesh);
      this.noteMeshes.push(mesh);
    }
    // Startbogen an der Linie
    const gantry = firstMesh(findNode(assets.models.kit, 'Gantry'));
    if (gantry) {
      const mesh = new THREE.Mesh(gantry.geometry, ps1Material({ map: gantry.material.map }));
      mesh.position.set(world.gantry.x - origin.x, 0, world.gantry.z - origin.z);
      mesh.rotation.y = world.gantry.yaw;
      mesh.scale.set(world.gantry.half + 1.5, 1, 1);
      mesh.userData.ownMaterial = false;
      this.world.add(mesh);
    }
  }

  /** Neue Runde: Auf den Zetteln stehen die nächsten Anekdoten. */
  nextNotes() {
    this.noteLap++;
    this.noteMeshes.forEach((mesh, i) => {
      const old = mesh.material.uniforms.map.value;
      mesh.material.uniforms.map.value = this.noteTexture(noteFor(this.notes[i].index, this.noteLap).text);
      old?.dispose();
    });
  }

  /** Text in Handschrift auf liniertes Papier setzen (kleines Bild, wird ohne Filter gezeichnet). */
  noteTexture(text) {
    const canvas = document.createElement('canvas');
    canvas.width = 128; canvas.height = 160;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    const paper = this.assets.images.paper;
    if (paper) {
      for (let y = 0; y < canvas.height; y += paper.height) {
        for (let x = 0; x < canvas.width; x += paper.width) ctx.drawImage(paper, x, y);
      }
    } else {
      ctx.fillStyle = '#f4f1e4';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    drawText(ctx, this.assets.fonts.hand, text, 12, 10, { width: 108, color: '#1c2f8a' });
    const texture = new THREE.CanvasTexture(canvas);
    return ps1Texture(texture);
  }

  /** Randstein-Stücke entlang der Strecke auslegen; `side` +1 = links der Fahrtrichtung. */
  setKerbs(pieces) {
    const track = this.track, o = this.origin, p = {};
    const count = Math.min(pieces.length, 600);
    const scale = new THREE.Vector3();
    for (let i = 0; i < count; i++) {
      const piece = pieces[i];
      // Das Stück wächst von seiner Innenkante nach außen (Vorlage: X von 0 bis 1) und nach vorn (Z bis −1).
      track.pos(piece.s - KERB_LENGTH / 2, piece.d - piece.side * KERB_WIDTH / 2, p);
      this.matrix.compose(this.vec.set(p.x - o.x, TRACK_TOP, p.z - o.z), this.quat.setFromAxisAngle(this.up, p.yaw),
        scale.set(-piece.side * KERB_WIDTH, 1, KERB_LENGTH));
      this.kerbs.setMatrixAt(i, this.matrix);
    }
    this.kerbs.count = count;
    this.kerbs.instanceMatrix.needsUpdate = true;
  }

  setItems(list) {
    this.items.clear();
    this.hideItems();
    let coin = 0, oil = 0;
    for (const item of list) {
      if (item.taken) continue;
      const kind = item.kind === 'oil' ? 'oil' : 'coin';
      const slot = kind === 'oil' ? oil++ : coin++;
      if (slot >= (kind === 'oil' ? this.oils.count : this.coins.count)) continue;
      this.items.set(item.id, { item, kind, slot });
    }
    this.placeOil();
  }

  addItem(item) {
    const kind = item.kind === 'oil' ? 'oil' : 'coin';
    const used = new Set([...this.items.values()].filter((v) => v.kind === kind).map((v) => v.slot));
    const max = kind === 'oil' ? this.oils.count : this.coins.count;
    let slot = 0;
    while (used.has(slot) && slot < max) slot++;
    if (slot >= max) return;
    this.items.set(item.id, { item, kind, slot, dropped: 1 });
    this.placeOil();
  }

  placeOil() {
    for (const { item, kind, slot } of this.items.values()) {
      if (kind !== 'oil') continue;
      this.matrix.compose(this.vec.set(item.x - this.origin.x, this.surface + 0.05, item.z - this.origin.z),
        this.quat.setFromAxisAngle(this.up, item.id * 1.7), this.unit);
      this.oils.setMatrixAt(slot, this.matrix);
    }
    this.oils.instanceMatrix.needsUpdate = true;
  }

  takeItem(e, instant) {
    const entry = this.items.get(e.item.id);
    if (!entry) return;
    this.items.delete(e.item.id);
    this.matrix.makeScale(0, 0, 0);
    if (entry.kind === 'oil') {
      if (e.type === 'oil' && !instant) this.player.spin();
      else if (e.type !== 'oil') { this.oils.setMatrixAt(entry.slot, this.matrix); this.oils.instanceMatrix.needsUpdate = true; }
    } else {
      this.coins.setMatrixAt(entry.slot, this.matrix);
      if (e.type === 'coin' && !instant) {
        for (let i = 0; i < 3; i++) {
          this.sparks.spawn(e.item.x - this.origin.x, this.surface + 1.5 + i, e.item.z - this.origin.z,
            (Math.random() - 0.5) * 6, (Math.random() - 0.5) * 6, 3.2, 0.45, 1, 1, 1);
        }
      }
    }
  }

  // ── Bild für Bild ─────────────────────────────────────────────────────────────────────────────────

  /**
   * @param {number} dt Sekunden seit dem letzten Bild
   * @param {number} time laufende Sekunden (für Drehungen)
   * @param {object|null} pose Lage des eigenen Autos aus der Zeitachse
   */
  update(dt, time, pose, game) {
    if (!pose) return this.idle(dt, time);
    if (!this.origin) this.origin = { x: Math.round(pose.x), z: Math.round(pose.z) };
    this.lastPose = pose;
    const o = this.origin, track = this.track;
    const x = pose.x - o.x, z = pose.z - o.z;

    // Bahnteile klicken ein
    const reveal = this.reveal;
    if (reveal.value < reveal.target) {
      reveal.value = Math.min(reveal.target, reveal.value + reveal.rate * dt);
      this.trackMaterial.uniforms.uReveal.value = reveal.value;
      if (reveal.value >= reveal.target) { this.chalk.mesh.visible = false; this.surface = TRACK_TOP; this.placeOil(); }
      else this.surface = Math.min(TRACK_TOP, TRACK_TOP * reveal.value / 6);
    }
    if (this.chalk.mesh.visible) {
      this.chalk.sync(game.trail, o);
      this.chalk.showUntil(game.trail, pose.pid);
      if (!track && pose.pid >= this.surveyAt) {
        this.surveyAt = pose.pid + 30;
        const list = placeSurvey(game.trail, pose.pid, this.propsLayout.filter((p) => p.group?.startsWith('survey-')));
        if (list.length !== this.propsLayout.length || list.some((p, i) => p !== this.propsLayout[i])) this.setProps(list);
      }
    }

    // eigenes Auto
    this.player.root.visible = true;
    this.player.place(x, this.surface, z, pose.yaw, pose.steer, pose.speed, dt);
    this.effects(pose, x, z, dt);

    // Geister
    let nearest = Infinity;
    if (track) {
      const p = track.project(pose.x, pose.z, this.hint);
      this.hint = p.i;
      this.playerS = p.s;
      const clock = game.clockAt(pose.pid);
      for (const ghost of this.ghosts.values()) {
        if (!ghost.align) { ghost.car.root.visible = false; continue; }
        const g = ghostPose(ghost.align, track.length, clock, this.ghostOut ??= {});
        const d = Math.hypot(g.x - pose.x, g.z - pose.z);
        nearest = Math.min(nearest, d);
        ghost.car.root.visible = true;
        const focus = clamp((75 - d) / 35, 0, 1);
        ghost.focusWeight += (focus - ghost.focusWeight) * (1 - Math.exp(-dt / 0.4));
        ghost.car.stipple = d < 7.5 * CAR_SCALE;         // wo sich die Autos überdecken, wird der Geist gerastert
        ghost.car.place(g.x - o.x, this.surface, g.z - o.z, g.yaw, g.steer, g.speed, dt);
      }
    }

    // Münzen drehen sich
    for (const { item, kind, slot } of this.items.values()) {
      if (kind !== 'coin') continue;
      this.matrix.compose(this.vec.set(item.x - o.x, this.surface + 0.25 + 0.3 * Math.sin(time * 4 + item.id), item.z - o.z),
        this.quat.setFromAxisAngle(this.up, time * 3.2 + item.id), this.coinScale);
      this.coins.setMatrixAt(slot, this.matrix);
    }
    this.coins.instanceMatrix.needsUpdate = true;

    this.smoke.update(dt, this.camera);
    this.sparks.update(dt, this.camera);
    this.follow(dt, x, z, pose, nearest);
    this.updateProps(dt);
    return null;
  }

  /** Bremsspuren, Reifenqualm, Staub: aus Radschlupf, Driftwinkel und Untergrund. */
  effects(pose, x, z, dt) {
    const f = pose.frame;
    const sin = Math.sin(pose.yaw), cos = Math.cos(pose.yaw);       // vorwärts (−sin, −cos), rechts (cos, −sin)
    const wheels = [];
    for (const [rx, fz] of WHEELS) {
      wheels.push([x + (cos * rx - sin * fz) * CAR_SCALE, z + (-sin * rx - cos * fz) * CAR_SCALE]);
    }
    const sliding = Math.abs(f.drift) > 0.12 && pose.speed > 8;
    const y = this.surface + 0.03;
    for (let i = 0; i < 4; i++) {
      const rear = i >= 2;
      const locked = f.slip[i] < -0.2 && (f.brake > 0.2 || f.handbrake);
      const spinning = f.slip[i] > 0.25 && f.throttle > 0.4;
      const off = 'GSDs'.includes(f.surface[i]);
      const marks = !off && pose.speed > 3 && (locked || spinning || (sliding && (rear || Math.abs(f.drift) > 0.3)));
      if (marks && this.prevWheels) {
        this.skids.add(this.prevWheels[i][0], this.prevWheels[i][1], wheels[i][0], wheels[i][1], y, 0.24 * CAR_SCALE);
      }
      const strength = off ? 0.5 : marks ? clamp(Math.abs(f.drift) * 2 + Math.abs(f.slip[i]), 0.3, 1) : 0;
      if (strength > 0 && pose.speed > 5 && Math.random() < strength * dt * 26) {
        const shade = off ? [0.62, 0.5, 0.36] : [0.93, 0.93, 0.9];
        this.smoke.spawn(wheels[i][0], y + 0.4, wheels[i][1], (Math.random() - 0.5) * 3, (Math.random() - 0.5) * 3,
          (off ? 2.4 : 3) * (0.8 + strength), 0.55 + strength * 0.4, ...shade);
      }
    }
    this.prevWheels = wheels;
  }

  /** Kamera schräg von oben: folgt dem Auto, dreht träge mit der Strecke, rückt bei Tempo weiter weg. */
  follow(dt, x, z, pose, nearest) {
    const cam = this.cam;
    let heading = pose.yaw;
    if (this.track) heading = this.track.pos(this.playerS + 30 + pose.speed * 0.6).yaw;
    // Je schneller, desto weiter weg und flacher: Bei 300 km/h sieht man so gut 90 m voraus (eine Sekunde),
    // im Stand ist das Auto groß im Bild.
    const speedPart = clamp(pose.speed / 85, 0, 1);
    let dist = 36 + 68 * speedPart;
    if (nearest < 70) dist = Math.max(dist, 34 + nearest * 1.2);       // den nächsten Gegner im Bild halten
    const portrait = this.height > this.width;
    // Leicht weiter weg in 9:16: genug Breite für Bahn und nahe Gegner, mehr Vorschau nach oben.
    if (portrait) dist *= 1.55;
    const pitch = portrait ? 1.05 - 0.1 * speedPart : 0.98 - 0.2 * speedPart;
    const ahead = portrait ? 10 + 30 * speedPart : 4 + 21 * speedPart;
    let tx = x - Math.sin(pose.yaw) * ahead, tz = z - Math.cos(pose.yaw) * ahead;
    if (portrait) {
      let weight = 1;
      for (const ghost of this.ghosts.values()) {
        if (!ghost.car.root.visible) continue;
        const w = ghost.focusWeight * 0.5;
        tx += ghost.car.root.position.x * w; tz += ghost.car.root.position.z * w; weight += w;
      }
      tx /= weight; tz /= weight;
    }
    if (!cam.ready) {
      Object.assign(cam, { yaw: heading, dist, pitch, x: tx, z: tz, ready: true });
    } else {
      cam.yaw = lerpAngle(cam.yaw, heading, 1 - Math.exp(-dt / 1.1));
      cam.dist += (dist - cam.dist) * (1 - Math.exp(-dt / 0.9));
      cam.pitch += (pitch - cam.pitch) * (1 - Math.exp(-dt / 0.9));
      const k = 1 - Math.exp(-dt / 0.12);
      cam.x += (tx - cam.x) * k; cam.z += (tz - cam.z) * k;
    }
    this.aim(cam.x, cam.z, cam.yaw, cam.dist, cam.pitch);
    if (portrait) {
      const cars = [{ car: this.player, weight: 1 }, ...[...this.ghosts.values()]
        .filter((g) => g.car.root.visible && g.focusWeight > 0.001).map((g) => ({ car: g.car, weight: g.focusWeight }))];
      let fx = cam.x, fz = cam.z, distance = cam.dist;
      // Zwei begrenzte Korrekturen: gemeinsame Bildmitte, dann genügend Breite für nahe Gegner.
      for (let pass = 0; pass < 2; pass++) {
        this.camera.updateMatrixWorld();
        let lo = Infinity, hi = -Infinity, depth = 0;
        const playerScreen = this.vec.copy(this.player.root.position).project(this.camera).x;
        for (const { car, weight } of cars) {
          depth += -this.vec.copy(car.root.position).applyMatrix4(this.camera.matrixWorldInverse).z;
          const screen = this.vec.copy(car.root.position).project(this.camera);
          const sx = playerScreen + (screen.x - playerScreen) * weight;
          lo = Math.min(lo, sx); hi = Math.max(hi, sx);
        }
        const centre = cars.length > 1 ? (lo + hi) / 2 : lo - clamp(lo, -0.3, 0.3);
        const shift = centre * depth / cars.length * Math.tan(this.camera.fov * Math.PI / 360) * this.camera.aspect;
        const right = this.camera.matrixWorld.elements;
        fx += right[0] * shift; fz += right[2] * shift;
        distance *= Math.max(1, (hi - lo) / 1.45);
        this.aim(fx, fz, cam.yaw, distance, cam.pitch);
      }
      const k = 1 - Math.exp(-dt / 0.28);
      cam.frameX = (cam.frameX ?? 0) + (fx - cam.x - (cam.frameX ?? 0)) * k;
      cam.frameZ = (cam.frameZ ?? 0) + (fz - cam.z - (cam.frameZ ?? 0)) * k;
      cam.frameScale = (cam.frameScale ?? 1) + (distance / cam.dist - (cam.frameScale ?? 1)) * k;
      this.aim(cam.x + cam.frameX, cam.z + cam.frameZ, cam.yaw, cam.dist * cam.frameScale, cam.pitch);
    }
  }

  aim(x, z, yaw, dist, pitch) {
    const back = Math.cos(pitch) * dist, height = Math.sin(pitch) * dist;
    this.camera.position.set(x + Math.sin(yaw) * back, height, z + Math.cos(yaw) * back);
    this.camera.lookAt(x, 0, z);
    this.desk.position.set(Math.round(x / DESK_CELL) * DESK_CELL, 0, Math.round(z / DESK_CELL) * DESK_CELL);
  }

  /** Ohne Daten: Das Auto steht auf dem Tisch, die Kamera kreist langsam darum. */
  idle(dt, time) {
    if (!this.idleProps && !this.track && !this.origin) {
      this.setProps([{ id: 'idle-pencil', type: 'PencilBlue', x: -8, z: -3, rot: -0.3 },
        { id: 'idle-book', type: 'Notebook', x: 10, z: 1, rot: 0.15 },
        { id: 'idle-eraser', type: 'Eraser', x: -7, z: 6, rot: 0.3 }], true);
      this.idleProps = true;
    }
    this.player.root.visible = true;
    this.player.place(0, 0, 0, 0.6, 0.25, 0, dt);
    this.smoke.update(dt, this.camera);
    const portrait = this.height > this.width;
    this.aim(0, 0, time * 0.25, portrait ? 45 : 24, portrait ? 0.9 : 0.5);
    this.updateProps(dt);
    return null;
  }

  /** Zettel, an dem das Auto gerade vorbeikommt (für die lesbare Karte in der Anzeige). */
  noteAhead() {
    if (!this.track) return null;
    for (const note of this.notes) {
      const d = this.track.delta(this.playerS, note.s);
      if (d > -25 && d < 120) return { ...noteFor(note.index, this.noteLap), index: note.index, lap: this.noteLap };
    }
    return null;
  }

  /** Wo das eigene Auto im Bild ist (Pixel der kleinen Auflösung), damit die Anzeige ihm ausweichen kann. */
  carOnScreen() {
    const v = this.vec.copy(this.player.root.position).project(this.camera);
    return { x: (v.x + 1) / 2 * this.width, y: (1 - v.y) / 2 * this.height };
  }

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  updateProps(dt) {
    this.camera.updateMatrixWorld();
    const protectedCars = [this.player, ...[...this.ghosts.values()].map((g) => g.car)].filter((c) => c.root.visible);
    for (const entry of this.propSlots) {
      // Hohe Gegenstände dürfen kein Auto verdecken: Abstand zur Sichtlinie in Weltkoordinaten.
      let hidden = false;
      if (entry.height > 3) {
        const centre = this.vec.setFromMatrixPosition(entry.base);
        const top = entry.height;
        for (const car of protectedCars) {
          const a = this.camera.position, b = car.root.position;
          const dx = b.x - a.x, dz = b.z - a.z;
          const t = ((centre.x - a.x) * dx + (centre.z - a.z) * dz) / (dx * dx + dz * dz || 1);
          const y = a.y + (b.y + 1 - a.y) * t;
          if (t > 0 && t < 1 && y < top + 1.5 && Math.hypot(centre.x - a.x - t * dx, centre.z - a.z - t * dz) < entry.radius + 2) hidden = true;
        }
      }
      const growth = Math.min(1, entry.growth + Math.max(0, dt) * 3);
      if (growth !== entry.growth || hidden !== entry.hidden) {
        entry.growth = growth; entry.hidden = hidden;
        this.matrix.copy(entry.base).scale(this.vec.setScalar(hidden ? 0 : growth));
        entry.mesh.setMatrixAt(entry.slot, this.matrix);
        entry.mesh.instanceMatrix.needsUpdate = true;
      }
    }
  }
}

// ── Text aus einer Bitmap-Schrift setzen (auch von der Anzeige benutzt) ───────────────────────────────

const tinted = new Map();

function tint(font, color) {
  const key = font.name + color;
  if (!tinted.has(key)) {
    const canvas = document.createElement('canvas');
    canvas.width = font.image.width; canvas.height = font.image.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(font.image, 0, 0);
    ctx.globalCompositeOperation = 'source-in';
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    tinted.set(key, canvas);
  }
  return tinted.get(key);
}

export function textWidth(font, text) {
  if (!font) return text.length * 6;
  let w = 0;
  for (const ch of text) w += (font.glyphs[ch] ?? font.glyphs['?'] ?? [0, 0, 0, 0, 0, 0, 6])[6];
  return w;
}

/**
 * Text zeichnen. Mit `width` wird an Wortgrenzen umbrochen.
 * @returns {number} Höhe des gesetzten Textes in Pixeln
 */
export function drawText(ctx, font, text, x, y, { color = '#ffffff', width = 0, align = 'left', lineHeight } = {}) {
  if (!font) {
    ctx.fillStyle = color;
    ctx.font = '8px monospace';
    ctx.textBaseline = 'top';
    ctx.fillText(text, x, y);
    return 10;
  }
  const lines = [];
  if (width > 0) {
    let line = '';
    for (const word of text.split(' ')) {
      const next = line ? line + ' ' + word : word;
      if (line && textWidth(font, next) > width) { lines.push(line); line = word; } else line = next;
    }
    lines.push(line);
  } else lines.push(text);
  const atlas = tint(font, color), lh = lineHeight ?? font.lineHeight;
  lines.forEach((line, row) => {
    let pen = x;
    if (align === 'center') pen = Math.round(x - textWidth(font, line) / 2);
    else if (align === 'right') pen = x - textWidth(font, line);
    for (const ch of line) {
      const g = font.glyphs[ch] ?? font.glyphs['?'];
      if (!g) continue;
      if (g[2] && g[3]) ctx.drawImage(atlas, g[0], g[1], g[2], g[3], pen + g[4], y + row * lh + g[5], g[2], g[3]);
      pen += g[6];
    }
  });
  return lines.length * lh;
}
