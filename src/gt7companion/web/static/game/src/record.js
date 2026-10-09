// Nimmt nur das Spielbild mit HUD auf. Keine Bedienleiste, kein Mikrofon.
// Canvas-Capture und MediaRecorder: https://www.w3.org/TR/mediastream-recording/
import { t } from './i18n.js';

const START = 'Aufnehmen';

export class GameRecorder {
  constructor({ image, hud, button, download, status, format, render }) {
    Object.assign(this, { image, hud, button, download, status, format, render });
    this.recorder = null;
    this.url = null;
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d', { alpha: false });
    if (!window.MediaRecorder || !this.canvas.captureStream) {
      button.disabled = true;
      button.title = 'Videoaufnahme in diesem Browser nicht unterstützt';
    }
    button.addEventListener('click', () => this.recorder ? this.stop() : this.start());
    window.addEventListener('beforeunload', (e) => {
      if (this.recorder) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  start() {
    if (this.recorder) return;
    this.canvas.width = this.image.width; this.canvas.height = this.image.height;
    this.ctx.imageSmoothingEnabled = false;
    this.status.textContent = '';
    const types = ['video/mp4;codecs=avc1.42E01E', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const mimeType = types.find((type) => MediaRecorder.isTypeSupported(type));
    let stream;
    try {
      if (!mimeType) throw new Error(t('Kein unterstütztes Videoformat'));
      // WebGL ohne preserveDrawingBuffer: direkt nach dem Rendern beide Ebenen zusammenführen.
      this.render();
      this.composite();
      stream = this.canvas.captureStream(60);
      const rec = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 8000000 });
      const chunks = [];
      this.recorder = rec;
      this.started = performance.now();
      this.format.disabled = true;
      this.button.setAttribute('aria-pressed', 'true');
      this.button.classList.add('recording');
      let failure = '';
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onerror = (e) => { failure = e.error?.message ?? t('Videoaufnahme fehlgeschlagen'); };
      rec.onstop = () => {
        const blob = new Blob(chunks, { type: rec.mimeType });
        stream.getTracks().forEach((track) => track.stop());
        this.recorder = null;
        this.button.disabled = false;
        this.button.textContent = START;
        this.button.classList.remove('recording');
        this.button.setAttribute('aria-pressed', 'false');
        this.format.disabled = false;
        if (blob.size) {
          if (this.url) URL.revokeObjectURL(this.url);
          this.url = URL.createObjectURL(blob);
          const extension = rec.mimeType.startsWith('video/mp4') ? 'mp4' : 'webm';
          const stamp = new Date().toISOString().replace(/[:.]/g, '-');
          this.download.href = this.url;
          this.download.download = `Tisch-Turismo_${this.canvas.width}x${this.canvas.height}_${stamp}.${extension}`;
          this.download.hidden = false;
          this.download.click();
        }
        this.status.textContent = failure || (blob.size ? 'Video bereit' : 'Keine Videodaten aufgenommen');
      };
      rec.start(1000);
      this.frame();
    } catch (e) {
      stream?.getTracks().forEach((track) => track.stop());
      this.recorder = null;
      this.format.disabled = false;
      this.button.classList.remove('recording');
      this.button.setAttribute('aria-pressed', 'false');
      this.button.textContent = START;
      this.status.textContent = t('Aufnahme nicht möglich: {grund}', { grund: e.message });
    }
  }

  stop() {
    if (!this.recorder || this.recorder.state === 'inactive') return;
    this.button.disabled = true;
    this.button.textContent = 'Speichern …';
    this.recorder.stop();
  }

  composite() {
    this.ctx.drawImage(this.image, 0, 0);
    this.ctx.drawImage(this.hud, 0, 0);
  }

  frame() {
    if (!this.recorder || this.recorder.state !== 'recording') return;
    this.composite();
    const seconds = Math.floor((performance.now() - this.started) / 1000);
    const label = `${t('Stopp')} ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (this.button.textContent !== label) this.button.textContent = label;
  }
}
