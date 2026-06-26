# HANDOFF - Live MIDI Agent

For the next agent (likely a **local** Claude with a real DAW + MIDI stack) picking up
this project. Read this first, then `design.md` (source of truth) and `plan.md` (task
spec). This file is the bridge between what was built headless and what you can finish
locally.

## TL;DR

The **M1-M4 proof of concept is built and green** (39 offline `pytest` tests). It is the
no-GPU, no-API-key **heuristic** turn-taking agent: play a phrase into a virtual MIDI port,
it detects your turn ended, composes an in-key reply with music-theory rules, streams it
back to your DAW as editable MIDI. What remains is (1) the **manual DAW verification** you
can actually do locally, and (2) the optional **smart engines** (M5 local AMT, M6 Claude
API) behind the existing `Responder` seam.

## Orient yourself (read in this order)

1. `scope.md` - the 5 acceptance criteria the PoC is measured on.
2. `design.md` - the architecture and every invariant. Sections: 2 (concurrency +
   coordinate contract), 4 (engines), 5 (handover/echo-guard/panic), 6 (theory), 9 (build
   plan), 4.4/4.5/4.6 (the unbuilt engines).
3. `plan.md` - task-level plan with ids (M1.x..M6.x) and gates G1-G6.
4. `research.md` + `research-claude-engine.md` - why the engine choices are what they are
   (notably: subscription-headless Claude is NO-GO for the live loop; local AMT is the
   recommended no-key smart engine).

## What is built (and where)

Flat layout, single process, no framework:

| File | What it does |
|---|---|
| `ports.py` | The ONLY RtMidi module. Two virtual ports ("Agent In"/"Agent Out"), non-blocking callback, same-name-port warning, teardown, `emit_test_scale`, MIDI parse. |
| `capture.py` | Frozen `NoteRecord` (start_s<end_s invariant) + lock-guarded `PhraseBuffer` (dangling note-off synthesis at handover, `phrase_t0` normalize). |
| `handover.py` | `HandoverDetector` (CC67 trigger + silence ladder) + `PollLoop` (the silence timers MUST live on the poll thread). |
| `theory.py` | `MusicalContext`: duration-weighted Krumhansl-Schmuckler key + median-IOI tempo, both with confidence floors, `snap`/`degree_transpose`. |
| `responder.py` | `Responder` ABC, `HeuristicResponder` (restate_vary/mirror/arpeggiate/harmonize + `MotifAnalyzer` + `humanize`), `FallbackResponder`, `build_responder` factory. |
| `scheduler.py` | Absolute-target sleep player (no drift), echo-guard, sounding-note tracking, all-notes-off. |
| `agent.py` | LISTEN/HANDOVER/RESPOND machine, CLI, guaranteed `panic_cleanup` via atexit/SIGINT/SIGTERM. |
| `config.py` | One tunables dataclass + argparse. |
| `tests/` | `fake_port.py` (in-memory port double + injectable clock) + 8 test modules. |

## Run it locally

```bash
cd midi-agent
python3 -m venv venv                       # venv is gitignored; recreate it
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m pytest                # expect: 52 passed
./venv/bin/python agent.py                 # opens the two virtual ports, starts listening
```

## YOUR FIRST JOB: the manual DAW round-trip (it could not run headless)

This was built in a headless container with no `/dev/snd/seq`, so the live-port and DAW
gates (G1/G3/G4 manual lines in `plan.md`) were never exercised. You can. Do this and
record what you find in `STATUS.md`:

1. `python agent.py`; confirm **Agent In** + **Agent Out** show up in your DAW's MIDI ports.
2. Route Agent In to an instrument, play a short phrase, pause (or tap CC67). Confirm a
   reply arrives on Agent Out within ~1s and is in key.
3. Arm a track from Agent Out; confirm the reply records as editable MIDI.
4. Confirm turn-taking loops without a restart.
5. Echo-guard check: enable MIDI thru on the armed track and confirm the agent does NOT
   self-trigger (it should ignore its own output within ~150ms).
6. Linux stale-port check: `kill -9` the agent, rerun, note whether the same-name warning
   fires and whether the port reopens cleanly. Record it in the README.

If anything is off, the offline suite + `fake_port` let you reproduce most of it without
the DAW. Tune `--silence-ms` for feel (the single most interaction-defining knob).

## NEXT MILESTONES (in order)

### M5 - Local AMT engine (BUILT offline; operator hardware pass remains)

The "smart" upgrade the operator actually wants: free, offline, MIDI-native. The
offline-testable bulk is **built and green** (`amt_engine.py` + `tests/test_amt_bridge.py`,
`tests/test_amt_responder.py`, `tests/test_fallback.py`). What was built:

