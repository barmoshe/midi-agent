/**
 * engine.js - the midi-agent follow-along harmony engine, ported 1:1 from the Python PoC
 * (theory.py + follow.py harmony core + backing.py primitives). Pure: no Max, no Node, no I/O.
 * Runs identically in Node (for the golden-vector oracle) and in Max v8 (the .amxd device).
 *
 * Parity rule: this is a faithful port. The Node oracle (test/run.js) proves it matches the
 * Python bit-for-bit (ints exact, floats <= 1e-9) against vectors dumped from the real Python
 * functions (test/gen_golden.py). Do not "improve" the math here without regenerating vectors.
 *
 * The one deliberate divergence: chord_bar_events velocity humanization uses an injectable rng
 * (Python's RNG is not reproducible in JS). Pass a zero-rng for deterministic output (golden
 * vectors do this); the live device passes a JS rng for cosmetic jitter.
 */

// Python's % is floor-mod (so -1 % 12 === 11); JS % is truncated. Use this for all pitch-class math.
function pc(n) {
  return ((n % 12) + 12) % 12;
}
function clamp(p) {
  return Math.max(0, Math.min(127, p));
}
function clampVel(v) {
  return Math.max(1, Math.min(127, Math.trunc(v)));
}

// --- Krumhansl-Schmuckler key profiles + diatonic steps (theory.py:15-19) ---
const KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88];
const KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17];
const MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11];
const MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10]; // natural minor

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const NAME_TO_PC = {
  C: 0, 'C#': 1, DB: 1, D: 2, 'D#': 3, EB: 3, E: 4, F: 5,
  'F#': 6, GB: 6, G: 7, 'G#': 8, AB: 8, A: 9, 'A#': 10, BB: 10, B: 11,
};

// --- theory.py ---
function pearson(a, b) {
  const n = a.length;
  let ma = 0, mb = 0;
  for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
  ma /= n; mb /= n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) {
    num += (a[i] - ma) * (b[i] - mb);
    da += (a[i] - ma) ** 2;
    db += (b[i] - mb) ** 2;
  }
  da = Math.sqrt(da); db = Math.sqrt(db);
  if (da === 0 || db === 0) return 0.0;
  return num / (da * db);
}

/** notes: array of {pitch, start, end}. Returns [rootPc, mode, confidence]. (theory.py:37-52) */
function estimateKey(notes) {
  const hist = new Array(12).fill(0);
  for (const n of notes) hist[pc(n.pitch)] += (n.end - n.start);
  if (hist.reduce((s, x) => s + x, 0) === 0) return [0, 'major', 0.0];
  let best = null;
  for (let root = 0; root < 12; root++) {
    const rot = [];
    for (let i = 0; i < 12; i++) rot.push(hist[pc(root + i)]);
    for (const [mode, profile] of [['major', KS_MAJOR], ['minor', KS_MINOR]]) {
      const c = pearson(rot, profile);
      if (best === null || c > best[2]) best = [root, mode, c];
    }
  }
  return [best[0], best[1], Math.max(0.0, best[2])];
}

function scaleFor(root, mode) {
  const steps = mode === 'major' ? MAJOR_STEPS : MINOR_STEPS;
  return new Set(steps.map((s) => pc(root + s)));
}

function parseKeyLock(spec) {
  const idx = spec.indexOf(':');
  const name = (idx >= 0 ? spec.slice(0, idx) : spec).trim().toUpperCase();
  let mode = (idx >= 0 ? spec.slice(idx + 1) : '').trim().toLowerCase() || 'major';
  const root = NAME_TO_PC[name];
  if (root === undefined) throw new Error('unknown key root: ' + name);
  if (mode !== 'major' && mode !== 'minor') throw new Error('unknown mode: ' + mode);
  return [root, mode];
}

function snap(pitch, scale) {
  if (scale.has(pc(pitch))) return clamp(pitch);
  for (const d of [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6]) {
    if (scale.has(pc(pitch + d))) return clamp(pitch + d);
  }
  return clamp(pitch);
}

function degreeTranspose(pitch, steps, scale) {
  let cur = snap(pitch, scale);
  if (steps === 0) return cur;
  const direction = steps > 0 ? 1 : -1;
  let remaining = Math.abs(steps);
  while (remaining > 0) {
    cur += direction;
    let guard = 0;
    while (!scale.has(pc(cur)) && cur >= 0 && cur <= 127 && guard < 12) {
      cur += direction;
      guard += 1;
    }
    remaining -= 1;
    if (!(cur >= 0 && cur <= 127)) break;
  }
  return clamp(cur);
}

/** A MusicalContext analog: {root, mode, scale, snap(p), degreeTranspose(p, steps)}. */
function makeContext(key) {
  const [root, mode] = parseKeyLock(key);
  const scale = scaleFor(root, mode);
  return {
    root, mode, scale,
    snap: (p) => snap(p, scale),
    degreeTranspose: (p, steps) => degreeTranspose(p, steps, scale),
  };
}

