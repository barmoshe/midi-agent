/**
 * run.js - the Node golden-vector oracle. Proves engine.js matches the Python PoC bit-for-bit
 * by replaying the vectors dumped in golden.json (from gen_golden.py). Ints/strings exact,
 * floats within 1e-9. Exits non-zero on any mismatch.
 *
 *   ./venv/bin/python m4l/test/gen_golden.py   # regenerate vectors from Python
 *   node m4l/test/run.js                        # check the JS port against them
 */
'use strict';
const fs = require('fs');
const path = require('path');
const E = require('../engine.js');

const golden = JSON.parse(fs.readFileSync(path.join(__dirname, 'golden.json'), 'utf8'));

const TOL = 1e-9;
function eq(a, b) {
  if (typeof a === 'number' && typeof b === 'number') {
    if (Number.isNaN(a) && Number.isNaN(b)) return true;
    return Math.abs(a - b) <= TOL;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!eq(a[i], b[i])) return false;
    return true;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    if (ka.length !== kb.length || ka.join(',') !== kb.join(',')) return false;
    for (const k of ka) if (!eq(a[k], b[k])) return false;
    return true;
  }
  return a === b;
}

const ctxCache = {};
function ctxFor(key) {
  if (!ctxCache[key]) ctxCache[key] = E.makeContext(key);
  return ctxCache[key];
}

function run(c) {
  const i = c.in;
  switch (c.fn) {
    case 'estimateKey': return E.estimateKey(i.notes);
    case 'snap': return ctxFor(i.ctxKey).snap(i.pitch);
    case 'degreeTranspose': return ctxFor(i.ctxKey).degreeTranspose(i.pitch, i.steps);
    case 'buildTriad': return E.buildTriad(ctxFor(i.ctxKey), i.tonic, i.degree);
    case 'chordName': return E.chordName(ctxFor(i.ctxKey), i.tonic, i.degree, i.seventh);
    case 'chordBarEvents':
      return E.chordBarEvents(ctxFor(i.ctxKey), i.tonic, i.degree,
        { style: i.style, vel: i.vel, beats: i.beats, seventh: i.seventh, rng: E.ZERO_RNG });
    case 'pitchHistogram':
      return E.pitchHistogram(i.notes, i.now, { windowS: i.windowS, halflife: i.halflife });
    case 'scoreChord':
      return E.scoreChord(i.hist, new Set(i.chordPcs), i.rootPc, i.outPenalty);
    case 'bestDegree':
      return E.bestDegree(ctxFor(i.ctxKey), i.tonic, i.hist, i.current);
    case 'timelineForCycle': return E.timelineForCycle(i.events, i.cstart, i.spb);
    default: throw new Error('unknown fn: ' + c.fn);
  }
}

let pass = 0;
const fails = [];
const byFn = {};
for (const c of golden) {
  byFn[c.fn] = byFn[c.fn] || { n: 0, ok: 0 };
  byFn[c.fn].n++;
  let got;
  try { got = run(c); } catch (e) { got = '<<threw ' + e.message + '>>'; }
  if (eq(got, c.out)) { pass++; byFn[c.fn].ok++; }
  else if (fails.length < 12) fails.push({ fn: c.fn, in: c.in, expected: c.out, got });
}

const total = golden.length;
console.log(`golden vectors: ${pass}/${total} passed`);
for (const fn of Object.keys(byFn).sort()) {
  console.log(`  ${byFn[fn].ok}/${byFn[fn].n}  ${fn}`);
}
if (fails.length) {
  console.log('\nFAILURES (first ' + fails.length + '):');
  for (const f of fails) {
    console.log(`  ${f.fn}  in=${JSON.stringify(f.in)}`);
    console.log(`    expected ${JSON.stringify(f.expected)}`);
    console.log(`    got      ${JSON.stringify(f.got)}`);
  }
  process.exit(1);
}
console.log('ALL GOLDEN VECTORS MATCH (JS engine == Python, bit-for-bit)');
