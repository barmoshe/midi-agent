# Live MIDI Agent - Build Plan

The authoritative, sequenced build plan for the Live MIDI Agent (`lab/midi-agent/`):
a turn-taking call-and-response AI musician in Python. The DESIGN is done
(`design.md` is the source of truth). This document is the BUILD PLAN: task ids,
dependencies, acceptance checks, verification gates, and a session-by-session order
an agent executes next session. It contains no implementation code (signatures and
pseudocode appear only where a task needs clarifying).

House style: no em dashes (commas, parentheses, or hyphens instead).

---

## 1. Purpose and how to use this plan

**Purpose.** Turn the locked `design.md` into a checkable, sequenced build. The
product is the heuristic-engine PoC (M1-M4). The neural engines (M5 local AMT, M6
Claude API) are post-PoC upgrades through the same `Responder` seam and are not part
of the shippable definition of done.

**How to use it.**

1. Settle the open decisions in section 2 before writing code (most are already
   recommended; G0 confirms the blocking ones).
2. Work milestone by milestone in the order of section 6. Each task has an `id`,
   `produces`, `depends-on`, an `acceptance` check, and the `test` to write
   alongside it (tests-first for the offline core).
3. Do not advance past a milestone until its verification gate (section 7) is green.
   Offline gates run under `pytest` against `fake_port` with an injectable clock,
   zero real hardware, zero real sleeps. Each milestone has exactly one manual DAW
   gate.
4. Trace every acceptance criterion back to `scope.md` via the Definition of Done
   (section 8).
5. Watch the risk checkpoints (section 9) at the listed task boundaries.

**Engine-numbering convention (resolved).** This plan uses **M5 = local AMT engine**
and **M6 = Claude API engine**, per `design.md` section 9 (lines 463-464) and the task
brief. Note that `design.md` section 7's stack table (lines 410-411) has the labels
SWAPPED ("Claude engine (RECOMMENDED, M5)" / "Local model (OPTIONAL, M6)"), which
contradicts its own section 9. The plan follows section 9; the section-7 table should
be corrected in `design.md` so the design doc stops self-contradicting. Record this
reconciliation in the build-start ADR at G0.

**Reading the tables.** `depends-on` lists task ids that must complete first. `test`
names the pytest file/case to write with the task (`none` means scaffolding/manual).
Manual tasks are the unavoidable hardware steps; everything else is offline.

**Scope discipline (from `design.md` ch.13).** No capture/handover/theory logic is
written before the M1 round-trip is verified. The coordinate contract is honored
literally everywhere: capture normalizes to `phrase_t0`; `respond()` emits offsets
from 0; the scheduler sleeps to ABSOLUTE `play_t0+offset` targets, never cumulative.

---

## 2. Open decisions to settle before coding

Most are pre-decided with a recommendation. The two business-scope items (greenlight,
layout/CLAUDE.md correction) are confirmed at G0 in section 7.

| # | Decision | Recommendation (adopt unless the operator overrides) |
|---|---|---|
| D1 | Manual-verification DAW on the build OS | **Reaper on Linux** primary (free, cross-platform, simplest virtual-port arming + explicit input-monitoring/thru toggles the echo-guard README depends on). **Bitwig** Linux secondary (first-class ALSA). Logic/GarageBand only if the build OS is macOS. Build OS is Linux 6.18, so Reaper/ALSA is the path. |
| D2 | Default handover mode out of the box | **Silence ladder is the always-on baseline** (700ms settle / 3000ms hard, needs no hardware so the PoC demos for anyone). CC67 pedal is an additive override. Hotkey is an additive fallback wired in M4. Do not require a pedal for the core M3 demo. |
| D3 | When to build `fake_port` + injectable clock | **Minimal record/replay stub before M1** (plus frozen NoteRecord/Responder/MusicalContext contracts), then **grow the injectable-clock + scripted-stream features in M2** when the poll-thread timers first need them. Honors `design.md` ch.13 #3 without front-loading. |
| D4 | Dependency pinning | **Exact-pin the core** (`python-rtmidi==`, `mido==`, `pytest==`) in `requirements.txt` for reproducible cross-OS builds (rtmidi is a compiled C extension, the most likely ABI break). **Floors only** (`>=`) for the optional engine extras (`requirements-claude.txt`, `requirements-model.txt`). Record resolved verified versions in the README. |
| D5 | How config defaults are chosen | **Adopt the design-doc literals verbatim** as v1 defaults (silence=700, hard=3000, poll=30ms, trigger-cc=67) in a single source-of-truth block in `config.py` citing design section 5.0. Confidence floors (key/tempo) get unit-test-derived thresholds in M3, not guesses. Empirical silence-feel tuning deferred to the M4 manual session. |
| D6 | Build skeleton location | **Flat in `lab/midi-agent/`** exactly as design section 7 specifies (modules at folder root, `tests/` beneath). The design doc supersedes the older CLAUDE.md "likely mvp/" guess. No package nesting. Correct the per-project CLAUDE.md at G0. |
| D7 | CI | **Minimal GitHub Actions workflow** installing `requirements.txt` + `pytest` on push, core deps only (never the engine extras). The whole core is offline-testable, so CI is cheap and guards the determinism/drift/dangling/echo/panic invariants. |

---

## 3. Build principles

1. **Plumbing first, model second.** M1-M4 (heuristic engine) is the shippable
   product; every acceptance criterion is met before any neural engine (M5/M6). The
   `Responder` interface is the only seam the model swaps through.
2. **Tests-first for the offline core.** The whole capture -> handover -> theory ->
   responder -> scheduler path runs against `fake_port` with an injectable clock.
   Write the invariant test (handover-fires, dangling-free, in-key, no-drift,
   no-echo-reclaim, no-stuck-notes) alongside the module, not after; CI runs them on
   push.
3. **Hardware only where unavoidable.** Exactly one manual step per milestone (the
   DAW round-trip) needs real ports. Never block iteration on a DAW.
4. **Honor the coordinate contract literally.** Capture normalizes to `phrase_t0`;
   `respond()` emits offsets from 0; the scheduler sleeps to ABSOLUTE
   `play_t0+offset` targets. Never sum per-note sleeps. Enforce `start_s < end_s` in
   `PhraseBuffer.snapshot()` and unit-test it.
5. **Concurrency discipline is explicit M2 work, not free.** Three threads (native
   callback / poll / state+scheduler) + one `queue.Queue`, no asyncio. The callback
   never sleeps/blocks and is the sole writer of `last_event_time`; silence handover
   lives ONLY in the poll thread; all sends go through the scheduler. Every
   shared-state access is lock-guarded.
6. **Safety invariants built incrementally across M2-M4, never deferred.** Dangling
   note-offs synthesized at handover before snapshot; echo-guard so the agent never
   mistakes DAW-thru of its own output for a human reclaim; guaranteed panic cleanup
   (explicit note_offs + CC123 on all 16 channels) on every exit/exception via
   atexit + SIGINT/SIGTERM + try/finally.
7. **Musical coherence over cleverness.** Every generated pitch is scale-snapped to
   the duration-weighted detected key; key and tempo each carry a confidence floor
   that falls back to last-known/`--key-lock` rather than answering out of key (the
   most audible failure). v1 tempo is an honest "smart echo" (literal onset
   spacing), not beat induction.
8. **Optional engines never break the default.** `anthropic` and
   `transformers`/`torch` are guarded imports in separate requirements files, never
   installed by default. Any ImportError/exception is caught by `FallbackResponder`
   and drops to the always-importable `HeuristicResponder`.
9. **Match the appetite.** Smallest surface that satisfies acceptance: flat module
   layout, single process, stdlib + two MIDI libs. Stretch hooks
   (prefill-during-listen, adaptive-IOI, process-isolated timeout) are documented
   no-ops, not v1 work. Do not pre-build.
10. **Plain, verifiable artifacts.** A per-OS README with DAW arming steps + the
    feedback/thru warning + Linux own-port quirk is a deliverable (M4), not an
    afterthought. No em dashes in committed docs.
11. **Cleanup-on-exit is non-negotiable.** Ports close on teardown, a same-name-port
    collision warns at startup, and no exit path leaves a stuck note or a stale ALSA
    port without at least a documented recovery.

---

## 4. Cross-cutting setup tasks

Built once, consumed by every milestone. Most land in M1; the harness grows in M2/M3.

| Id | Task | Lands in | Notes |
|---|---|---|---|
| X1 | Flat build skeleton in `lab/midi-agent/` per design section 7 (`agent.py`, `ports.py`, `capture.py`, `handover.py`, `theory.py`, `responder.py`, `scheduler.py`, `config.py`, `tests/`), Python 3.10+ venv, `.gitignore` (`venv/`, `__pycache__/`, scratch `*.mid`). No package nesting. | M1.1 | |
| X2 | Requirements files: `requirements.txt` (exact-pinned `python-rtmidi`, `mido`, `pytest`) installed by default; `requirements-claude.txt` (`anthropic>=`) and `requirements-model.txt` (`transformers>=`, `torch>=`, `anticipation>=`) NOT installed. Record verified resolved versions. | M1.2 (claude/model files in M6.1/M5.1) | |
| X3 | Shared data contracts frozen first: `NoteRecord` frozen dataclass (pitch/velocity/start_s/end_s/channel, `start_s < end_s` invariant), `Responder` ABC signature, `MusicalContext` shape. Referenced from M1's test pattern through M6, so lock before module logic to prevent churn. | M1.3 (MusicalContext shape finalized M3.1) | |
| X4 | `tests/fake_port.py` + injectable-clock harness: an in-memory rtmidi-port double that records emitted messages and replays scripted input streams, with an injectable clock so the poll-thread silence timers are testable without real waits. Minimal stub before M1; injectable-clock + scripted-stream grown in M2; output-capture for the scheduler grown in M3. | M1.8 -> M2.4 -> M3.12 | |
| X5 | Test scaffolding: pytest layout + `conftest.py` with shared fixtures (fake-port pair, a clock, canonical known phrases for key/tempo assertions) reused by `test_handover` / `test_theory` / `test_heuristic` / `test_scheduler` / `test_feedback` / `test_panic`. | M1.8 -> M2.8 | |
| X6 | CI: minimal GitHub Actions workflow installing `requirements.txt` + running `pytest` on push (core deps only, never the optional engine extras). Guards the determinism/drift/dangling/echo/panic invariants. | M2.9 (modules added per milestone at M3.16/M4.9) | |
| X7 | `config.py` defaults block: ONE source-of-truth tunables dataclass + argparse (`--trigger-cc`, `--silence-ms`, `--hard-ms`, `--poll-ms`, `--responder`, `--response-bars`, `--port-names`, `--key`) seeded with design-section-5.0 literals + an inline citation comment. Grown by APPEND only: M2.8 seeds the M2 thresholds, M3.16 appends the M3 floors/humanize/seed, M4.1 appends the M4 fields and CONSOLIDATES (never re-declares or forks the earlier values; a test asserts the M2/M3 design-literals are unchanged). Consumed by every milestone. | M2.8 (appended M3.16, consolidated M4.1) | |
| X8 | Panic/cleanup + logging plumbing: atexit/SIGINT/SIGTERM + try/finally cleanup wiring and a lightweight logging setup (FallbackResponder warnings, handover events, teardown). Established early so each milestone plugs in. | M1.7 (full wiring M4.2/M4.3) | |
| X9 | README scaffold: per-OS (macOS/Linux) skeleton with section stubs (setup, venv/install, per-DAW arming Reaper/Ableton/Bitwig/Logic, Linux own-port quirk, Windows loopMIDI workaround, feedback/thru warning, run command). Filled across milestones, completed in M4. | M1.9 (completed M4.8) | |
| X10 | Project bookkeeping: update `STATUS.md` to "build started / current milestone" and correct the per-project CLAUDE.md (flat layout, not "likely mvp/") when the build begins; log a build-start ADR if the greenlight or any locked default changes. | M1.0 | Business-scope; see G0. |

