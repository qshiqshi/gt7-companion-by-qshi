// Anzeige über dem Spielbild: Lichterbalken wie im Vorbild, Cr., Rundenzeiten, Einblendungen, Zettel, Titel.
// Gezeichnet wird in der kleinen Auflösung auf ein zweites Canvas, das genau über dem Spielbild liegt.

import { drawText, textWidth, COLORS } from './view.js';
import { t, lang } from '../i18n.js';

const hex = (v) => '#' + v.toString(16).padStart(6, '0');
const CAR_COLORS = { player: hex(COLORS.player), best: hex(COLORS.best), last: hex(COLORS.last) };
const LABELS = { player: 'DU', best: 'BESTE', last: 'LETZTE' };
// Ganze Sätze je Gegner, damit sie sich übersetzen lassen.
const PULLS_AWAY = { best: 'BESTE RUNDE ZIEHT WEG', last: 'LETZTE RUNDE ZIEHT WEG' };
const MATCH_LOST = { best: 'PARTIE AN DIE BESTE RUNDE', last: 'PARTIE AN DIE LETZTE RUNDE' };
const THOUSANDS = lang === 'en' ? ',' : '.';

export function lapTime(ms) {
  const m = Math.floor(ms / 60000), s = (ms % 60000) / 1000;
  return `${m}:${s.toFixed(3).padStart(6, '0')}`;
}

export function credits(value) {
  return Math.round(value).toString().replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS);
}

export class Hud {
  constructor(canvas, assets, { width = 640, height = 480 } = {}) {
    this.canvas = canvas;
    this.assets = assets;
    this.resize(width, height);
    this.reset();
  }

  resize(width, height) {
    this.width = width / 2; this.height = height / 2;
    this.portrait = height > width;
    this.canvas.width = width; this.canvas.height = height;
    this.ctx = this.canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;
    this.ctx.setTransform(2, 0, 0, 2, 0, 0);
    if (this.note) { delete this.note.h; delete this.note.top; }
  }

  reset() {
    this.lights = { player: 0 };        // id → Anzahl
    this.ghostIds = [];
    this.credits = 0;
    this.shownCredits = 0;
    this.lastLap = null;
    this.bestLap = null;
    this.banner = null;                 // { text, color, until }
    this.popups = [];                   // { text, color, born }
    this.note = null;                   // { text, index, since }
    this.noteSeen = -1;
    this.flash = {};                    // id → Zeitpunkt des letzten Lichts
  }

  // ── Ereignisse ────────────────────────────────────────────────────────────────────────────────────