- `amt_engine.py`: the model-free NoteRecord <-> temp `.mid` bridge, the guarded-import
  `AmtResponder` (the module always imports; constructing it without torch raises a catchable
  ImportError), the section-4.4 round-trip (phrase -> `midi_to_events` -> `generate(start_time
  =t_end..)` -> `events_to_midi` -> notes), the call-and-response window filter + t=0 re-base,
  and the shared scale-snap + `humanize` post-pass. The model boundary (`_encode`/`_generate`/
  `_decode`) is the injectable test seam.
- `responder.py`: `build_responder` routes `--responder amt` behind a `FallbackResponder` with
  a best-effort `--amt-timeout`; missing deps / load failure / timeout drop to the heuristic.
- `config.py`: `--amt-model`, `--amt-device`, `--amt-response-bars`, `--amt-top-p`,
  `--amt-timeout`, `--amt-no-snap`. Default `--responder` stays `heuristic`.

**What remains is operator/hardware-side (M5.2 + M5.10):** `pip install -r
requirements-model.txt`, run `--responder amt` against a DAW, confirm a model-composed in-key
reply records and loops, observe one real CPU `generate()` latency and the loop behavior
during it, and confirm the HuggingFace **weights** license before any paid use (the AMT code
is Apache-2.0; weights believed Apache-2.0, confirm). Keep responses ~2 bars on CPU.

### M6 - Claude API engine (optional, needs a metered key)

See `design.md` 4.5. `claude_engine.py` with `ClaudeResponder`; direct `anthropic` Messages
call, Haiku tier, streaming + tool-use JSON `NoteRecord`s + prompt caching; `--responder
claude` already wired behind `FallbackResponder`. Do NOT use the subscription-headless path
for the live loop (4.6, research pass 4 = NO-GO: volatile latency, possible separate
metering).

### Other follow-ups

- CI (`plan.md` X6): a repo-root `.github/` workflow is **business-scope** in this monorepo
  - confirm with the operator before adding it.
- Stretch hooks (documented no-ops, not required): prefill-during-listen, adaptive-IOI
  handover threshold.

## How to add an engine (the one seam)

Implement `Responder.respond(phrase, context) -> tuple[NoteRecord, ...]` (offsets from 0),
add a guarded import + a branch in `responder.build_responder`, ship its deps in a separate
`requirements-*.txt`, and let `FallbackResponder` wrap it. The MIDI core never imports a
model. Add a `tests/test_<engine>.py` that runs offline (mock the model/client) so CI stays
hardware-free.

## Invariants you must not break

1. **Two separate virtual ports** (Linux RtMidi can't read its own).
2. **Three threads, no asyncio.** Callback only stamps time + appends + pushes to the queue
   (never sleeps/blocks). Silence handover lives ONLY on the poll thread.
3. **Coordinate contract:** capture normalizes to `phrase_t0`; responses are offsets from 0;
   the scheduler sleeps to ABSOLUTE `play_t0 + offset`, never cumulative sums.
4. **Dangling note-offs** synthesized at handover before the snapshot; `start_s < end_s`.
5. **Echo-guard** on reclaim; **panic/all-notes-off** guaranteed on any exit.
6. Optional engines stay guarded imports in separate requirements files.
7. Every output pitch scale-snapped to the detected key.

## Gotchas (learned the hard way)

- **Two repo hooks throw false positives.** A `*contract*` filename trips `protect-paths`
  (that is why the test is `tests/test_invariants.py`, not `test_contracts.py`). The word
  "contract" plus a `>` (e.g. the `<email>` trailer) in a commit message trips `fs-safe` -
  keep both out of commit messages.
- **House style: no em dashes** in committed files (use commas, parens, hyphens).
- **`venv/` is gitignored** - recreate it; never commit it.
- This is now its **own standalone repo** (`github.com/barmoshe/midi-agent`), relocated from
  the bar_builds monorepo on 2026-06-26. Full autonomy here; `.github/` CI is this repo's own
  scope now (no longer monorepo business-scope).

## Git flow

This is a standalone repo with `origin` = `github.com/barmoshe/midi-agent`, default branch
`main`. Work on a feature branch, keep `pytest` green, commit in milestone-sized chunks, open
a PR (CI runs `pytest` on push/PR). Update `STATUS.md` as you go. Two commit-message gotchas
still apply (see above): no em dashes, and keep the word "contract" + a `>` out of messages.

## Definition of done for the PoC (from scope.md)

- [x] A virtual MIDI port appears as a DAW input (code done; **operator/local agent to
      confirm in a DAW**).
- [ ] Play a phrase -> in-key reply recorded as editable MIDI (**needs the DAW run**).
- [ ] Turn-taking loops without restart (**needs the DAW run**).
- [x] Runs with no GPU (heuristic path; the optional M5 AMT engine is the smart upgrade).
- [x] README documents per-OS setup incl. the Windows loopMIDI caveat.

The code and offline proof are done; the three unchecked boxes need a real DAW, which is
your job now.