---

## 5. Per-milestone task tables

### M1 - Loopback / port proof (~0.5d)

Prove the hardware-in-the-loop spine before any musical logic: two separate virtual
ports, receive on Agent In, emit a DISTINCT C-major scale (not an echo) on Agent Out
that a DAW records as editable MIDI, clean teardown on every exit path, a same-name
warning, explicit validation of the Linux own-port quirk. Stand up only the
cross-cutting scaffolding M1 needs.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M1.0 | Confirm greenlight + lock M1 defaults (business-scope): verify `scope.md`/`STATUS.md` greenlight; record the two locked decisions M1 depends on (flat layout per design section 7; Reaper-on-Linux primary, Bitwig secondary). Update STATUS to "build started / M1"; correct CLAUDE.md's stale "likely mvp/". | Greenlight noted; CLAUDE.md flat; DAW target recorded; build-start ADR if anything changed | - | STATUS reads "build started / M1"; CLAUDE.md no longer says "likely mvp/"; DAW target written down; greenlight explicitly confirmed (not assumed) | none |
| M1.1 | Create the flat skeleton: empty module stubs + `tests/` (`fake_port.py`, `conftest.py` placeholders), Python 3.10+ venv, `.gitignore`. No nesting. | Flat module tree, `tests/`, venv, `.gitignore` | M1.0 | All eight modules + `tests/` at folder root (no `src/`/`mvp/`); `python --version` >=3.10; `.gitignore` excludes venv/pycache/scratch `.mid` | none |
| M1.2 | Author requirements files; install core: `requirements.txt` exact-pinned `python-rtmidi==`/`mido==`/`pytest==`; `requirements-claude.txt`/`requirements-model.txt` floors authored but NOT installed. Install core, record resolved versions. | Requirements files; installed core; resolved-versions note | M1.1 | `pip install -r requirements.txt` succeeds; `python -c 'import rtmidi, mido'` clean; anthropic/transformers/torch NOT importable; versions captured | none |
| M1.3 | Freeze shared contracts: `NoteRecord` frozen dataclass (`start_s < end_s` via `__post_init__`), `Responder` ABC (`respond(phrase, context) -> list[NoteRecord]`), `MusicalContext` placeholder. Signatures only, no behavior. | `NoteRecord` + invariant; `Responder` ABC; `MusicalContext` stub | M1.1 | `NoteRecord` frozen/immutable; `start_s >= end_s` raises; `Responder` ABC not instantiable; all three import without engine deps | `tests/test_contracts.py`: NoteRecord frozen + invariant fires; Responder ABC abstract |
| M1.4 | Implement `ports.py`: open two SEPARATE virtual ports via `open_virtual_port()` (MidiIn "Agent In", MidiOut "Agent Out"); register a non-blocking input callback that for M1 prints/logs each message with its `perf_counter` stamp; expose a raw send primitive on Agent Out. Default names in `config.py`. | `ports.py` with `open_ports()`/send/callback registration | M1.2, M1.3 | A tiny harness opens both ports; `aconnect -l` (or DAW prefs) lists both names; callback is non-blocking and stamps `perf_counter` | `tests/test_ports.py`: open creates two distinct named ports; send routes to out-port record; callback fires on a scripted message |
| M1.5 | Same-name-port collision warning + Linux stale-port note: at startup enumerate existing port names; warn (via logging) if "Agent In"/"Agent Out" already exists before opening, so a stale ALSA port from an unclean exit is surfaced. | Startup collision check + warning; documented recovery hint | M1.4 | Opening when a same-named port exists logs a visible warning (not a crash); text names the colliding port and points at the recovery note | `tests/test_ports.py`: pre-seeded same-name port -> `open()` emits the warning exactly once |
| M1.6 | Distinct C-major test pattern emitter: a function emitting an ascending C-major scale (60,62,64,65,67,69,71,72) as note_on/off pairs on Agent Out with simple fixed timing, explicitly NOT an echo. Uses the `ports.py` send primitive. | `emit_test_scale()` | M1.4 | Invoking it produces the exact 8-note note_on/off sequence on the out-port; pitches are the scale, not the input | `tests/test_ports.py`: `emit_test_scale` records exactly (60,62,64,65,67,69,71,72) with matched pairs |
| M1.7 | Panic/cleanup + logging plumbing as reusable infra: atexit + SIGINT/SIGTERM + try/finally around the M1 run loop that closes both ports and sends CC123 on all 16 channels of Agent Out on any exit/exception; lightweight logging setup. No tracked sounding notes yet, but the seam + port-close must exist. | `cleanup()` + signal/atexit wiring + logging in `agent.py` | M1.4, M1.5 | Ctrl-C, SIGTERM, normal exit, injected exception all run cleanup once; both ports closed after (none in `aconnect -l`); CC123 on all 16 channels | `tests/test_panic.py` (M1 slice): injected exception -> cleanup once, both fake ports closed + CC123 x16 |
| M1.8 | Minimal `fake_port` stub + pytest scaffolding: `tests/fake_port.py` records emitted messages + replays a scripted incoming stream; `conftest.py` exposes a fake-port-pair fixture. M1 scope is record/replay only; injectable clock + scripted-timing deferred to M2. | `fake_port.py` (record + replay); `conftest.py`; green M1 pytest | M1.3 | `pytest` runs and all M1 tests pass against `fake_port` with zero real ports and zero real sleeps | manual (this task IS the harness; assertions live in M1.3-M1.7) |
| M1.9 | README scaffold + per-OS stub, M1 parts filled: setup/venv/install, M1 run command, Reaper-on-Linux + Bitwig arming, Linux own-port quirk + stale-port recovery, Windows loopMIDI pointer, feedback/thru warning stub (filled M4). No em dashes. | `README.md` with M1 sections + later stubs; resolved versions folded in | M1.2, M1.6, M1.7 | A fresh reader can venv/install/run the M1 harness and arm a Reaper-on-Linux track from the README alone; quirk + recovery documented; no em dashes | manual |
| M1.10 | Manual hardware acceptance: run the M1 harness, open Reaper on Linux, confirm both ports appear, arm a track on Agent Out and record while the emitter runs, confirm the C-major scale lands as editable MIDI, send MIDI into Agent In and confirm the callback prints it. Validate the own-port quirk and clean teardown. THEN run the explicit STALE-PORT procedure (the real ALSA collision case, which the in-process M1.5 test cannot reproduce): (a) run the agent, (b) `kill -9` it (NOT a clean exit, so cleanup does not run), (c) re-run the agent and OBSERVE both whether the same-name collision warning fires AND whether `open_virtual_port` succeeds or raises against the port left by the killed process, (d) record the observed ALSA behavior + the documented recovery in the README (convert the unfalsifiable checkbox into a recorded observation). | DAW round-trip evidence; quirk validated; clean teardown confirmed; RECORDED observation of the real `kill -9` stale-port behavior + recovery | M1.6, M1.7, M1.9 | Both ports in DAW; recorded clip is the distinct C-major scale (not an echo); incoming Agent In printed; no stale port after a CLEAN exit; AND the `kill -9` stale-port path is exercised and its observed behavior (warning fires y/n; reopen succeeds or raises; recovery steps) is written into the README | manual |

### M2 - Capture + handover + three-thread concurrency (~1d)

Lock-guarded PhraseBuffer, the three-thread model wired by one `queue.Queue`, the
HandoverDetector silence ladder + in-callback trigger-CC check, mandatory dangling
note-off synthesis, the immutable `phrase_t0`-normalized snapshot. Grow `fake_port`
into a full injectable-clock + scripted-stream harness.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M2.1 | Finalize `capture.py` `NoteRecord` + open-note bookkeeping: confirm the frozen `NoteRecord` from M1; define the mutable `OpenNote` keyed by `(pitch, channel)` holding `start_s` + velocity until its note_off arrives. | `capture.py` frozen `NoteRecord` + internal open-note structure | - | `NoteRecord` frozen/immutable; open-note keyable by `(pitch, channel)` and convertible to a `NoteRecord` once `end_s` known; `start_s < end_s` documented | `test_capture.py::test_noterecord_frozen_and_invariant` |
| M2.2 | Implement `PhraseBuffer` with a single `threading.Lock` guarding all shared state (NoteRecord list, open-notes map, held-notes set, `last_event_time`, `phrase_t0`/first-onset). Expose `append_event(msg, t)`, a lock-guarded read of `(now - last_event_time)` + held-notes-empty, and `clear()`/re-arm. | `PhraseBuffer` with lock-guarded mutators + readers | M2.1 | Every field access under the lock; note_on records an open note + stamps `last_event_time`/first-onset; note_off closes the matching open note; held-notes reflects down notes; `clear()` resets to LISTEN-ready | `test_capture.py::test_phrasebuffer_basic_accumulation` |
| M2.3 | Implement `PhraseBuffer.snapshot(handover_t)`: synthesize note_offs at `handover_t` for every still-open note BEFORE freezing, normalize every record to `phrase_t0` (first onset -> 0.0), enforce `start_s < end_s`, return an immutable (tuple) frozen phrase. Order: closeout -> normalize -> freeze. Snapshot must NOT mutate the live buffer. | `snapshot()` returning a dangling-free, `phrase_t0`-anchored immutable phrase | M2.2 | Open note at handover closed at `handover_t`; first `start_s == 0.0`; no record `start_s >= end_s`; phrase immutable; snapshot does not clear the live buffer | `test_handover.py::test_dangling_closeout` + `test_capture.py::test_snapshot_normalizes_to_phrase_t0` |
| M2.4 | Grow `tests/fake_port.py` into the full offline harness: `FakeMidiIn` (scripted-stream replay into the callback), `FakeMidiOut` (records sends), an injectable `Clock` (fake `perf_counter` read by poll + capture, advanceable in tests without real sleeps). Parameterize the time-read seam (clock passed in, default `time.perf_counter`). | `FakeMidiIn`/`FakeMidiOut`/injectable `Clock` | M2.1 | A test registers the capture callback on `FakeMidiIn`, pushes a scripted stream on the fake clock, advances past `settle_ms` with no real wait, and observes the silence accessor cross threshold; `FakeMidiOut` records every emit in order | `test_fake_port.py::test_scripted_stream_and_clock` |
| M2.5 | Wire the native rtmidi callback: on each message stamp `clock()` once, call `PhraseBuffer.append_event` (note bookkeeping + `last_event_time`), push the raw event onto a shared `queue.Queue`, and evaluate ONLY the immediate trigger-CC check (`control == trigger_cc and value >= 64`). Never sleep/block; sole writer of `last_event_time`; treat note_on velocity 0 as note_off. | Callback wiring + queue producer side | M2.2, M2.4 | Feeding messages updates the buffer + enqueues; trigger-CC `value >= 64` raises handover synchronously in the callback; vel-0 empties held-notes; static read confirms no sleep/block/IO; `last_event_time` written nowhere else | `test_handover.py::test_trigger_cc_fires_immediately` + `test_capture.py::test_noteon_vel0_is_noteoff` |
| M2.6 | Implement `HandoverDetector` + poll thread (`handover.py`): a `threading.Thread` waking every `poll_ms` (30) reading the clock, evaluating under the buffer lock: (1) held-notes empty AND `now - last_event_time > settle_ms` (700) -> fire; (2) hard override `> hard_ms` (3000) -> fire even with a note held. Fire exactly once (debounced one-shot until re-armed). The ONLY place silence handover lives. | `HandoverDetector` + poll-loop thread reading the injectable clock; single debounced fire signal | M2.2, M2.4 | Settle fires only when held-notes empty (a held note suppresses settle but not hard); hard fires with a note held past `hard_ms`; fires exactly once per phrase; silence logic exists nowhere in the callback | `test_handover.py::test_settle_fires_when_silent`, `::test_held_note_suppresses_settle_but_hard_overrides`, `::test_fires_once_until_rearm` |
| M2.7 | Wire the LISTEN<->HANDOVER seam in `agent.py` (M2 scope only): drain the queue, react to the fire signal (callback trigger-CC OR poll thread), transition LISTEN -> HANDOVER, call `snapshot(handover_t)`, print "handover detected, N notes captured" + the snapshot, then `clear()`/re-arm and return to LISTEN. RESPOND/theory/scheduler are M3; stub the post-snapshot path. | M2-slice state machine (queue drain, handover handling, snapshot, demo print, re-arm) | M2.3, M2.5, M2.6 | A scripted phrase produces exactly one "handover detected, N notes captured" with correct N and a `phrase_t0`-anchored dangling-free snapshot; N COUNTS the dangling note that was closed at handover (a scripted phrase with the last note still held at fire, e.g. 4 onsets with the 4th held, yields N==4, every record `start_s<end_s`), proving the closeout-counts-as-a-note path; after firing the buffer clears and a second phrase fires its own handover | `test_handover.py::test_end_to_end_capture_to_snapshot` (asserts N includes the closed dangling note) |
| M2.8 | pytest scaffolding: `conftest.py` shared fixtures (FakeMidiIn/Out pair, injectable Clock, canonical scripted phrase, a configured PhraseBuffer+HandoverDetector with design defaults). Confirm `config.py` exposes M2 thresholds (settle=700, hard=3000, poll=30, trigger_cc=67) as source-of-truth. | `conftest.py` fixtures; `config.py` M2 tunables block + citation comment | M2.4, M2.6 | Fixtures import cleanly and are consumed by M2 tests; defaults read 700/3000/30/67; thresholds flow from config into `HandoverDetector` (no hard-coded literals in `handover.py`) | `test_config.py::test_m2_defaults` |
| M2.9 | Concurrency-discipline guard, TWO variants: (a) DETERMINISTIC - the callback append path and the poll-read path concurrently against one `PhraseBuffer` (fake clock + real threads), asserting no torn reads / no lost events / no deadlock; (b) STRESS - a real append path and a real-time poll loop with a real (short) `time.sleep` and many iterations across repeated runs, asserting a consistent final buffer and no deadlock, so the real 30ms-wakeup interleaving against the native callback (which the fake clock erases) gets exercised at least loosely. Document the single-writer rule for `last_event_time`. Wire M2 modules into the CI pytest-on-push workflow. | `test_concurrency.py` (deterministic + stress) + M2 tests in CI | M2.7, M2.8 | The deterministic test passes repeatedly with no deadlock + consistent final buffer; the stress variant runs many real-time iterations across repeated runs with no deadlock and a consistent buffer; CI runs the full M2 offline suite green on push using `requirements.txt` only | `test_concurrency.py::test_callback_and_poll_no_torn_state` (fake clock) + `test_concurrency.py::test_realtime_poll_stress_no_deadlock` (real sleep, repeated) |

