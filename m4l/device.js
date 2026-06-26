/**
 * device.js - the Max v8 object for the "MIDI Follow" Max for Live device.
 *
 * This is GLUE only: all the music is in engine.js (proven bit-for-bit vs the Python PoC by
 * test/run.js). device.js owns MIDI I/O, the transport-driven bar decision, note scheduling,
 * the in-code echo gate, and the UI params/readout.
 *
 * Patch wiring (see BUILD.md):
 *   inlet 0  <- control messages: `note <pitch> <vel>` (from midiparse), `bang` (a transport-
 *              synced bar tick), `tempo <bpm>`, `key <auto|C:major|...>`, `feel <pulse|pads>`,
 *              `rate <bars>`, `sevenths <0|1>`, `velocity <n>`, `panic`.
 *   outlet 0 -> MIDI note as a 2-int list [pitch, velocity] (velocity 0 = note off);
 *              wire to `midiformat` -> `midiout`.
 *   outlet 1 -> status: `key <name>` and `chord <name>` for the UI readout.
 *
 * Feedback note: inline M4L routing means the device only ever reads its own track's input, so
 * it cannot hear its own output - the feedback trap is structurally gone. The recentEmit gate
 * below is belt-and-suspenders (the in-process analog of follow.py's 150ms echo-guard).
 */

autowatch = 1;
inlets = 1;
outlets = 2;

var E = require('engine.js'); // engine.js must be on Max's file search path (same folder)

// --- tunable state (set from the UI) ---
var bpm = 120.0;
var feelMode = 'pulse';      // 'pulse' | 'pads'  (state; the `feel` message handler sets it)
var beatsPerChord = 4;       // 4 = one chord per bar; 8 = every two bars (match the metro rate)
var useSevenths = false;     // state; the `sevenths` message handler sets it
var vel = 74;
var keyMode = 'pin';         // 'pin' | 'auto'
var keyLocked = true;        // for 'auto': becomes true once detected
var WINDOW_S = 2.5;
var HALFLIFE = 1.2;
var KEEP_S = 8.0;

// --- musical state ---
var ctx = E.makeContext('C:major');
var tonic = 48 + ctx.root;   // follow.py default tonic octave 3
var degree = 1;

// --- runtime buffers ---
var buffer = [];             // [[pitch, tSeconds], ...] of the soloist's recent notes
var sounding = {};           // pitches we currently have on
var recentEmit = {};         // pitch -> tSeconds we last emitted it (echo gate)

// a JS rng for the (cosmetic) velocity humanization; the harmony itself is deterministic
var jsRng = { randint: function (a, b) { return a + Math.floor(Math.random() * (b - a + 1)); } };

function nowS() { return Date.now() / 1000.0; }

// ---- MIDI in: a played note from the soloist (midiparse note outlet -> `prepend note`) ----
function note(pitch, velocity) {
  if (velocity === undefined) { velocity = 0; }
  if (velocity <= 0) { return; }            // note-off: ignore for analysis
  var t = nowS();
  if (recentEmit[pitch] !== undefined && t - recentEmit[pitch] < 0.15) { return; } // echo gate
  buffer.push([pitch, t]);
}
function list() { note(arguments[0], arguments[1]); } // tolerate a bare [pitch vel] list too

// ---- the bar tick (a transport-synced metro -> bang) ----
function bang() {
  var t = nowS();
  prune(t);
  if (keyMode === 'auto' && !keyLocked) { tryDetectKey(t); }

  var hist = E.pitchHistogram(buffer, t, { windowS: WINDOW_S, halflife: HALFLIFE });
  if (Object.keys(hist).length > 0) {
    degree = E.bestDegree(ctx, tonic, hist, degree);
  }
  emitBar();
  outlet(1, 'chord', E.chordName(ctx, tonic, degree, useSevenths));
}

function emitBar() {
  var events = E.chordBarEvents(ctx, tonic, degree,
    { style: feelMode, vel: vel, beats: beatsPerChord, seventh: useSevenths, rng: jsRng });
  var mspb = 60000.0 / bpm;
  for (var i = 0; i < events.length; i++) {
    var onset = events[i][0], dur = events[i][1], p = events[i][2], v = events[i][3];
    scheduleNote(p, v, onset * mspb, dur * mspb);
  }
}

function scheduleNote(p, v, onMs, durMs) {
  var on = new Task(noteOn, this, p, v); on.schedule(onMs);
  var off = new Task(noteOff, this, p); off.schedule(onMs + durMs);
}
function noteOn(p, v) { sounding[p] = true; recentEmit[p] = nowS(); outlet(0, p, v); }
function noteOff(p) { delete sounding[p]; outlet(0, p, 0); }

function prune(t) {
  var kept = [];
  for (var i = 0; i < buffer.length; i++) if (t - buffer[i][1] <= KEEP_S) kept.push(buffer[i]);
  buffer = kept;
}

// ---- auto key detection: estimate then lock once confident (mirrors follow.py) ----
function tryDetectKey(t) {
  var recent = [];
  for (var i = 0; i < buffer.length; i++) {
    if (t - buffer[i][1] <= 6.0) {
      var p = buffer[i][0], s = buffer[i][1];
      recent.push({ pitch: p, start: s, end: s + 0.3 }); // nominal duration for the weighting
    }
  }
  if (recent.length < 8) { return; }
  var res = E.estimateKey(recent); // [root, mode, conf]
  if (res[2] >= 0.6) {
    var name = E.NOTE_NAMES[res[0]] + ':' + res[1];
    setKey(name);
    keyLocked = true;
    outlet(1, 'key', name);
  }
}

// ---- UI / control messages ----
function key(v) {
  if (v === 'auto') { keyMode = 'auto'; keyLocked = false; outlet(1, 'key', 'auto'); }
  else { keyMode = 'pin'; setKey(String(v)); outlet(1, 'key', String(v)); }
}
function setKey(name) {
  ctx = E.makeContext(name);
  tonic = 48 + ctx.root;
}
function feel(f) { feelMode = String(f); }
function rate(bars) { beatsPerChord = Math.max(1, bars) * 4; }
function sevenths(on) { useSevenths = !!on; }
function velocity(v) { vel = Math.max(1, Math.min(127, v)); }
function tempo(b) { if (b > 0) bpm = b; }

function panic() {
  for (var p in sounding) outlet(0, parseInt(p, 10), 0);
  sounding = {};
}
function stop() { panic(); }
function reset() { buffer = []; panic(); }

function loadbang() { post('MIDI Follow device ready (engine.js loaded)\n'); }
