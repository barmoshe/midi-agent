/**
 * sim_device.js - exercise device.js OUTSIDE Max by stubbing the Max v8 globals (outlet, Task,
 * post, require). Proves the note -> bar-tick -> MIDI-emit + chord-readout flow works and that
 * the device follows the soloist, without needing Max. Not a parity oracle (that's run.js); a
 * smoke test for the glue. Run: node m4l/test/sim_device.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const E = require('../engine.js');

const emitted = []; // [outletIndex, ...args]
const queue = []; // {delay, fn} - scheduled Tasks, fired on demand so we can inspect mid-bar state
function flush(maxMs) {
  const due = [];
  for (let i = queue.length - 1; i >= 0; i--) {
    if (queue[i].delay <= maxMs) { due.unshift(queue[i]); queue.splice(i, 1); }
  }
  due.sort((a, b) => a.delay - b.delay).forEach((t) => t.fn());
}
const sandbox = {
  autowatch: 0, inlets: 0, outlets: 0,
  outlet: function () { emitted.push(Array.prototype.slice.call(arguments)); },
  post: function () {},
  require: function (name) { return name.indexOf('engine') >= 0 ? E : require(name); },
  Task: function (fn, obj) {
    const args = Array.prototype.slice.call(arguments, 2);
    this.schedule = function (ms) { queue.push({ delay: ms, fn: function () { fn.apply(obj, args); } }); };
  },
  Date: Date, Math: Math, Object: Object, parseInt: parseInt, String: String,
};

const code = fs.readFileSync(path.join(__dirname, '..', 'device.js'), 'utf8');
const expose = ';return { note: note, bang: bang, key: key, feel: feel, sevenths: sevenths, ' +
  'velocity: velocity, rate: rate, panic: panic };';
const factory = new Function(...Object.keys(sandbox), code + expose);
const dev = factory(...Object.values(sandbox));

function notesFrom(outletDump) {
  // outlet 0 = [0, pitch, vel]; collect note-ONs (vel>0)
  return outletDump.filter((e) => e[0] === 0 && e[2] > 0).map((e) => e[1]);
}
function chordReadout(outletDump) {
  const c = outletDump.filter((e) => e[0] === 1 && e[1] === 'chord').pop();
  return c ? c[2] : null;
}

let failures = 0;
function check(name, cond) {
  console.log((cond ? 'ok   ' : 'FAIL ') + name);
  if (!cond) failures++;
}

// Pin C major, play a C-E-G emphasis, tick a bar -> expect a C chord comped out.
dev.key('C:major');
dev.feel('pulse');
[60, 64, 67, 72].forEach((p) => dev.note(p, 100));
emitted.length = 0;
dev.bang();
flush(Infinity); // fire all scheduled note on/off tasks
let pitches = notesFrom(emitted);
check('C-E-G solo -> chord readout is C', chordReadout(emitted) === 'C');
check('emits a comp (>=4 notes)', pitches.length >= 4);
check('all emitted notes are in C major', pitches.every((p) => E.makeContext('C:major').scale.has(((p % 12) + 12) % 12)));

// Now emphasize F-A-C -> chord should move to F.
[65, 69, 72, 77].forEach((p) => dev.note(p, 100));
emitted.length = 0;
dev.bang();
flush(Infinity);
check('F-A-C solo -> chord readout moves to F', chordReadout(emitted) === 'F');

// panic flushes sounding notes: tick a bar, fire only the downbeat note-ONs (delay ~0), so the
// chord is still sounding, then panic -> it must emit note-offs.
emitted.length = 0;
dev.bang();
flush(50); // only the beat-0 note-ons fire (offs are scheduled hundreds of ms later)
const onCount = emitted.filter((e) => e[0] === 0 && e[2] > 0).length;
emitted.length = 0;
dev.panic();
check('panic emits note-offs (vel 0) for sounding notes',
  onCount > 0 && emitted.some((e) => e[0] === 0 && e[2] === 0));

console.log(failures === 0 ? '\nDEVICE SIM OK' : '\nDEVICE SIM FAILED (' + failures + ')');
process.exit(failures === 0 ? 0 : 1);