### M3 - Heuristic responder + scheduler (the core demo, ~1d)

Turn a frozen phrase into a musically coherent in-key answer and stream it back to
Agent Out with absolute-target timing. `theory.py`, `HeuristicResponder` (MotifAnalyzer
+ response menu), `humanize()`, the worker-thread scheduler. THE CORE DEMO.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M3.1 | Freeze the `MusicalContext` contract in `theory.py`: frozen dataclass with `key_pc`, `mode`, `scale_pcs`, `key_confidence`, `tempo_bpm`, `median_ioi_s`, `tempo_confidence`, source-phrase reference (e.g. velocity-envelope summary). Factory stubs + field docstrings citing design section 6. No estimation logic. | `MusicalContext` frozen dataclass | - | Importable, frozen (mutation raises), exposes all listed fields; a hand-built instance round-trips | `test_theory.py::test_musical_context_shape_and_frozen` |
| M3.2 | Scale-snap + transpose helpers in `theory.py`: `snap_to_scale(pitch, scale_pcs)` (deterministic tie-break), `transpose_in_key(pitch, diatonic_steps, ctx)`, `is_in_scale(pitch, ctx)`. The coherence primitives every transform routes through; build before the menu. | `snap_to_scale`/`transpose_in_key`/`is_in_scale` | M3.1 | `snap_to_scale` never returns out-of-scale; in-scale pitch unchanged; `transpose_in_key` by a diatonic third on a known C-major phrase lands correct; tie-break deterministic | `test_theory.py::test_scale_snap_and_transpose` |
| M3.3 | Duration-weighted key/scale estimation: 12-bin pitch-class histogram weighted by each note's duration, correlate against normalized Krumhansl-Schmuckler major/minor profiles across 24 rotations, pick best `(tonic, mode)`, derive `scale_pcs`; `key_confidence` from the best-vs-second margin. Pure stdlib (no numpy). | `estimate_key(phrase) -> (key_pc, mode, scale_pcs, key_confidence)` | M3.1 | Canonical C-major / A-minor phrases return the expected tonic+mode above the floor; duration-weighting demonstrable (a long tonic vs many short passing tones does not flip the key) | `test_theory.py::test_key_estimation_duration_weighted` |
| M3.4 | Key confidence floor + fallback: if `key_confidence < key_conf_floor`, fall back to `last_known` or a `--key` lock rather than answering out of key; emit the fallback with a flag/low confidence. Out-of-key is the single most audible failure, so this guard is mandatory. | Key-confidence fallback path | M3.3 | A 3-note sparse phrase yields below-floor confidence and returns the supplied `last_known`/lock, not a guess; with neither, the documented default | `test_theory.py::test_key_confidence_fallback` |
| M3.5 | Median-IOI tempo + confidence floor: inter-onset intervals from sorted `start_s`, median -> pulse -> `tempo_bpm`; `tempo_confidence` from IOI regularity. Below floor or too few onsets -> fall back to prior spacing / fixed grid, lower confidence. Honest median-IOI "smart echo", NOT beat induction. | `estimate_tempo(phrase) -> (tempo_bpm, median_ioi_s, tempo_confidence)` | M3.1 | Even onsets -> expected median IOI + high confidence; irregular -> below-floor fallback; `<2`-onset phrase -> safe None | `test_theory.py::test_tempo_median_ioi_and_floor` |
| M3.6 | Compose `build_context(phrase, last_known=None, key_lock=None, cfg=...) -> MusicalContext`: run key (+floor/fallback) + tempo (+floor/fallback), pack with a velocity-envelope/register summary. The single HANDOVER-time entry point agent.py calls; the only theory surface responders depend on. | `build_context` | M3.2, M3.4, M3.5 | Canonical phrase -> fully populated context; `last_known`/`key_lock` thread through; output consumed unchanged by `HeuristicResponder` | `test_theory.py::test_build_context_end_to_end` |
| M3.7 | Implement `MotifAnalyzer` in `responder.py`: extract interval contour, rhythm cells (literal IOIs = smart-echo template), last-N-note tail motif, phrase center pitch, velocity/register envelope. Pure analysis. | `MotifAnalyzer` | M3.1 | Known ascending phrase -> expected positive deltas, tail motif = last-N, correct center, rhythm template = literal onset spacing | `test_heuristic.py::test_motif_analyzer` |
| M3.8 | Freeze the `Responder` ABC + deterministic RNG seam: `respond(phrase, ctx) -> list[NoteRecord]` anchored at t=0 (offsets from 0). Thread a seeded RNG/config so `HeuristicResponder`/`humanize` are deterministic-testable. Confirm the signature matches design section 4 so M5/M6 swap through the same seam. | `Responder` ABC + seeded-RNG plumbing | M3.1 | Abstract (not instantiable); a trivial subclass returns notes with first `start_s == 0.0`; same seed -> identical output | `test_heuristic.py::test_responder_abc_contract` |
| M3.9 | Four response-menu transforms as pure functions over `(motif, ctx)` returning t=0-anchored NoteRecord lists, every pitch via `snap_to_scale`: (1) transpose tail motif a diatonic third in-key; (2) mirror/invert contour around center; (3) arpeggiate the implied chord in-scale; (4) harmonize with diatonic thirds/sixths. Each reuses the onset-spacing template + echoes velocity/register. | `transpose_in_key`/`mirror`/`arpeggiate`/`harmonize` transforms | M3.2, M3.7, M3.8 | Each on a known C-major phrase emits only in-scale pitches, starts at t=0, dangling-free, reuses the rhythm template; mirror reflects around center; harmonize adds the correct diatonic interval | `test_heuristic.py::test_response_menu_transforms` |
| M3.10 | Assemble `HeuristicResponder.respond(phrase, ctx)`: run `MotifAnalyzer`, select a transform (default restate-then-vary: echo rhythm grid, transform pitch in-key; menu selectable/weighted via seeded RNG), return the in-key answer at offsets from 0. Off-tonic-ending question phrases bias toward a tonic resolution. Deterministic given phrase+ctx+seed. | `HeuristicResponder` (v1 default engine) | M3.6, M3.9 | Same (phrase, ctx, seed) -> byte-identical list; every pitch in `ctx.scale_pcs`; dangling-free; first event at t=0; off-tonic-ending biases toward tonic | `test_heuristic.py::test_heuristic_determinism_inkey_danglingfree` |
| M3.11 | Implement `humanize()` as a single post-pass: small Gaussian micro-timing + velocity jitter (seeded RNG) + "leave space" (occasional rests). Tunable/bypassable via config. Must preserve `start_s < end_s` and never push `start_s < 0` (clamp). | `humanize()` (engine-agnostic, seedable, bypassable) | M3.8 | Fixed seed deterministic; jitter within bounds; no dangling/no negative start; bypass returns the input unchanged | `test_heuristic.py::test_humanize_bounds_and_bypass` |
| M3.12 | Grow `tests/fake_port.py` into a full output-capturing `MidiOut` double with injectable clock: records every `(message, emit_perf_counter)` pair; tests advance/inspect a fake `perf_counter` so absolute-target sleeps are assertable without real waits. Provide a conftest scheduler fixture. NOTE: this EXTENDS the same `tests/fake_port.py` created in M1.8 and grown in M2.4, so it depends on M2.4's injectable-clock seam; it is independent of the M3 theory/responder tracks but is NOT a no-dependency leaf. Do not edit this file in parallel with M2.4. | Output-capture + injectable-clock; scheduler fixtures | M2.4 | A scripted set of emits is recorded with timestamps; the injectable clock is read in place of `time.perf_counter`; fixture consumable by `test_scheduler` without real hardware/waits | `test_scheduler.py::test_fake_port_records_emits` |
| M3.13 | Worker-thread scheduler in `scheduler.py` honoring coordinate-contract clause 3: on RESPOND capture `play_t0 = perf_counter()`; for each note sleep to the ABSOLUTE target `sleep(max(0, (play_t0 + note.start_s) - perf_counter()))` then emit note_on; schedule note_off at `play_t0 + note.end_s` the same absolute way. NEVER sum per-note sleeps. Use the injectable clock. Send via the `ports.py` primitive. To make the no-drift guarantee actually falsifiable, the scheduler must record, per emit, the ABSOLUTE target it slept toward (so a test can assert each target == `play_t0 + note.start_s` exactly, independent of clock readings) rather than only the emit timestamp. | Worker-thread player with absolute-target sleeps + a per-emit recorded absolute target | M3.12 | (1) STRUCTURE: each recorded sleep target equals `play_t0 + note.start_s` exactly (and note_off target == `play_t0 + note.end_s`), proving targets are computed absolutely, never as a running sum; (2) under the fake clock every emit timestamp tracks `play_t0 + offset` within tolerance; (3) under a short REAL clock (a handful of notes, real `time.sleep`) emit perf_counter timestamps stay within tolerance of the absolute targets and the error does not accumulate across notes; (4) ordering correct; emits through fake Agent Out; (5) code-reviewed for any cumulative/running-sum addition of sleep durations (none allowed) | `test_scheduler.py::test_absolute_target_no_drift` (fake clock, asserts the recorded targets structurally) + `test_scheduler.py::test_realclock_no_accumulated_drift` (short real-clock run, asserts no accumulation) |
| M3.14 | Sounding-note tracking + `cleanup()` hook: maintain the set of sounding `(pitch, channel)` note_ons (added on emit, removed on note_off); `cleanup()` sends explicit note_offs for every still-tracked note + CC123 on all 16 channels of Agent Out. Wrap the emit loop in try/finally so cleanup runs on normal completion and on exception. (Full atexit/SIGINT wiring is M4.) | Sounding-note tracking + `cleanup()`, try/finally emit loop | M3.13 | After a normal response the sounding set is empty; a mid-response exception triggers cleanup so every note_on has a matching note_off (+ CC123 x16); no stuck note | `test_panic.py::test_mid_response_exception_no_stuck_notes` |
| M3.15 | Wire HANDOVER->RESPOND in `agent.py`: on the M2 handover event call `build_context`, then `respond`, then `humanize`, then hand the offset-from-0 list to the scheduler; on completion return to LISTEN and clear the buffer; persist the detected key as `last_known` for the next turn's fallback. Makes turn-taking loop without a restart. (Reclaim/echo-guard/full panic are M4.) | HANDOVER->RESPOND->LISTEN happy-path wiring | M3.10, M3.11, M3.14 | Driven offline, a captured phrase produces an in-key response on Agent Out, then returns to LISTEN with a cleared buffer; a second phrase loops without restart; `last_known` carries forward | `test_scheduler.py::test_handover_to_respond_loop` |
| M3.16 | Add M3 config defaults (`key_conf_floor`, `tempo_conf_floor`, `response-bars`, humanize on/off + jitter bounds, default `responder='heuristic'`, RNG seed) as a single source-of-truth block citing design 5.0/6, via argparse, consumed by theory/responder/scheduler. Run the full offline suite green; confirm CI installs `requirements.txt` only. | M3 tunables + green offline suite under CI | M3.6, M3.10, M3.11, M3.13, M3.14, M3.15 | `pytest` runs theory/heuristic/scheduler/panic green with no hardware; defaults match design literals and are read by every M3 module; CI installs only `requirements.txt` + pytest | manual (run pytest + read CI logs) |
| M3.17 | Manual hardware verification of the core demo in Reaper: run the agent, arm a track on Agent In with input-monitoring/thru OFF, play a phrase, confirm an audible in-key editable-MIDI response recorded on Agent Out, then that turn-taking loops without restart. The one hardware step that proves M3 acceptance. | Confirmed play->in-key-reply->editable-MIDI round-trip | M3.15, M3.16 | A played phrase yields a coherent in-key reply recorded as editable notes on Agent Out; a second phrase loops without restart; no stuck notes after a normal turn | manual |

