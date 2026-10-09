/* Undo snapshots; one continuous drag or held arrow key is one edit. */
export class History {
  constructor() { this.current = null; this.past = []; this.group = false; this.groupRecorded = false; }
  begin() { this.group = true; this.groupRecorded = false; }
  end() { this.group = false; }
  remember(layout) {
    const value = JSON.stringify(layout);
    if (value === this.current) return;
    if (this.current !== null && (!this.group || !this.groupRecorded)) {
      this.past.push(this.current);
      if (this.past.length > 100) this.past.shift();
    }
    this.current = value;
    if (this.group) this.groupRecorded = true;
  }
  undo() {
    this.end();
    if (!this.past.length) return null;
    this.current = this.past.pop();
    return JSON.parse(this.current);
  }
}
