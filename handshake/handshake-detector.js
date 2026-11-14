// Tacit: handshake detection for two wristbands.
//
// The idea: in a handshake the two hands are joined, so both wrists make the same
// short up-and-down motion at the same moment. One person shaking a hand alone, or
// two people moving at the same time but not together, do not produce the same trace.
//
// So a handshake is: (1) both bands are "shaking" (a few quick swings, strong enough),
// and (2) the two motion traces match each other closely over the same second.
//
// This file is the logic only (no page, no Bluetooth). Feed it motion samples from
// each band and ask it for the state.

export const DEFAULTS = {
  windowMs: 1200,        // how much of the recent past is compared
  stepMs: 20,            // both traces are put on this common time grid (50 per second)
  minEnergy: 0.2,        // how strong the shake must be, in g (average swing size)
  minSwings: 4,          // at least two full up-and-downs...
  maxSwings: 16,         // ...and not a buzz
  minMatch: 0.6,         // how closely the two traces must agree (0 to 1)
  maxLagMs: 160,         // the traces may be this far apart in time (clocks, radio delay)
  cooldownMs: 3000,      // after a handshake, wait this long before the next one counts
};

/** The recent motion of one band: time and the size of its acceleration, in g. */
export class MotionTrace {
  constructor(keepMs = 4000) {
    this.keepMs = keepMs;
    this.samples = [];
  }

  /** time: milliseconds (same clock for both bands). ax, ay, az: acceleration in g. */
  push(time, ax, ay, az) {
    const size = Math.hypot(ax, ay, az);
    if (!Number.isFinite(size) || !Number.isFinite(time)) return;
    const list = this.samples;
    const at = list.length && time <= list[list.length - 1].time ? list[list.length - 1].time + 1 : time;
    list.push({ time: at, size });
    while (list.length && list[0].time < at - this.keepMs) list.shift();
  }

  get latest() {
    return this.samples.length ? this.samples[this.samples.length - 1].time : null;
  }

  /** The trace on a regular grid between two moments, or null when it does not cover them. */
  resample(from, to, stepMs) {
    const list = this.samples;
    if (list.length < 2 || list[0].time > from + 150 || list[list.length - 1].time < to - 150) return null;
    const values = [];
    let i = 0;
    for (let t = from; t <= to; t += stepMs) {
      while (i < list.length - 2 && list[i + 1].time < t) i += 1;
      const a = list[i];
      const b = list[i + 1];
      const span = b.time - a.time;
      const part = span > 0 ? Math.min(1, Math.max(0, (t - a.time) / span)) : 0;
      values.push(a.size + (b.size - a.size) * part);
    }
    return values;
  }
}

/** How a stretch of motion looks: its swings around the average, how strong, how many. */
export function describe(values) {
  const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
  const swing = values.map((v) => v - mean);
  const energy = Math.sqrt(swing.reduce((sum, v) => sum + v * v, 0) / swing.length);
  const band = Math.max(0.08, energy * 0.5);        // ignore small wobbles around the middle
  let swings = 0;
  let side = 0;
  for (const v of swing) {
    if (v > band && side !== 1) {
      if (side === -1) swings += 1;
      side = 1;
    } else if (v < -band && side !== -1) {
      if (side === 1) swings += 1;
      side = -1;
    }
  }
  return { energy, swings, swing };
}

/** How closely two swing traces agree (-1 to 1), allowing a small shift in time. */
export function match(a, b, maxLag) {
  let best = -1;
  let bestLag = 0;
  for (let lag = -maxLag; lag <= maxLag; lag += 1) {
    let ab = 0;
    let aa = 0;
    let bb = 0;
    for (let i = 0; i < a.length; i += 1) {
      const j = i + lag;
      if (j < 0 || j >= b.length) continue;
      ab += a[i] * b[j];
      aa += a[i] * a[i];
      bb += b[j] * b[j];
    }
    const r = aa > 0 && bb > 0 ? ab / Math.sqrt(aa * bb) : 0;
    if (r > best) {
      best = r;
      bestLag = lag;
    }
  }
  return { r: best, lag: bestLag };
}

export class HandshakeDetector {
  constructor(options = {}) {
    this.options = { ...DEFAULTS, ...options };
    this.a = new MotionTrace();
    this.b = new MotionTrace();
    this.lastHandshake = -Infinity;
    this.count = 0;
  }

  feedA(time, ax, ay, az) { this.a.push(time, ax, ay, az); }
  feedB(time, ax, ay, az) { this.b.push(time, ax, ay, az); }

  /**
   * Look at the last moment both bands have data for. Returns what each band is doing,
   * how well they match, and `handshake: true` at the moment one is recognised.
   */
  check() {
    const o = this.options;
    const idle = { ready: false, a: null, b: null, match: 0, lagMs: 0, handshake: false, count: this.count };
    if (this.a.latest === null || this.b.latest === null) return idle;
    const to = Math.min(this.a.latest, this.b.latest);
    const from = to - o.windowMs;
    const va = this.a.resample(from, to, o.stepMs);
    const vb = this.b.resample(from, to, o.stepMs);
    if (!va || !vb) return idle;
    const da = describe(va);
    const db = describe(vb);
    const shaking = (d) => d.energy >= o.minEnergy && d.swings >= o.minSwings && d.swings <= o.maxSwings;
    const a = { energy: da.energy, swings: da.swings, shaking: shaking(da) };
    const b = { energy: db.energy, swings: db.swings, shaking: shaking(db) };
    const found = match(da.swing, db.swing, Math.round(o.maxLagMs / o.stepMs));
    const together = a.shaking && b.shaking && found.r >= o.minMatch;
    const handshake = together && to - this.lastHandshake >= o.cooldownMs;
    if (handshake) {
      this.lastHandshake = to;
      this.count += 1;
    }
    return { ready: true, a, b, match: found.r, lagMs: found.lag * o.stepMs, handshake, count: this.count, at: to };
  }
}