### M4 - Trigger + safety + polish (PoC complete, ~0.5-1d)

Harden interaction and safety: CC67/CC64 + hotkey handover atop the silence ladder;
RESPOND-state reclaim (barge-in) made safe via the echo-guard; guaranteed no stuck
notes on any exit; every tunable a config flag; a per-OS/per-DAW README.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M4.1 | CONSOLIDATE (do NOT re-declare) the M2/M3 defaults plus all remaining tunables into one final `Config` dataclass + argparse, the single source-of-truth block citing design 5.0/5.1. There must be ONE defaults block from M2 onward (M2.8 seeds it, M3.16 appends, M4.1 finalizes); M4.1 only APPENDS the new fields and must not silently restate or fork the earlier M2/M3 values. Existing fields: `trigger_cc` (67), `silence_ms` (700), `hard_ms` (3000), `poll_ms` (30), `response_bars`, `responder` ('heuristic'), `port_names` (('Agent In','Agent Out')), `key` (None), key/tempo floors + humanize bounds + RNG seed (from M3.16). New fields: `hotkey` (e.g. space), `echo_window_ms` (150), `trigger_cc_threshold` (>=64). Every flag a `--kebab-case` form; the dataclass is the only place defaults live. | Final consolidated `Config` + `build_config(argv)` parser (one defaults block, M4 appends only) | - | `python agent.py --help` lists every flag; `Config()` with no args yields the design-literal defaults; each flag overrides exactly its field; the design-literal M2/M3 values (700/3000/30/67 + the M3 floors) are UNCHANGED through the consolidation (no drift between M2/M3 and M4) | `test_config.py`: representative argv round-trips every field; defaults match 700/3000/30/67/150; an explicit assertion that the consolidated M2/M3 design-literal values are unchanged from their M2/M3 declarations |
| M4.2 | Extract the all-notes-off logic into a single idempotent `panic_cleanup(send_fn, sounding_notes, lock)`: explicit note_off for every tracked sounding `(pitch, channel)` on Agent Out, then CC123 on all 16 channels; guard with a "cleaned" flag (second call is a no-op); copy-under-lock, send outside the lock to avoid deadlock from a signal handler. | `panic_cleanup()` reused by exit handlers, reclaim-abort, try/finally | - | Calling twice sends the offs once and is harmless the second time; a known sounding set emits exactly one note_off each + 16 CC123s | `test_panic.py` (part 1): seed a sounding set, cleanup -> one note_off each + CC123 x16; call again -> no additional sends |
| M4.3 | Wire guaranteed exit cleanup in `agent.py`: atexit + SIGINT/SIGTERM handlers (main thread) + try/finally around the state loop and scheduler emit loop, all routing to `panic_cleanup`. The signal handler does minimal work (set stop flag + cleanup), then exits. | atexit + signal handlers + try/finally around `run()` | M4.2 | Normal exit, unhandled exception, simulated SIGINT each invoke cleanup exactly once (cleaned-flag prevents doubles); no exit path skips it | `test_panic.py` (part 2): exception mid-response via real scheduler+fake_port -> every note_on matched; invoke SIGINT handler directly -> cleanup ran + idempotent |
| M4.4 | Primary trigger-CC handover in `handover.py` (callback path per design 5.0): on `control_change` where `control == cfg.trigger_cc` and `value >= cfg.trigger_cc_threshold`, fire handover immediately (independent of and ahead of the silence/hard ladder, which stays the always-on baseline). Callback only flags; never sleeps/blocks. | Trigger-CC branch in the callback path | M4.1 | A CC67 `>=64` fires handover on the next tick even far from silence expiry; CC67 `<64` or a different CC does not; the silence ladder still fires when no trigger arrives | `test_handover.py` (extend): trigger CC fires immediately; sub-threshold/wrong-CC do not; silence ladder still fires (no regression) |
| M4.5 | Hotkey handover fallback as an additive, optional source: a small listener (terminal raw-mode stdin on a daemon thread) that on the configured `--hotkey` calls the same `fire_handover()` path. Scoped to terminal focus, gated so it is purely additive (silence ladder stays the no-hardware baseline). Document the focus caveat in code + README. | Hotkey-listener thread mapping the key to `fire_handover()` | M4.4 | Pressing the hotkey ends the turn exactly like the pedal; disabling/omitting it changes nothing about silence-ladder behavior | manual (real keypress) + a thin unit test that the hotkey-callback invokes `fire_handover()` when called directly |
| M4.6 | Echo-guard in `scheduler.py` per design 5.1: while in RESPOND, record every emitted note_on as `(pitch, channel, emit_perf_counter)`; expose `is_echo(pitch, channel, now)` returning True if a matching output note was emitted within `cfg.echo_window_ms`. Incoming matching note_ons are ignored for reclaim; reclaim is only considered for a trigger CC or a non-matching note. KNOWN LIMITATION to document: `is_echo` matches on `(pitch, channel)` only, so a human legitimately replaying the SAME pitch within `echo_window_ms` is indistinguishable from an echo and is intentionally swallowed; a same-pitch reclaim JUST AFTER the window must abort. | Emitted-output ledger + `is_echo()` + a documented same-pitch-within-window limitation | M4.1 | (1) An incoming note_on identical to one emitted `< echo_window_ms` ago -> `is_echo` True; (2) the same note AFTER the window, or a different pitch -> False; (3) the same-pitch-within-window swallow is documented as a known limitation in code + README | `test_feedback.py` (part 1): emit a response, feed those exact note_ons back within the window via the injectable clock -> `is_echo` True, no reclaim; non-echo note -> False; AND the false-negative BOUNDARY case - a same-pitch note just AFTER `echo_window_ms` -> `is_echo` False (reclaim proceeds); plus an explicit test documenting that within-window same-pitch IS swallowed (known limitation) |
| M4.7 | Wire reclaim/barge-in into RESPOND: during RESPOND, a trigger CC (re-press) OR a note where `is_echo()==False` cancels the scheduler worker, routes the abort through `panic_cleanup` (all-notes-off, no dangling), clears the buffer, returns to LISTEN. A matching (echo) note is ignored. Reuse the cleanup primitive so barge-in cannot become a new stuck-note source. | RESPOND -> abort+cleanup -> LISTEN on genuine reclaim, no-op on echo | M4.3, M4.6 | A non-echo note (or re-pressed trigger CC) mid-RESPOND stops emission, sends all-notes-off, returns to LISTEN with a cleared buffer; an echoed note does not abort; the aborted response leaves no sounding note | `test_feedback.py` (part 2): non-echo note mid-RESPOND aborts to LISTEN with zero sounding notes; echo note does not abort; trigger-CC re-press aborts |
| M4.8 | Finalize the per-OS/per-DAW `README.md`: setup + venv + install; run command + a flag reference table (M4.1); macOS (CoreMIDI) and Linux (ALSA own-port quirk + stale-port recovery) sections; per-DAW arming (Reaper primary, plus Ableton/Bitwig/Logic) including input-monitoring/MIDI-thru OFF; Windows loopMIDI workaround (two loopback ports via `--port-names`); feedback/thru warning (never route Agent Out into Agent In). No em dashes. | Complete per-OS + per-DAW onboarding doc | M4.1 | A reader on the build OS can go clone -> working duet from the README; every CLI flag documented; thru/feedback warning + Linux quirk present; no em dashes | manual (doc review); optional no-em-dash CI grep |
| M4.9 | Add the M4 tests to the CI workflow (core deps only) and run the full offline suite locally + in CI green: `test_config`, extended `test_handover` (trigger CC), `test_feedback` (echo-guard + reclaim), `test_panic` (mid-response exception + idempotent + simulated-signal), no regression in theory/heuristic/scheduler. | Green CI on the full M1-M4 offline suite | M4.1, M4.3, M4.4, M4.6, M4.7 | `pytest` passes locally and the Actions run is green on push; the workflow installs core deps only (no anthropic/transformers) | none (aggregation/CI; tests written in M4.1-M4.7) |
| M4.10 | Single manual acceptance gate in Reaper: arm a track on Agent In (input-monitoring/thru OFF); confirm a full turn-taking loop without restart using each handover mode (pedal CC67, silence ladder, hotkey); verify barge-in aborts cleanly; verify Ctrl-C mid-response leaves no stuck note; deliberately enable MIDI-thru briefly to confirm the echo-guard prevents self-abort. CRITICAL echo-guard sizing step: with thru ON, MEASURE the actual DAW-thru round-trip latency (emit on Agent Out -> re-arrival on Agent In, e.g. by logging the perf_counter delta) and confirm it is BELOW the chosen `--echo-window-ms`; if real thru latency exceeds the window the guard never matches and silently does nothing, so adjust `--echo-window-ms` upward (and record the measured value). Tune `--silence-ms`/`--echo-window-ms` if real-instrument feel warrants. Record verified dep versions + the measured thru latency into the README; update STATUS to "M4 complete / PoC done". Log an ADR only if a locked default changes. | Verified working PoC; measured DAW-thru latency vs window recorded; README versions filled; STATUS updated; optional tuning ADR | M4.5, M4.7, M4.8, M4.9 | Live in Reaper: all three handover modes work; turn-taking loops without restart; barge-in clean; Ctrl-C leaves no hanging note; echo-guard verified with thru ON AND the measured thru round-trip latency is recorded and confirmed BELOW `--echo-window-ms` (window correctly sized vs real latency, not just "agent does not self-abort"); in-key editable MIDI recorded. Meets every scope.md AC | manual (the one hardware/DAW gate) |

