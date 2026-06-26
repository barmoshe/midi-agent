# Live MIDI Agent

A turn-taking, call-and-response AI musician. You play a phrase into a virtual MIDI
port; the agent detects that your turn ended, generates a musically-coherent reply, and
streams it back into your DAW as ordinary, editable MIDI. Symbolic (MIDI in, MIDI out),
not audio. Phrase-level turn-taking, not sub-20ms jamming.

This is the **M1-M4 proof of concept**: the no-GPU, no-API-key **heuristic** engine
(music-theory rules: transpose / mirror / arpeggiate / harmonize the human phrase, snapped
to the detected key). The smart engines (local AMT, Claude API) are designed but not built
yet (see `design.md` sections 4.4-4.6, `plan.md` M5/M6).

## Status

- Offline test suite: green (`pytest`, 39 tests, no hardware needed).
- Manual DAW round-trip: pending an operator run on a machine with a real MIDI stack
  (this was built in a headless container with no `/dev/snd/seq`). See "Verify in a DAW".

## Prerequisites

- Python 3.10+ (developed on 3.11).
- A MIDI-capable DAW for the live experience (Reaper, Bitwig, Ableton, Logic, GarageBand).
- macOS or Linux for native virtual ports. Windows needs a helper (see below).

## Install and run

```bash
cd lab/midi-agent
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python agent.py            # opens "Agent In" + "Agent Out", starts listening
```

Useful flags (`agent.py --help` for all):

```
--silence-ms 700      # how long a pause counts as "your turn is over"
--hard-ms 3000        # force a reply even if a note is still held
--trigger-cc 67       # pedal that signals handover (67 = una corda; never collides with sustain 64)
--heuristic-mode restate_vary|mirror|arpeggiate|harmonize
--key "C:major"       # pin the key instead of estimating it
--no-humanize         # disable the timing/velocity micro-variation
```

## Run the tests

```bash
./venv/bin/python -m pytest        # the whole core, offline, against a fake MIDI port
```

The entire capture -> handover -> theory -> responder -> scheduler path is testable with no
real ports and no real sleeps (an injectable clock drives the timers), so you can iterate
without a DAW.

## Per-OS virtual MIDI ports

| OS | Virtual ports | Notes |
|---|---|---|
| **Linux (ALSA)** | Native | Works out of the box. RtMidi cannot read its OWN virtual output, which is exactly why the agent uses two separate ports ("Agent In", "Agent Out"); your DAW sees both. After an unclean kill an ALSA port can linger; rerun and watch for the same-name warning, or reopen the DAW's MIDI prefs. |
| **macOS (CoreMIDI)** | Native | Both ports appear in Audio MIDI Setup and the DAW's MIDI inputs. |
| **Windows** | Not native | Install **loopMIDI**, create two loopback ports, and point the agent at them with `--port-in-name` / `--port-out-name`. The agent code path is identical; only port creation differs. |

## Verify in a DAW (the manual acceptance, operator-side)

1. Start the agent: `./venv/bin/python agent.py`.
2. In your DAW, confirm **"Agent In"** and **"Agent Out"** appear as MIDI ports.
3. Route **"Agent In"** to an instrument track and play a short phrase, then pause (or tap
   the trigger pedal). Within a moment the agent replies on **"Agent Out"**.
4. Arm a track recording from **"Agent Out"** to capture the reply as editable MIDI.
5. Confirm turn-taking loops: play, get a reply, play again, without restarting.

### Feedback / thru warning (important)

Disable **input monitoring / MIDI thru** on the track armed from "Agent Out", and never
route "Agent Out" back into "Agent In". Otherwise the DAW echoes the agent's own output
back at it. The agent has an echo-guard (it ignores incoming notes that match its own
recent output within ~150ms), but a hard thru loop can still confuse turn-taking.

### Stale-port check (Linux)

To observe the ALSA stale-port case the in-process test cannot: run the agent, `kill -9`
it (not a clean exit), rerun, and note whether the same-name warning fires and whether the
port reopens cleanly. Record what you see here if it differs from a clean restart.

## Layout

Flat, single process, no framework. `agent.py` (state machine + CLI + cleanup), `ports.py`
(the only RtMidi module), `capture.py` (NoteRecord + PhraseBuffer), `handover.py`,
`theory.py`, `responder.py`, `scheduler.py`, `config.py`, `tests/`. Design and rationale:
`design.md`. Build plan: `plan.md`.

## Resolved core versions

`python-rtmidi==1.5.8`, `mido==1.3.3`, `pytest==8.3.4` (see `requirements.txt`). The
optional engine deps in `requirements-claude.txt` / `requirements-model.txt` are NOT
installed by default.