// --- backing.py primitives ---
function buildTriad(ctx, tonicPitch, degree) {
  const root = ctx.degreeTranspose(tonicPitch, degree - 1);
  return [root, ctx.degreeTranspose(root, 2), ctx.degreeTranspose(root, 4)];
}

/** events: [[onset, dur, pitch, vel], ...] -> sorted [[absTime, kind(1 on/0 off), pitch, vel], ...] */
function timelineForCycle(events, cstart, spb) {
  const tl = [];
  for (const [onset, dur, pitch, vel] of events) {
    tl.push([cstart + onset * spb, 1, pitch, vel]);
    tl.push([cstart + (onset + dur) * spb, 0, pitch, 0]);
  }
  tl.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
  return tl;
}

// --- follow.py harmony core ---
/** notes: array of [pitch, t]. Returns {pcStr: weight}. (follow.py:41-50) */
function pitchHistogram(notes, now, opts = {}) {
  const windowS = opts.windowS ?? 2.5;
  const halflife = opts.halflife ?? 1.2;
  const hist = {};
  for (const [pitch, t] of notes) {
    const age = now - t;
    if (age > windowS || age < 0) continue;
    const k = pc(pitch);
    hist[k] = (hist[k] || 0) + Math.pow(0.5, age / halflife);
  }
  return hist;
}

function scoreChord(hist, chordPcs, rootPc, outPenalty = 0.5) {
  let s = 0.0;
  for (const key of Object.keys(hist)) {
    const p = +key;
    const w = hist[key];
    if (p === rootPc) s += w;
    else if (chordPcs.has(p)) s += 0.8 * w;
    else s -= outPenalty * w;
  }
  return s;
}

/** Pick the diatonic degree (1..7) best fitting hist, with hold-bias hysteresis. (follow.py:67-83) */
function bestDegree(ctx, tonicPitch, hist, currentDegree, opts = {}) {
  const holdBonus = opts.holdBonus ?? 0.2;
  const switchMargin = opts.switchMargin ?? 0.15;
  const scores = {};
  for (let d = 1; d < 8; d++) {
    const triad = buildTriad(ctx, tonicPitch, d);
    const pcs = new Set(triad.map((p) => pc(p)));
    scores[d] = scoreChord(hist, pcs, pc(triad[0]));
  }
  if (currentDegree in scores) scores[currentDegree] += holdBonus;
  // Python max(scores, key=...) returns the FIRST max -> iterate 1..7, strict >.
  let best = 1;
  for (let d = 2; d < 8; d++) if (scores[d] > scores[best]) best = d;
  if (currentDegree && best !== currentDegree) {
    const cur = (currentDegree in scores) ? scores[currentDegree] : -Infinity;
    if (scores[best] - cur < switchMargin) return currentDegree;
  }
  return best;
}

function chordName(ctx, tonicPitch, degree, seventh = false) {
  const triad = buildTriad(ctx, tonicPitch, degree);
  const [root, third, fifth] = triad;
  const thirdIv = pc(third - root);
  const fifthIv = pc(fifth - root);
  let quality;
  if (thirdIv === 4 && fifthIv === 8) quality = 'aug';
  else if (thirdIv === 3 && fifthIv === 6) quality = 'dim';
  else if (thirdIv === 3) quality = 'm';
  else quality = '';
  return NOTE_NAMES[pc(root)] + quality + (seventh ? '7' : '');
}

const ZERO_RNG = { randint: () => 0 };

/** One bar of comp as [[onset, dur, pitch, vel], ...]. opts.rng.randint(a,b) for vel jitter. */
function chordBarEvents(ctx, tonicPitch, degree, opts = {}) {
  const style = opts.style ?? 'pulse';
  const vel = opts.vel ?? 74;
  const rng = opts.rng ?? ZERO_RNG;
  const beats = opts.beats ?? 4;
  const seventh = opts.seventh ?? false;
  const triad = buildTriad(ctx, tonicPitch, degree);
  const chord = seventh ? triad.concat([ctx.degreeTranspose(triad[0], 6)]) : triad.slice();
  const bass = Math.max(0, triad[0] - 12);
  const events = [];
  if (style === 'pads') {
    for (const p of chord) events.push([0.0, beats, p, clampVel(vel)]);
    events.push([0.0, beats, bass, clampVel(vel + 10)]);
  } else { // pulse
    for (let b = 0; b < beats; b++) {
      const accent = b === 0 ? 12 : (b % 2 ? -7 : 0);
      for (const p of chord) events.push([b, 0.9, p, clampVel(vel + accent + rng.randint(-3, 3))]);
      if (b % 2 === 0) events.push([b, 1.9, bass, clampVel(vel + 10)]);
    }
  }
  return events;
}

module.exports = {
  pc, clamp, clampVel,
  KS_MAJOR, KS_MINOR, MAJOR_STEPS, MINOR_STEPS, NOTE_NAMES,
  pearson, estimateKey, scaleFor, parseKeyLock, snap, degreeTranspose, makeContext,
  buildTriad, timelineForCycle,
  pitchHistogram, scoreChord, bestDegree, chordName, chordBarEvents, ZERO_RNG,
};