### M5 - Local AMT engine (OPTIONAL post-PoC, ~1-2d)

`AmtResponder` behind the `Responder` ABC: the Anticipatory Music Transformer
(`stanford-crfm/music-medium-800k`), guarded import, `FallbackResponder`-wrapped,
melody-conditioned. Default path unchanged; opt-in via `--responder amt`; deps live
only in `requirements-model.txt`.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M5.1 | Create `requirements-model.txt` with floors for the AMT stack (`transformers>=`, `torch>=`, `anticipation>=` per design section 8); document NOT installed by default; record verified resolved versions. Confirm CI still installs only `requirements.txt`. | `requirements-model.txt` + README install stanza + versions note | - | `pip install -r requirements-model.txt` resolves in a throwaway venv; a default install does NOT pull torch/transformers/anticipation; CI unchanged and green on core deps | manual |
| M5.2 | Spot-check the model artifact: confirm `stanford-crfm/music-medium-800k` reachable on HuggingFace, note size + `from_pretrained` cache path, do the 2-minute license-tag check (precondition for any paid build). Decide + document device selection (cpu/cuda/mps auto) and the default response-length cap (~2 bars for CPU latency). | Provenance+license note + device-select + response-length default | M5.1 | `from_pretrained("stanford-crfm/music-medium-800k")` loads once in a scratch script; license tag recorded; device rule + length cap written into config plan | manual |
| M5.3 | `NoteRecord <-> temp .mid` bridge: `phrase_to_tempmid(phrase) -> Path` and `tempmid_to_notes(path) -> list[NoteRecord]` (re-based so earliest `start_s == 0`, `start_s < end_s` enforced). Reuse the existing mido write/read (no second serialization path); route temp files through a gitignored, cleaned-up dir. | Model-free conversion helpers with t=0 re-basing + dangling-free invariant | - | A known list -> `.mid` -> list preserves pitch/velocity/channel and relative timing within tolerance; output re-based to `min(start_s)==0`, every `start_s < end_s` | `test_amt_bridge.py`: round-trip preserves pitches/relative timing, re-bases to t=0, dangling-free |
| M5.4 | Implement `AmtResponder(Responder)` with a GUARDED lazy import (`transformers` + `anticipation.convert.midi_to_events/events_to_midi` + `anticipation.sample.generate` imported inside `__init__`/first `respond()`, so an absent package raises a catchable ImportError). Lazy-load + cache the model. `respond()` wires the section-4.4 round-trip: phrase -> tempmid -> `midi_to_events` (history) -> `generate(model, start_time=t_end, end_time=t_end+resp_len, inputs=history, top_p=.98)` -> `events_to_midi` -> `tempmid_to_notes` -> notes at t=0. Do NOT import MidiTok. | `AmtResponder` (guarded import + lazy load + round-trip) | M5.2, M5.3 | With the model installed, `respond()` returns a non-empty t=0-anchored list; with the package absent, `responder.py` still imports and constructing `AmtResponder` raises ImportError (no module-level crash) | `test_amt_responder.py`: (a) absent anticipation -> construction raises ImportError, module still imports; (b) `generate()` mocked to canned events -> t=0-anchored dangling-free notes |
| M5.5 | Apply shared post-passes to AMT output: scale-snap every returned pitch to `ctx`'s key (the same guard for stray model notes), then `humanize()`. Reuse the existing `theory.scale_snap` + `responder.humanize` (no reimplementation). Make scale-snap toggle-able if humanize already is. | AMT output routed through the existing scale-snap + humanize | M5.4 | Every pitch in `AmtResponder` output (canned-events test) is in `ctx`'s scale after snapping; humanize applied within bounds; the same helpers as `HeuristicResponder` are called | `test_amt_responder.py` (extend): in-key after snap on canned out-of-key events; humanize bounds respected |
| M5.6 | Wire `--responder amt` through `config.py` + the responder factory: construct `AmtResponder`, wrap in `FallbackResponder(primary=AmtResponder, fallback=HeuristicResponder, timeout_s=...)` so ImportError/exception/timeout drops to heuristic. Add `--amt-model` (default `stanford-crfm/music-medium-800k`), `--amt-device` (auto), `--amt-response-len`/response-bars cap, `--amt-top-p` (.98), `--amt-timeout`. Default `--responder` stays heuristic. | Factory + config so `--responder amt` yields a wrapped `AmtResponder`; amt-* tunables | M5.4 | `--responder amt` with deps installed runs AMT end to end; with deps absent it logs the fallback warning and produces a heuristic answer instead of crashing; default run is the heuristic path | `test_fallback.py` (extend): a wrapper whose primary raises ImportError returns the heuristic result + logs a warning; factory builds the wrapped chain |
| M5.7 | Decide + implement the timeout/isolation posture: in-process blocking inference cannot be safely thread-killed mid-CUDA-kernel. EITHER run `generate()` in a `multiprocessing` worker so `--amt-timeout` can terminate a slow generation, OR document timeout as best-effort and rely on the heuristic default. Whichever is chosen, it is tested or documented, not ambiguous. | Process-isolated AMT path with a real timeout, OR an explicit documented best-effort decision | M5.6 | If isolated: a hung `generate` is terminated at `--amt-timeout` and the heuristic answer returns; if deferred: the limitation is written down and the heuristic-default safety net verified | `test_fallback.py` (extend): a primary sleeping past timeout yields the heuristic result within timeout+margin (isolated path); else manual + documented |
| M5.8 | Adapt AMT for call-and-response: feed the captured phrase as conditioning history and constrain `generate()` to the response window (`start_time=t_end..t_end+resp_len`) so the model answers AFTER the phrase, then re-base to t=0. Cap response length to the configured bars. Document the prefill-during-listen optimization as a no-op stretch hook (NOT v1). | `generate()` shaped for call-and-response + a documented no-op prefill hook | M5.4 | Generated notes start after the conditioning phrase's end in model time and re-base to t=0; length respects the bars cap; prefill hook present as a documented no-op | `test_amt_responder.py` (extend): `generate()` called with `start_time >= phrase t_end` and bounded `end_time` (assert on mocked args); output re-based to t=0 |
| M5.9 | Update README + STATUS for the AMT engine: install via `requirements-model.txt`, `--responder amt` usage, device/latency note (GPU/Apple Silicon fast; strong laptop CPU ~1-3s, keep responses ~2 bars on CPU), first-run model-download note, the fallback behavior when deps are missing, the Apache-2.0-weights-confirm-before-paid-build caveat. No em dashes. Mark M5 in STATUS. | README AMT section + STATUS update | M5.6, M5.8 | A reader can install the model deps, run `--responder amt`, and knows latency/download/license expectations; STATUS reflects M5 | manual |
| M5.10 | Manual hardware acceptance: install `requirements-model.txt`, run `--responder amt` against Reaper, play a phrase, confirm an audible in-key editable-MIDI model-composed response loops without restart; confirm the fallback path (disable deps -> heuristic with a logged warning). CRITICAL posture check (ties M5.7 to reality): observe ONE real CPU `generate()`'s wall-clock latency under load and confirm the loop behavior DURING it matches whichever M5.7 posture was chosen - if process-isolated, a deliberately slow/hung generate is terminated at `--amt-timeout` and the heuristic answer returns; if best-effort, the loop BLOCKS for that generate and the observed worst-case block time is recorded in STATUS so the limitation is concrete, not theoretical. Note observed latency. | Verified live AMT demo + confirmed graceful degradation + a recorded real-CPU-generate latency and observed loop behavior matching the M5.7 posture (block time in STATUS if best-effort) | M5.5, M5.6, M5.7, M5.8, M5.9 | DAW records a coherent in-key model-composed reply via `--responder amt`; loop survives multiple turns; runs without GPU (CPU OK); disabling deps degrades to heuristic; one real CPU generate's wall-clock latency is recorded AND the loop behavior during it matches the chosen M5.7 posture (timed-out-to-heuristic if isolated; observed worst-case block time recorded in STATUS if best-effort) | manual |

### M6 - Claude API engine (OPTIONAL, needs key, ~0.5-1d)

`ClaudeResponder` behind the `Responder` ABC: a direct Anthropic Messages API call
(Haiku), JSON NoteRecords via tool-use, streamed note-by-note, `FallbackResponder` +
scale-snap/humanize wrapped. Selected via `--responder claude`; needs
`ANTHROPIC_API_KEY` + `requirements-claude.txt`, never installed by default.

