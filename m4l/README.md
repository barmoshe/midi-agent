# MIDI Follow - Max for Live device (MVP)

The `midi-agent` follow-along comp as a Max for Live MIDI device: drop it on a track before an
instrument, play a solo, and the chords follow your harmony in key, bar by bar. No terminal, no
virtual ports, no routing, no feedback trap. This is the MVP chosen in
[`../PLUGIN_MVP.md`](../PLUGIN_MVP.md).

## What's here

| File | Role |
|---|---|
| `engine.js` | The harmony engine, ported 1:1 from the Python PoC (`theory.py` + `follow.py` + `backing.py` primitives). Pure JS, runs in Node and Max v8. |
| `device.js` | The Max v8 object: MIDI I/O, the transport-driven bar decision, note scheduling, the echo gate, UI params + chord readout. Glue over `engine.js`. |
| `test/gen_golden.py` | Dumps golden vectors from the real Python functions. |
| `test/golden.json` | The committed vectors (3633 of them). |
| `test/run.js` | The Node oracle: proves `engine.js` matches Python bit-for-bit. |
| `test/sim_device.js` | Smoke-tests `device.js` outside Max (stubs the Max globals). |
| `BUILD.md` | Step-by-step to assemble the `.amxd` in Max and test it in Ableton. |

## Status: M0 done (port verified)

The riskiest part of the plan - hand-porting the harmony math to JS - is **proven correct**:
`test/run.js` shows all 3633 golden vectors match the Python (ints exact, floats <= 1e-9), and
`test/sim_device.js` confirms the device follows a solo (C-E-G -> C, F-A-C -> F) and panics cleanly.

## Verify (no Max needed)

```bash
cd m4l
../venv/bin/python test/gen_golden.py   # regenerate vectors from Python (optional; committed)
node test/run.js                         # engine.js == Python, bit-for-bit
node test/sim_device.js                  # device.js glue smoke test
# or: npm test
```

## Build the device

See [`BUILD.md`](BUILD.md). Do the M1 pass-through gate first (confirm an inline M4L MIDI effect
plays an instrument downstream on the same track), then wire `device.js`, then freeze to a single
`MidiFollow.amxd`. Requires Ableton Live Suite or the Max for Live add-on.

## Not in this MVP

The frozen `.amxd` binary (built in Max on your machine), any neural engine (the v2 hybrid where a
model decorates voicings but every pitch is hard-masked to the theory-chosen chord - the
`chooseChord -> events` seam is preserved for it), the other PoC modes, and cross-DAW formats. See
`../PLUGIN_MVP.md`.
