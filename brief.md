# midi-agent — brief

Immutable once written. Track changes as decisions, not edits.

- **One-liner:** An innovative AI + MIDI lab tool. Open exploration that landed on a
  real-time "Live MIDI Agent": an AI that plays symbolic MIDI into a DAW and reacts
  to what a human plays.
- **For / job-to-be-done:** A musician or producer who wants an AI co-creator that
  responds musically inside their existing DAW, in real MIDI (notes they can edit),
  not pre-rendered audio loops.
- **v1 "done":** TBD on build greenlight. The de-risked target is a turn-taking
  call-and-response agent: human plays a phrase into a virtual MIDI port, the agent
  generates a musical response and streams it back into the DAW. macOS/Linux first.
- **Constraints:** Buildable by an AI agent in hours-to-days. Reuse mature libraries
  (mido, python-rtmidi). Avoid the parts the research flagged as real ML/latency
  engineering (sub-20ms jamming; real-time symbolic inference on commodity CPU).
- **After-demo intent:** Lab lead-gen surface + a candidate to harden into a skill or
  MCP if it lands. Showcase-able.
- **Open questions:** Which model for the response engine (Anticipatory Music
  Transformer vs Aria-piano); weights-license confirmation for commercial use;
  whether to add a web/WebMIDI front end later.