| Id | Task | Produces | Depends-on | Acceptance | Test |
|---|---|---|---|---|---|
| M6.1 | Create `requirements-claude.txt` as a floor for `anthropic>=` only, NOT referenced by `requirements.txt` and NOT installed by CI; add a one-line README install note. | `requirements-claude.txt` + README note | - | Default install does NOT pull anthropic; `pip install -r requirements-claude.txt` installs the SDK; `requirements.txt` has no anthropic reference; CI installs only `requirements.txt` | none |
| M6.2 | Verify the current Anthropic model id + SDK surface against the live docs/SDK (NOT memory): the fastest Haiku model id (design cites `claude-haiku-4-5`), the `messages.stream`/tool-use streaming event shape, `cache_control`, the `input_json_delta`/partial-tool-input events. Record verified model id + SDK version + event names in an inline comment block + the README verified-versions section. | Verified model id, SDK version, streaming/tool-use event-name notes | M6.1 | The model id and named events match the installed SDK's documented API (cross-checked, not memory); the recorded version is the verified one | manual |
| M6.3 | Define static prompt assets: `MUSICIAN_SYSTEM` (musician persona + a non-folk style hint + the JSON note-schema description, written for prompt-cache stability) and `RESPOND_TOOL` (a tool-use schema whose single input is a notes array of `{pitch 0-127, velocity 0-127, start_s>=0, end_s>start_s, channel 0-15}` matching NoteRecord). Mark `MUSICIAN_SYSTEM` with `cache_control: ephemeral`. | `MUSICIAN_SYSTEM` + `RESPOND_TOOL` constants | M6.2 | `RESPOND_TOOL` is a valid schema mapping 1:1 onto NoteRecord ranges with `start_s < end_s`; `MUSICIAN_SYSTEM` is a stable string with a non-folk style hint + schema description; `cache_control` set | `test_claude.py::test_respond_tool_schema_matches_noterecord` |
| M6.4 | Serialization helpers: `phrase_to_json(phrase)` -> compact JSON note-dict array for the user message, `context_block(ctx)` -> a compact key+tempo+last-phrase summary. Keep carried context minimal (no full-history accumulation). | `phrase_to_json()` + `context_block()` pure functions | M6.3 | `phrase_to_json` round-trips a known list to JSON matching inputs; `context_block` emits key+tempo+last-phrase only and omits earlier turns; both pure (no SDK import, no network) | `test_claude.py::test_phrase_serialization_roundtrip` + `::test_context_block_is_compact` |
| M6.5 | Client-injection seam: `ClaudeResponder.__init__(self, client=None, model=<verified id>, max_tokens=600, snap=True)`. When `client is None`, lazily construct `anthropic.Anthropic()` inside a guarded import so a missing SDK/key raises a clean catchable error rather than an import-time crash; tests pass a `FakeAnthropicClient`. | `ClaudeResponder` constructor + guarded lazy import | M6.2 | Importing `responder.py` with anthropic NOT installed succeeds (no top-level import); constructing with a missing SDK raises a catchable error (caught by FallbackResponder); an injected fake client never imports anthropic | `test_claude.py::test_import_without_anthropic_sdk` |
| M6.6 | Streaming tool-use parser as a generator: `iter_response_notes(stream)` yields a completed NoteRecord each time the accumulated tool-input JSON closes one note object. Accumulate `input_json_delta` fragments, parse defensively, drop-and-continue on a malformed/out-of-range note. Consumes the events verified in M6.2. | `iter_response_notes()` incremental parser with drop-and-continue | M6.3, M6.5 | Fed a scripted partial-JSON delta sequence it yields NoteRecords in order, emits the first before the stream completes, and silently drops a bad note without raising | `test_claude.py::test_streaming_parser_yields_incrementally` + `::test_streaming_parser_drops_bad_notes` |
| M6.7 | Implement `ClaudeResponder.respond(phrase, ctx)`: build the request (`system=MUSICIAN_SYSTEM` cached, `tools=[RESPOND_TOOL]`, `max_tokens`, user content = `phrase_to_json` + `context_block`), open `client.messages.stream`, drive `iter_response_notes`, then apply scale-snap + humanize. Return offsets-from-0; reuse M3 streaming-to-scheduler wiring. | Complete `respond()` honoring the ABC + coordinate contract + scale-snap/humanize | M6.4, M6.6 | With a `FakeAnthropicClient` returning a scripted in-tool note list, `respond()` returns a t=0-anchored list, every pitch in `ctx` key after snapping, `start_s < end_s`, and an injected out-of-key note comes back snapped | `test_claude.py::test_respond_in_key_and_anchored` + `::test_respond_snaps_stray_note` |
| M6.8 | Register `ClaudeResponder` in the factory: `--responder claude` builds `FallbackResponder(primary=ClaudeResponder(...), fallback=HeuristicResponder(), timeout_s=None)` so any ImportError/missing-key/network/parse failure drops to the heuristic. Wire `--claude-model` (default = verified Haiku id) into argparse. No new live-loop path in `agent.py` beyond engine selection. | Factory wiring + config flags with guaranteed FallbackResponder wrapping | M6.5, M6.7 | `--responder claude` with no key / no SDK runs the loop and answers via the heuristic (logged warning), never crashes; with a fake key+client it answers via Claude; `--responder heuristic` unchanged | `test_claude.py::test_factory_falls_back_without_key` + `::test_factory_uses_claude_with_client` |
| M6.9 | Add `FakeAnthropicClient` (`tests/fake_anthropic.py`): a minimal stand-in exposing `messages.stream(...)` as a context manager replaying a scripted list of streaming events (`input_json_delta` fragments + `message_stop`), plus a failure mode (raise on enter) to exercise the fallback. Reuse the existing conftest fixtures; no network or key. | `FakeAnthropicClient` + a conftest fixture | M6.2 | The fake client drives `iter_response_notes` and `respond` end-to-end with zero network and no `ANTHROPIC_API_KEY`; its raise-on-enter mode triggers the FallbackResponder path | `test_claude.py::test_fake_anthropic_replays_scripted_stream` |
| M6.10 | One OPTIONAL live smoke (`scripts/claude_smoke.py` or `-m`, guarded behind an env flag / `skipif(no ANTHROPIC_API_KEY)`): send one canonical phrase to the real Haiku model, assert a non-empty in-key list within a sane timeout, print phrase->first-note and phrase->complete latency. The only network/key-touching step; never in default CI. | Optional live smoke + a recorded latency/quality observation | M6.7, M6.8 | With a real key the smoke returns an in-key list and prints both latencies; with no key it is skipped; default `pytest` stays green | manual (skipif-gated; not in default CI) |
| M6.11 | Fill the README Claude-engine section: install `requirements-claude.txt`, export `ANTHROPIC_API_KEY`, run with `--responder claude` (and `--claude-model`), the verified model id + SDK version, the cost note (~fraction of a cent/turn on Haiku), the fallback-on-no-key behavior, and an explicit pointer that subscription/Claude-Code is NOT a live-loop engine. No em dashes. | Completed README Claude-engine subsection | M6.8, M6.10 | A reader with a key can install, set the env var, and run `--responder claude` from the README alone; the no-key fallback + cost/latency caveats stated; no em dashes | manual |

---

## 6. Critical path and recommended session order

### Critical path

```
M1.0 -> M1.1 -> M1.2 -> M1.4 -> M1.7 -> M1.10
     -> M2.2 -> M2.3 -> M2.6 -> M2.7
     -> M3.6 -> M3.10 -> M3.13 -> M3.14 -> M3.15 -> M3.17
     -> M4.2 -> M4.3 -> M4.6 -> M4.7 -> M4.10
```

The PoC critical path ends at M4.10 (shippable). M5 and M6 are off the critical path.

### Recommended session-by-session order

| Session | Scope (est) | Tasks in order | Gate |
|---|---|---|---|
| 1 | M1, ~0.5d - Spine proof | M1.0 greenlight+lock-defaults (BLOCKING, business-scope), M1.1 skeleton, M1.2 pin+install (de-risk the compiled wheel early), M1.3 freeze contracts, M1.8 fake_port stub. Then M1.4 two ports, M1.5 same-name warning, M1.6 distinct C-major emitter, M1.7 panic/cleanup+logging, M1.9 README scaffold. | G1: M1.10 manual Reaper round-trip; offline contracts/ports/panic-slice green |
| 2 | M2 part A, ~0.5d - Capture core | M2.1 NoteRecord+OpenNote, M2.2 lock-guarded PhraseBuffer, M2.3 snapshot (closeout->normalize->freeze, in that order), M2.4 grow fake_port into injectable-clock + scripted-stream. | (rolls into G2) |
| 3 | M2 part B, ~0.5d - Concurrency + handover | M2.5 native callback path, M2.6 HandoverDetector + poll thread, M2.8 conftest + config M2 defaults, M2.7 wire LISTEN<->HANDOVER + demo print + re-arm, M2.9 concurrency test + add M2 to CI. | G2: M2 offline suite green + one manual live-port smoke |
| 4 | M3 part A, ~0.5d - Music theory | M3.1 freeze MusicalContext, M3.2 scale-snap/transpose (before the menu), M3.3 duration-weighted KS key, M3.4 key-confidence floor + fallback (mandatory), M3.5 median-IOI tempo + floor, M3.6 build_context. | (rolls into G3) |
| 5 | M3 part B, ~0.5d - Heuristic responder | M3.7 MotifAnalyzer, M3.8 Responder ABC + seeded RNG, M3.9 four transforms (all via snap_to_scale, offset-from-0), M3.10 HeuristicResponder restate-then-vary, M3.11 humanize (clamp start_s>=0). | (rolls into G3) |
| 6 | M3 part C, ~0.5d - Scheduler + integration | M3.12 fake_port output-capture + clock, M3.13 absolute-target scheduler (write the no-drift test with/before it), M3.14 sounding-note tracking + cleanup under try/finally, M3.15 HANDOVER->RESPOND->LISTEN loop + persist last_known, M3.16 config + green offline suite. | G3: M3.17 manual Reaper - in-key reply, turn-taking loops, no stuck notes. THE CORE DEMO |
| 7 | M4, ~0.5-1d - Trigger + safety + polish | M4.1 all tunables, M4.2 idempotent panic_cleanup, M4.3 atexit+SIGINT/SIGTERM + try/finally, M4.4 trigger-CC branch, M4.6 echo-guard, M4.7 reclaim routing abort through panic_cleanup, M4.5 hotkey fallback (additive), M4.8 finalize README, M4.9 full suite green in CI. | G4: M4.10 manual Reaper - all three handover modes, barge-in clean, Ctrl-C no stuck note, echo-guard verified with thru ON. SHIPPABLE PoC |
| 8+ | M5, ~1-2d - Local AMT (OPTIONAL) | M5.1 requirements-model.txt + M5.3 .mid bridge (parallel, model-free), then M5.2 spot-check + license, M5.4 AmtResponder, M5.5 post-pass, M5.6 factory + fallback, M5.7 timeout posture (decide, do not leave ambiguous), M5.8 call-and-response conditioning, M5.9 README/STATUS. | G5: M5.10 manual `--responder amt` demo + verified fallback + latency note |
| 9+ | M6, ~0.5-1d - Claude API (OPTIONAL, needs key) | M6.1 requirements-claude.txt, M6.2 VERIFY model id + SDK events (not memory), M6.3 prompt/tool constants, M6.4 serializers, M6.5 injectable-client seam, M6.9 FakeAnthropicClient, M6.6 streaming parser (drop-and-continue), M6.7 respond + scale-snap/humanize, M6.8 factory + fallback, M6.11 README. | G6: offline test_claude green with no key/network; M6.10 OPTIONAL live smoke |

### Parallelizable

- **Global.** The offline fake-port harness is the master enabler: everything except
  the per-milestone manual DAW gates runs offline, so all logic can be built and
  iterated in parallel with DAW access needed only at the four PoC gates.
- **Within M1.** The tooling track (M1.3 contracts, M1.8 fake_port stub) runs in
  parallel with the ports track (M1.4 -> M1.5 -> M1.6 -> M1.7); both only need
  M1.1/M1.2. M1.9 README drafts alongside once M1.2/M1.6/M1.7 land.
- **Within M2.** M2.4 (grow fake_port) is parallel with the capture-data track
  (M2.1 -> M2.2 -> M2.3); they converge at M2.5/M2.6. M2.8 config defaults anytime
  after M2.4.
- **Within M3.** Two independent leaf tracks off M3.1: theory
  (M3.2/M3.3 -> M3.4/M3.5 -> M3.6) and responder analysis (M3.7, M3.8). A third track,
  scheduler tooling (M3.12 -> M3.13/M3.14), depends on M2.4's fake_port injectable
  clock (M3.12 extends `tests/fake_port.py`) but is otherwise independent of the
  theory/responder tracks. Because M3.12 grows the same file as M1.8/M2.4, it must NOT
  be edited in parallel with M2.4. The three tracks join at M3.15.