  handle(e, time, instant = false) {
    switch (e.type) {
      case 'reset': this.reset(); break;
      case 'ghosts':
        this.ghostIds = e.ghosts.map((g) => g.id);
        this.lights = { player: e.playerLights };
        for (const g of e.ghosts) this.lights[g.id] = g.lights;
        if (e.newMatch && !instant) this.say(t('NEUE PARTIE'), '#ffffff', time, 2);
        break;
      case 'point':
        this.lights.player = e.playerLights;
        this.lights[e.ghost] = e.ghostLights;
        this.credits = e.credits;
        if (!instant) {
          this.flash[e.winner] = time;
          if (e.winner === 'player') this.say(t('ABGEHÄNGT!'), '#7dff8a', time, 1.8);
          else this.say(t(PULLS_AWAY[e.winner]), '#ff6a5e', time, 1.8);
        }
        break;
      case 'match':
        this.credits = e.credits;
        if (!instant) {
          this.say(t(e.winner === 'player' ? 'PARTIE GEWONNEN!' : MATCH_LOST[e.winner]),
            e.winner === 'player' ? '#ffe04a' : '#ff6a5e', time, 5);
        }
        break;
      case 'coin': case 'oil':
        this.credits = e.credits;
        if (!instant) {
          this.popups.push({ text: e.type === 'coin' ? `+${credits(e.value)}` : t('ÖL! {n}', { n: credits(e.value) }),
            color: e.type === 'coin' ? '#ffe04a' : '#c9a2ff', born: time });
          if (e.item.by) this.say(t(e.type === 'coin' ? 'MÜNZE VON {name}' : 'ÖL VON {name}', { name: viewer(e.item.by) }),
            '#ffffff', time, 2.2);
        }
        break;
      case 'drift':
        this.credits = e.credits;
        if (!instant) {
          this.say(`DRIFT ${e.degrees}°`, '#ff9a3c', time, 1.8);
          this.popups.push({ text: `+${credits(e.value)}`, color: '#ff9a3c', born: time });
        }
        break;
      case 'drop':
        if (!instant) this.say(t(e.item.kind === 'oil' ? '{name} WIRFT ÖL' : '{name} WIRFT EINE MÜNZE', { name: viewer(e.item.by) }),
          '#ffffff', time, 2.5);
        break;
      case 'lap':
        this.lastLap = e.timeMs;
        if (e.best) this.bestLap = e.timeMs;
        if (e.best && !instant && this.ghostIds.length) this.say(t('NEUE BESTZEIT'), '#7dd0ff', time, 2.5);
        break;
      case 'track':
        if (!instant && e.how === 'neu') this.say(t('STRECKE STEHT – LOS!'), '#ffe04a', time, 3);
        if (!instant && e.how === 'wieder') this.say(t('GLEICHE STRECKE – WEITER'), '#ffe04a', time, 2.5);
        break;
      default: break;
    }
  }

  say(text, color, time, seconds) {
    this.banner = { text, color, until: time + seconds, since: time };
  }

  // ── Zeichnen ──────────────────────────────────────────────────────────────────────────────────────

  text(text, x, y, opts) {
    return drawText(this.ctx, this.assets.fonts.hud, text, x, y, opts);
  }

