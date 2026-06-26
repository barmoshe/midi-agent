# midi-agent — scope

The agreed, buildable contract for v1. Derived from `brief.md` (the immutable ask)
and `research.md` (the feasibility verdict). Shaped, not specified. Revisit only via
an ADR if scope changes. **Not yet greenlit to build** — this is the prepared contract
for the next session.

## Problem

A musician or producer wants an AI co-creator that responds *musically* inside their
existing DAW, in real editable MIDI (not pre-rendered audio loops), without needing a
GPU rig or fighting latency engineering. Existing AI-music tools either control a DAW
to author static clips, or generate audio loops; a real-time symbolic *call-and-response*
partner is comparatively unoccupied.

## Appetite

**2-3 days** for a proof-of-concept. Throwaway-OK quality bar for the model wiring;
the MIDI plumbing should be clean enough to reuse.

## Solution sketch

A turn-taking call-and-response MIDI agent:

- A standalone Python agent opens a **virtual MIDI port** (`python-rtmidi`,
  macOS/Linux native) the DAW sees as an input.
- The human plays a phrase; the agent **captures** the incoming MIDI, detects the
  end of the phrase (handover signal: a pause, a pedal, or a hotkey).
- The agent **generates a musical response** (model inference, ~1-2s is fine because
  it is turn-taking) and **streams it back** out the virtual port into the DAW.
- Response engine: start with the simplest thing that sounds musical, layered:
  (1) a heuristic/rules fallback so the demo runs with no GPU, then
  (2) a model path — Aria (piano, Apache-2.0) or Anticipatory Music Transformer
  (multi-instrument, Apache-2.0 code).

## Acceptance criteria (the "done" v1 is measured against)

- [ ] A virtual MIDI port appears as an input in at least one DAW (Ableton/Logic/
      Reaper/Bitwig) on macOS or Linux.
- [ ] Playing a phrase into the port produces an audible, musically-coherent
      response streamed back into the DAW as MIDI notes the user can see/edit.
- [ ] Turn-taking works end to end: play -> handover -> response -> ready for the
      next turn, without a restart.
- [ ] Runs on a machine with no dedicated GPU (heuristic path at minimum).
- [ ] README documents setup per OS, including the Windows loopMIDI caveat.

## No-gos (out of scope for this appetite)

- Sub-20ms simultaneous jamming (separate, harder class of system).
- Real-time symbolic inference on commodity CPU (unproven; not needed for turn-taking).
- Native Windows virtual-port support (document the loopMIDI workaround instead).
- Commercial deployment (pending weights-license confirmation).
- A polished GUI; a web/WebMIDI front end is a possible later layer, not v1.

## Rabbit holes (called out up front)

- **Model latency creep:** if the model path is slow/unmusical, the heuristic
  fallback keeps the demo alive. Build the plumbing first, model second.
- **Weights vs code licenses:** code is Apache/MIT-clean; weights are stated
  separately and sometimes non-commercial (MIDI-GPT looks CC-BY-NC). Confirm on
  HuggingFace before leaning on any specific model.
- **Phrase-end detection:** the handover signal is the fiddly UX bit; start with an
  explicit hotkey/pedal before trying silence-based auto-detection.