- **Within M4.** M4.1 config, M4.2 panic_cleanup, M4.6 echo-guard, M4.8 README are
  largely independent; they converge at M4.3/M4.7 and M4.9. M4.5 hotkey is strictly
  additive and can land last.
- **Within M5.** M5.1 (requirements) and M5.3 (.mid bridge, model-free) need no model
  and run up front; M5.2 gates only the model-touching M5.4+.
- **Within M6.** M6.1 reqs, M6.3 prompt/tool constants, M6.4 serializers, M6.9 fake
  client are offline and parallel once M6.2 verifies the SDK surface; they converge at
  M6.6/M6.7.
- **Across milestones.** M5 and M6 are independent of each other and both ride the
  same Responder + FallbackResponder seam frozen in M3.8. Once the PoC ships at G4,
  M5 and M6 can be built in parallel or in either order.
- **README** is incremental (M1.9 scaffold -> filled per milestone -> M4.8 finalize),
  not a serial end-phase.

---

## 7. Verification gates

Advance only when the gate is green. Offline checks run under `pytest` against
`fake_port` with an injectable clock, zero real hardware, zero real sleeps.

### G0 - Build greenlight (BLOCKING, business-scope, before any code)

- [ ] `scope.md` "not yet greenlit" resolved: operator greenlight explicitly
      confirmed, not assumed (design ch.13 #1)
- [ ] `STATUS.md` updated to "build started / M1"
- [ ] per-project CLAUDE.md corrected from the stale "likely mvp/" to the flat layout
      (design section 7)
- [ ] DAW verification target recorded: Reaper-on-Linux primary, Bitwig secondary
      (build OS is Linux 6.18)
- [ ] build-start ADR logged if the greenlight or any locked default changed; the ADR
      also records the engine-numbering reconciliation (M5 = local AMT, M6 = Claude API,
      per design section 9) and flags that `design.md` section 7's stack table has the
      M5/M6 labels swapped and should be corrected

### G1 - M1 spine (offline tests + one manual DAW round-trip)

- [ ] Offline (pytest, fake_port, zero real ports/sleeps): `test_contracts`
      (NoteRecord frozen + `start_s<end_s` fires; Responder ABC abstract),
      `test_ports` (two distinct named ports; send routes; callback fires; same-name
      warning once), `test_panic` M1-slice (injected exception runs cleanup once,
      both ports closed, CC123 x16)
- [ ] `pip install -r requirements.txt` succeeds; rtmidi+mido import clean;
      anthropic/transformers/torch NOT importable; resolved versions recorded
- [ ] MANUAL (Reaper/Linux): both ports visible in MIDI prefs; distinct C-major scale
      (60,62,64,65,67,69,71,72, matched on/off) recorded as editable MIDI, verified
      NOT an echo; incoming Agent In printed via the non-blocking callback
- [ ] Every exit path (Ctrl-C, SIGTERM, normal, injected exception) closes both ports,
      no stale port in `aconnect -l`
- [ ] Linux own-port quirk explicitly validated (agent never reads its own Agent Out);
      same-name warning fires on a deliberate re-run-without-teardown
- [ ] Real ALSA stale-port path exercised via `kill -9` (not a clean exit): observed
      and RECORDED in the README whether the collision warning fires and whether
      reopening the same-name port succeeds or raises after a hard kill, plus the
      documented recovery (this is the hardware-dependent behavior the in-process M1.5
      test cannot prove)
- [ ] DISCIPLINE: no capture/handover/theory logic written before this gate
      (design ch.13 #2)

### G2 - M2 capture + handover + concurrency (offline + one manual smoke)

- [ ] Offline green in CI (requirements.txt only): `test_handover` (settle fires only
      when held-notes empty; hard override fires with a note held past 3000ms;
      trigger-CC `value>=64` fires immediately; dangling note_ons closed at
      `handover_t` with `start_s<end_s`), `test_capture` (`phrase_t0` normalization to
      0.0, immutability, vel-0=note-off), `test_concurrency` (BOTH the deterministic
      fake-clock variant AND the real-time stress variant: no torn state, no deadlock,
      no lost/double fire across repeated runs)
- [ ] Injectable clock threaded through capture AND poll thread everywhere time is read
      (no silent fallback to real `perf_counter`)
- [ ] Callback provably never sleeps/blocks and is the sole writer of
      `last_event_time`; silence handover lives ONLY in the poll thread;
      exactly-once-per-phrase debounce (no double-fire across trigger-CC and silence
      paths)
- [ ] config M2 defaults read 700/3000/30/67 from `config.py` (no hard-coded literals
      in `handover.py`)
- [ ] Note: the concurrency invariant is only FULLY verified at the manual smoke; the
      offline tests bound it but a deterministic clock cannot reproduce every real
      interleaving (see the M2.9 risk row)
- [ ] MANUAL smoke: a real played phrase fires exactly one correct handover with a
      correct dangling-free `phrase_t0`-anchored snapshot; re-arm fires again on a
      second phrase (loop without restart); INCLUDE one deliberately fast/dense phrase
      (rapid notes, overlapping/held) to stress the lock against the real callback
      timing

### G3 - M3 core demo (offline invariants + the headline manual DAW round-trip)

- [ ] Offline green in CI (requirements.txt only): `test_theory` (duration-weighted
      key correct on canonical C-major/A-minor; key-confidence floor falls back to
      last-known/`--key` on a sparse phrase; median-IOI tempo + floor + safe None on
      `<2` onsets), `test_heuristic` (determinism under fixed seed; in-key invariant
      every pitch in `scale_pcs`; dangling-free; offset-from-0; humanize bounds/bypass,
      no `start_s<0`), `test_scheduler` (STRUCTURAL: each recorded sleep target ==
      `play_t0+offset` exactly, never a running sum; absolute-target timing under the
      fake clock; a short REAL-clock run shows NO accumulated drift; handover->respond->
      listen loop), `test_panic` (mid-response exception leaves no stuck note, every
      note_on matched, CC123 x16)
- [ ] Coordinate contract enforced: `respond()` emits offsets from 0; scheduler sleeps
      to absolute `play_t0+offset` targets, no per-note sleeps summed (explicitly
      code-reviewed for any cumulative/running-sum addition, AND pinned by the
      structural `test_absolute_target_no_drift` + the real-clock
      `test_realclock_no_accumulated_drift`)
- [ ] `last_known` key persists across turns for the confidence fallback
- [ ] MANUAL (Reaper/Linux, input-monitoring/MIDI-thru OFF): a played phrase yields a
      coherent in-key editable-MIDI reply on Agent Out; a second phrase loops without
      restarting the agent; no stuck notes after a normal turn

### G4 - PoC complete (M4: full M1-M4 offline suite + the acceptance manual gate)

- [ ] Offline green in CI (requirements.txt only): `test_config` (every flag
      round-trips; defaults match 700/3000/30/67/150), `test_handover` extended
      (trigger-CC fires immediately; sub-threshold/wrong-CC do not; silence ladder
      still fires, no regression), `test_feedback` (no spurious reclaim on echoed
      output within `echo_window_ms`; non-echo note/trigger aborts), `test_panic`
      (matched note_offs after mid-response exception AND after simulated SIGINT;
      idempotent double-cleanup harmless), plus the full pre-M4 suite still green
- [ ] `panic_cleanup` idempotent (cleaned-flag), lock-careful (copy-under-lock, send
      outside the lock); atexit+SIGINT/SIGTERM installed on the main thread; reclaim
      abort routes through the same cleanup primitive (barge-in leaves zero sounding
      notes)
- [ ] README per-OS/per-DAW complete: setup/install/run + flag reference; Linux
      own-port quirk + stale-port recovery; Windows loopMIDI workaround;
      input-monitoring/MIDI-thru OFF instruction + feedback warning; no em dashes
- [ ] MANUAL (Reaper/Linux), the one acceptance gate: full turn-taking loop without
      restart via all three handover modes (CC67 pedal, silence ladder, hotkey);
      barge-in aborts cleanly; Ctrl-C mid-response leaves no hanging note; echo-guard
      verified by leaving MIDI-thru ON briefly (agent does not self-abort) AND the
      measured DAW-thru round-trip latency is recorded and confirmed below
      `--echo-window-ms` (so the window is correctly sized vs real latency, not merely
      "did not self-abort"); resolved verified dep versions + the measured thru latency
      recorded in README; STATUS -> "M4 complete / PoC done"

### G5 - M5 AMT engine (OPTIONAL, post-PoC; default path must stay untouched)

- [ ] `responder.py` still imports and the default heuristic path is byte-for-byte
      unchanged when AMT deps are NOT installed; AMT deps live only in
      `requirements-model.txt`; CI still core-deps-only and green
- [ ] Offline AMT tests with the model FULLY MOCKED (no real weights in CI):
      guarded-import (absent anticipation -> construction raises catchable ImportError,
      module still imports), NoteRecord<->.mid round-trip re-based to t=0 and
      dangling-free, in-key-after-snap on canned out-of-key events, FallbackResponder
      degradation (ImportError/exception/timeout -> heuristic result + logged warning)
- [ ] Timeout posture decided and either tested (process-isolated, hung generate
      terminated at `--amt-timeout`) or explicitly documented as best-effort with the
      heuristic default as the safety net, not left ambiguous
- [ ] `midi_to_events`/`events_to_midi` is the only tokenizer boundary (no MidiTok
      import)
- [ ] MANUAL: `--responder amt` yields a coherent in-key model-composed editable-MIDI
      reply in Reaper, loops without restart, runs without GPU (CPU OK); disabling deps
      degrades to heuristic, not a crash; one real CPU `generate()` wall-clock latency
      recorded AND the loop behavior during it confirmed to match the chosen M5.7
      posture (timed-out-to-heuristic if isolated; observed worst-case block time in
      STATUS if best-effort); AMT weights license tag spot-checked on HuggingFace

### G6 - M6 Claude engine (OPTIONAL, needs key; default path must stay untouched)

- [ ] Default `pip install -r requirements.txt` still pulls no anthropic; M1-M4
      acceptance unaffected; CI green with no network and no `ANTHROPIC_API_KEY`
- [ ] Model id + SDK streaming/tool-use event names VERIFIED against the installed
      anthropic SDK and live docs (not memory), recorded inline + in README
- [ ] Offline `test_claude` with `FakeAnthropicClient` (no network/key): `RESPOND_TOOL`
      schema maps 1:1 onto NoteRecord ranges, phrase/context serialization round-trip,
      incremental streaming parser yields first-note-before-complete + drop-and-continue
      on malformed/out-of-range, `respond()` in-key + anchored t=0 + stray note snapped,
      factory falls back to heuristic without key/SDK
- [ ] `ClaudeResponder` honors the coordinate contract (offsets from 0) and reuses M3
      streaming-to-scheduler wiring; `FallbackResponder` wraps it (no-default-break)
- [ ] OPTIONAL live smoke (skipif no key, never in default CI): a real Haiku call
      returns a non-empty in-key list, prints phrase->first-note and phrase->complete
      latency

---

## 8. Definition of done (traced to scope.md acceptance)

| scope.md AC | Met at | Trace |
|---|---|---|
| AC#1 virtual port visible as a DAW input | G1 / M1.10 | Both "Agent In" and "Agent Out" open as separate virtual ports and appear in Reaper MIDI prefs on Linux (two ports because RtMidi cannot read its own virtual port on Linux). |
| AC#2 play -> audible, coherent response streamed back as editable MIDI | G3 / M3.17 (reinforced G4 / M4.10) | A played phrase produces a coherent IN-KEY reply (duration-weighted KS key, median-IOI tempo, restate-then-vary heuristic, scale-snapped, humanized) recorded on Agent Out as ordinary editable notes. |
| AC#3 turn-taking end to end without restart | G3 + G4 manual gates | play->handover->response->ready loops across turns with no restart; `last_known` carries forward; buffer clears and returns to LISTEN each turn. |
| AC#4 runs with no dedicated GPU | default path (all gates) | The default `HeuristicResponder` is offline, zero-deps, instant; M1-M4 need no GPU and no model download. AMT/Claude are opt-in, never on the default path. |
| AC#5 README documents setup per OS incl. Windows loopMIDI caveat | G4 / M4.8 | per-OS (macOS CoreMIDI / Linux ALSA own-port quirk + stale-port recovery) + per-DAW arming + Windows loopMIDI via `--port-names` + input-monitoring/thru OFF + feedback warning; no em dashes; resolved versions recorded. |

Cross-cutting done criteria:

- [ ] **Safety invariants verified** (all gates): dangling note_ons closed at handover
      before snapshot (G2); echo-guard so the agent never mistakes DAW-thru of its own
      output for a human reclaim (G4); guaranteed panic cleanup (explicit note_offs +
      CC123 on all 16 channels) on every exit/exception including Ctrl-C mid-response
      (G1 slice, G3, G4).
- [ ] **Offline-testability** (scope + design ch.13 #3): the entire core
      (capture->handover->theory->responder->scheduler) is provable via fake_port +
      injectable clock with zero real hardware and zero real sleeps; the full M1-M4
      suite is green in CI installing `requirements.txt` only.
- [ ] **Appetite met**: M1-M4 delivered within the 2-3 day PoC budget; concurrency
      (the budgeted hidden-work item) is explicitly costed inside M2, not treated as
      free; the only unavoidable hardware steps are the four manual DAW gates.
- [ ] **Discipline honored**: no capture/handover/theory logic before the M1
      round-trip is verified (design ch.13 #2); coordinate contract upheld (capture
      normalizes to `phrase_t0`; `respond` emits offsets from 0; scheduler sleeps to
      absolute targets, never cumulative).
- [ ] **PoC shippable at G4**: the heuristic-engine PoC is tunable (every threshold a
      CLI flag), safe (no stuck notes on any exit), and onboardable (per-OS README).
      M5 (local AMT) and M6 (Claude API) are post-PoC upgrades through the same
      Responder seam, not part of the shippable definition of done.

---

## 9. Risk checkpoints

Watch these at the listed task boundaries.

| Risk | Where | Mitigation |
|---|---|---|
| python-rtmidi wheel/ABI mismatch stalls before any code runs | M1.2 | Exact-pin in `requirements.txt` + record the resolved version; note the apt `libasound2-dev`/build path in case a source build is needed. |
| Stale ALSA virtual ports linger after an unclean exit and mask whether teardown works | M1.5, M1.7, M1.10 | Guaranteed cleanup + collision warning + README recovery note; M1.10 tests that a clean exit leaves nothing behind. |
| Reaper-on-Linux MIDI routing/arming friction (input-monitoring vs record-arm, ALSA vs JACK) | M1.10, M3.17, M4.10 | Reaper chosen for simplest arming; Bitwig is the Linux secondary if Reaper's ALSA routing fights back. |
| Scope creep into M2 logic while wiring ports (design forbids logic before the round-trip) | M1 | M1 emitter is a fixed C-major scale (not derived from input); contracts are signatures only; injectable clock + scripted-timing deferred to M2. |
| Concurrency: a lock-scope error (reading `last_event_time`/held-notes outside the lock) causes torn reads / missed/double fires that pass single-threaded tests | M2.2, M2.5, M2.6, M2.9 | M2.9's deterministic test + the single-writer rule for `last_event_time`; a fake clock erases the real 30ms-wakeup-vs-callback interleaving, so M2.9 ALSO runs a real-time stress variant (real short sleep, many repeated iterations), and the G2 gate states the invariant is only FULLY verified at the manual smoke, which now includes a deliberately fast/dense phrase to stress the lock. |
| Injectable-clock seam not threaded through every time-read; a silent fallback to real `perf_counter` makes silence-timer tests wall-clock-dependent | M2.4, M2.6 | Enforce clock injection everywhere time is read; the G2 gate checks for it. |
| Snapshot/dangling-closeout ordering bug (normalize before closeout, or clear before reading) yields wrong/negative durations | M2.3 | Order is closeout -> normalize -> freeze; the `start_s < end_s` assertion in snapshot is the guard. |
| Handover double-fire without a one-shot-until-rearm latch (poll fires every 30ms, or trigger-CC + silence both fire) | M2.6, M2.7 | Debounced one-shot until re-armed; exactly-once-per-phrase guaranteed and tested. |
| rtmidi delivers note_off as note_on velocity 0; held-notes never empties so settle never fires | M2.5 | Callback treats note_on-with-velocity-0 as note_off; covered by a test case. |
| Key estimation wrong on short/sparse phrases -> out-of-key answer (the most audible failure) | M3.3, M3.4 | Confidence floor + last-known/`--key`-lock fallback; the floor THRESHOLD is empirical (config default first, adjust in M3.16). |
| Median-IOI tempo fragile on dotted rhythms/rubato; can read like a delay effect | M3.5 | Honestly downscoped to a "smart echo" with a tempo-confidence floor and documented as such; bounded, not solved. |
| Coordinate-contract violation (summing per-note sleeps) silently reintroduces cumulative drift | M3.13 | A deterministic fake clock CANNOT exhibit real-time drift (the test controls the clock the sleep is computed against, so a summing implementation can still pass). So the guard is three-part: (1) the structural `test_absolute_target_no_drift` asserts each recorded sleep target == `play_t0 + offset` exactly, independent of clock reads (a running sum fails this); (2) a short `test_realclock_no_accumulated_drift` exercises the actual real-`time.sleep` mechanism and asserts the error does not accumulate; (3) explicit code review for any cumulative addition. Write all three with/before the scheduler (M3.12 -> M3.13). |
| humanize() jitter pushes `start_s` below 0 or creates a dangling note | M3.11 | Clamp + the `start_s < end_s` preservation check in `test_humanize_bounds_and_bypass`. |
| Hotkey input is the one genuinely cross-platform-fragile piece (terminal raw-mode vs key-listener; macOS accessibility perms) | M4.5 | Scope v1 to a terminal-focused keypress, document "terminal must have focus", keep strictly additive so the silence ladder stays the no-hardware baseline. |
| Echo-guard window tuning (150ms): too tight leaks a false reclaim, too loose swallows a fast human reclaim of the same pitch; AND real cross-port DAW-thru latency may EXCEED the window so the guard never matches and does nothing | M4.6, M4.10 | Make the window a config flag (`--echo-window-ms`); unit-test both boundaries INCLUDING the false-negative case (same pitch just after the window must abort) and document that within-window same-pitch reclaim is intentionally swallowed (a `(pitch,channel)`-only match, known limitation); in M4.10 MEASURE the real DAW-thru round-trip latency with thru on and confirm it is below the window (resize + record if not), so the guard is proven to actually match real echoes rather than silently no-op. |
| Panic cleanup re-entrancy / double-fire (atexit + signal + try/finally all fire on one Ctrl-C; signal handler runs while the scheduler holds the sounding-note lock -> deadlock) | M4.2, M4.3 | Idempotent, lock-careful `cleanup()` guarded by a cleaned-flag; signal handler does minimal work; test that double cleanup is harmless. |
| Reclaim during RESPOND must cancel the worker without leaving its current note dangling | M4.7 | Route the abort through the same panic_cleanup primitive; test that abort mid-response leaves no sounding notes. |
| Signals only deliver to the main thread in Python; if the state machine is not on the main thread the SIGINT handler will not install | M4.3 | Confirm `agent.py`'s main loop owns the main thread; test cleanup via a direct call + a simulated handler invocation rather than a real signal in CI. |
| AMT weights license only believed Apache-2.0 (HF card was 403 in research) | M5.2 | Spot-check the tag before any paid use; personal/offline use is fine for this PoC. |
| CPU latency (~1-3s/generate) could feel sluggish in the loop | M5.2, M5.8, M5.10 | ~2-bar response cap + stream time-to-first-note; GPU/Apple Silicon is where the budget is comfortable. |
| In-process blocking inference cannot be safely thread-killed mid-CUDA-kernel | M5.7 | A real enforceable `--amt-timeout` needs process isolation; if deferred to best-effort, the heuristic default is the only true safety net for a hung generate (decide, do not leave ambiguous). |
| MidiTok import or hand-touching tokens causes a vocab mismatch with the checkpoint | M5.4 | `midi_to_events`/`events_to_midi` is the only sanctioned tokenizer boundary. |
| Anthropic model id / SDK streaming-event surface drifts from the design's `claude-haiku-4-5` and remembered event names | M6.2 | Verify against the installed SDK + live docs, not memory, before coding the streaming parser. |
| Incremental tool-use JSON parsing splits mid-number/mid-object | M6.6 | Accumulate-then-parse defensively with drop-and-continue, never assume clean note boundaries. |
| Network/timeout/rate-limit mid-stream; partial stream then error needs a decided policy | M6.7, M6.8 | FallbackResponder catches it; decide return-partial vs fall-back-wholesale so the loop never hangs or half-plays. |

---

## First-session starter checklist

Session 1 = M1 (spine proof). Do these in order; do not write any
capture/handover/theory logic this session (design ch.13 #2).

- [ ] **M1.0 (BLOCKING, business-scope):** confirm the operator greenlight explicitly
      (do not assume); update `STATUS.md` to "build started / M1"; correct the
      per-project CLAUDE.md from "likely mvp/" to the flat layout; record the DAW
      target (Reaper-on-Linux primary, Bitwig secondary); log a build-start ADR if the
      greenlight or any locked default changed.
- [ ] **M1.1:** create the flat skeleton (`agent.py`, `ports.py`, `capture.py`,
      `handover.py`, `theory.py`, `responder.py`, `scheduler.py`, `config.py`,
      `tests/`), a Python 3.10+ venv, and `.gitignore`.
- [ ] **M1.2:** author the three requirements files; exact-pin and install the core
      (`python-rtmidi`, `mido`, `pytest`); confirm anthropic/transformers/torch are NOT
      importable; record the resolved versions.
- [ ] **M1.3:** freeze the `NoteRecord` frozen dataclass (with the `start_s<end_s`
      invariant), the `Responder` ABC, and the `MusicalContext` placeholder; write
      `test_contracts.py`.
- [ ] **M1.8:** stand up the minimal `fake_port` record/replay stub + `conftest.py`;
      get `pytest` running green.
- [ ] **M1.4 -> M1.5 -> M1.6 -> M1.7:** open the two virtual ports + non-blocking
      callback; add the same-name collision warning; build the distinct C-major
      emitter; wire panic/cleanup + logging. Write `test_ports.py` and the
      `test_panic.py` M1 slice alongside.
- [ ] **M1.9:** fill the README scaffold for the M1 parts (setup/install/run + Reaper
      arming + Linux own-port quirk). No em dashes.
- [ ] **GATE G1:** offline contracts/ports/panic-slice green under pytest (zero real
      ports, zero real sleeps), then the one manual Reaper round-trip (M1.10): both
      ports visible, the distinct C-major scale recorded as editable MIDI, incoming
      Agent In printed, clean teardown, same-name warning on a deliberate re-run.