  /** Text mit dunklem Rand, damit er auf jedem Untergrund lesbar bleibt. */
  outlined(text, x, y, color, align = 'left') {
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1]]) this.text(text, x + dx, y + dy, { color: '#120a08', align });
    this.text(text, x, y, { color, align });
  }

  /** Text in Zeilen brechen, die in `width` passen. */
  wrap(text, width = this.width - 16) {
    const font = this.assets.fonts.hud;
    const lines = [];
    let line = '';
    for (const word of text.split(' ')) {
      if (line && textWidth(font, line + ' ' + word) > width) { lines.push(line); line = ''; }
      line += (line ? ' ' : '') + word;
    }
    if (line) lines.push(line);
    return lines;
  }

  wrapped(text, x, y, color, width) {
    const lines = this.wrap(text, width);
    lines.forEach((s, i) => this.outlined(s, x, y + i * 11, color, 'center'));
    return lines.length * 11;
  }

  /**
   * @param {object} s
   * @param {string} s.phase 'titel' | 'warten' | 'vermessen' | 'rennen'
   * @param {string} [s.status] kurze Meldung (Quelle, Aufzeichnung zu Ende …)
   * @param {number} [s.driven] gefahrene Meter beim Vermessen
   * @param {object|null} [s.note] Zettel, an dem das Auto gerade vorbeikommt
   * @param {{x:number,y:number}} [s.car] Ort des eigenen Autos im Bild
   */
  draw(s, time) {
    const { ctx, width: W, height: H } = this;
    ctx.clearRect(0, 0, W, H);
    if (s.phase === 'titel') return this.title(s, time);

    // Cr. oben rechts, zählt hoch
    this.shownCredits += (this.credits - this.shownCredits) * 0.2;
    if (Math.abs(this.credits - this.shownCredits) < 1) this.shownCredits = this.credits;
    this.outlined(`Cr. ${credits(this.shownCredits)}`, W - 6, 6, '#ffe04a', 'right');

    // Rundenzeiten oben links
    if (this.lastLap) this.outlined(lapTime(this.lastLap), 6, 6, '#ffffff');
    if (this.bestLap) this.outlined(`${this.portrait ? 'B' : 'BEST'} ${lapTime(this.bestLap)}`, 6, 17, '#7dd0ff');

    if (s.phase === 'vermessen') {
      const dots = '.'.repeat(1 + Math.floor(time * 2) % 3);
      this.wrapped(t('STRECKE WIRD VERMESSEN') + dots, W / 2, H - 45, '#ffffff');
      this.outlined(t('{n} m KREIDE', { n: credits(s.driven ?? 0) }), W / 2, H - 22, '#ffe04a', 'center');
    } else if (s.phase === 'rennen') {
      this.lightBars(time);
    }
    if (s.status) this.wrapped(s.status, W / 2, H - (this.portrait && s.phase === 'rennen' ? 48 : 12), '#ffffff');

    // Einblendung in der Mitte oben
    if (this.banner && time < this.banner.until) {
      const age = time - this.banner.since;
      if (age > 0.12 || Math.floor(time * 20) % 2) this.wrapped(this.banner.text, W / 2, 38, this.banner.color);
    }
    // aufsteigende Zahlen
    this.popups = this.popups.filter((p) => time - p.born < 1.1);
    this.popups.forEach((p, i) => {
      const k = (time - p.born) / 1.1;
      this.outlined(p.text, W / 2, Math.round(H / 2 - 30 - k * 22 - i * 9), p.color, 'center');
    });

    this.noteCard(s.note, time, s.car ? { x: s.car.x / 2, y: s.car.y / 2 } : null, s.status ? 64 : 50);
    return null;
  }

  /** Lichterbalken unten links: acht Lichter je Auto, wie im Vorbild. */
  lightBars(time) {
    const { ctx, height: H } = this;
    const ids = ['player', ...this.ghostIds];
    const on = this.assets.images.light_on, off = this.assets.images.light_off;
    ids.forEach((id, row) => {
      const y = H - 12 - (ids.length - 1 - row) * 10;
      ctx.fillStyle = '#120a08';
      ctx.fillRect(5, y - 1, 9, 9);
      ctx.fillStyle = CAR_COLORS[id];
      ctx.fillRect(6, y, 7, 7);
      const lit = this.lights[id] ?? 0;
      const flashing = time - (this.flash[id] ?? -9) < 0.8 && Math.floor(time * 10) % 2 === 0;
      for (let i = 0; i < 8; i++) {
        const x = 17 + i * 9;
        const isOn = i < lit && !(flashing && i === lit - 1);
        if (on && off) {
          ctx.drawImage(isOn ? on : off, x, y - 1);
          if (isOn) {
            ctx.globalCompositeOperation = 'source-atop';
            ctx.globalAlpha = 0.55;
            ctx.fillStyle = CAR_COLORS[id];
            ctx.fillRect(x, y - 1, 8, 8);
            ctx.globalAlpha = 1;
            ctx.globalCompositeOperation = 'source-over';
          }
        } else {
          ctx.fillStyle = '#120a08';
          ctx.fillRect(x, y - 1, 8, 8);
          ctx.fillStyle = isOn ? CAR_COLORS[id] : '#4a3a34';
          ctx.fillRect(x + 1, y, 6, 6);
        }
      }
      this.outlined(t(LABELS[id]), 92, y, CAR_COLORS[id]);
    });
  }

  /** Lesbarer Zettel: schiebt sich von rechts unten ins Bild, solange das Auto am Zettel vorbeifährt. */
  noteCard(note, time, car, bottomSpace = 50) {
    // Jeder Zettel kommt je Vorbeifahrt einmal ins Bild.
    if (!note) this.noteSeen = -1;
    else if (note.index !== this.noteSeen) {
      this.note = { ...note, since: time };
      this.noteSeen = note.index;
    }
    const card = this.note;
    if (!card) return;
    const age = time - card.since;
    const life = this.portrait ? 5 : 6.5;
    if (age > life) { this.note = null; return; }
    const { ctx, width: W, height: H } = this;
    // Die Karte ist nur so hoch wie ihr Text: Kurze Zettel verdecken weniger vom Bild.
    const hand = this.assets.fonts.hand;
    const w = this.portrait ? W - 20 : 168;
    if (card.h === undefined) {
      const probe = document.createElement('canvas').getContext('2d');
      card.h = drawText(probe, hand, card.text, 0, 0, { width: w - 20 }) + 12;
    }
    const h = card.h;
    const slide = age < 0.35 ? 1 - age / 0.35 : age > life - 0.35 ? (age - (life - 0.35)) / 0.35 : 0;
    // Unten rechts – außer das Auto ist gerade dort: dann oben rechts. Einmal gewählt, bleibt die Karte dort.
    if (card.top === undefined) {
      card.top = !!car && car.x > W - w - 26 && car.y > H - h - 30;
    }
    const x = Math.round(W - w - (this.portrait ? 10 : 6) + slide * (w + 10));
    const y = this.portrait ? H - h - bottomSpace : card.top ? 18 : H - h - 6;
    if (this.portrait && car && car.y > y - 10 && car.y < y + h + 10) return;
    const paper = this.assets.images.paper;
    ctx.fillStyle = '#120a08';
    ctx.fillRect(x + 2, y + 2, w, h);
    if (paper) {
      // Der rote Rand des Papiers gehört nur an die linke Kante: weiter rechts ohne die ersten Spalten kacheln.
      const skip = 14;
      for (let py = 0; py < h; py += paper.height) {
        const ph = Math.min(paper.height, h - py);
        ctx.drawImage(paper, 0, 0, Math.min(paper.width, w), ph, x, y + py, Math.min(paper.width, w), ph);
        for (let px = paper.width; px < w; px += paper.width - skip) {
          const pw = Math.min(paper.width - skip, w - px);
          ctx.drawImage(paper, skip, 0, pw, ph, x + px, y + py, pw, ph);
        }
      }
    } else {
      ctx.fillStyle = '#f4f1e4';
      ctx.fillRect(x, y, w, h);
    }
    drawText(ctx, hand, card.text, x + 12, y + 5, { width: w - 20, color: '#1c2f8a' });
  }

  /** Startbild: eigener Schriftzug, darunter blinkt die Aufforderung. */
  title(s, time) {
    const { ctx, width: W, height: H } = this;
    const logo = this.assets.images.titel;
    if (logo) {
      const scale = Math.min(1, (W - 16) / logo.width);
      ctx.drawImage(logo, Math.round((W - logo.width * scale) / 2), this.portrait ? 44 : 14,
        Math.round(logo.width * scale), Math.round(logo.height * scale));
    }
    else this.outlined('TISCH TURISMO', W / 2, 40, '#ffe04a', 'center');
    // Von unten nach oben: Hinweis, Aufforderung, blinkende Meldung. Bricht ein Text um, rückt alles darüber höher.
    const hint = s.hint ? this.wrap(s.hint) : [];
    const prompt = this.wrap(t('EINE RUNDE FAHREN – DANN GEHT ES LOS'));
    const hintTop = H - 14 - (Math.max(hint.length, 1) - 1) * 11;
    const promptTop = hintTop - 7 - prompt.length * 11;
    hint.forEach((line, i) => this.outlined(line, W / 2, hintTop + i * 11, '#b9a79c', 'center'));
    prompt.forEach((line, i) => this.outlined(line, W / 2, promptTop + i * 11, '#ffe04a', 'center'));
    const status = this.wrap(s.status ?? t('WARTE AUF DIE PS5'));
    if (Math.floor(time * 1.6) % 2 === 0) {
      status.forEach((line, i) => this.outlined(line, W / 2, promptTop - 3 - (status.length - i) * 11, '#ffffff', 'center'));
    }
    return null;
  }
}

/** Name eines Zuschauers, wie er in die Anzeige passt. */
function viewer(name) {
  return String(name).toUpperCase().slice(0, 16);
}

export { textWidth };
