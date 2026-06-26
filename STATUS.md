# midi-agent - STATUS

- Updated: 2026-06-26

## Where we are

**M1-M4 proof of concept BUILT and the offline test suite is green** (39 passing
`pytest` tests, no hardware). The complete heuristic turn-taking agent ships: two
virtual ports, lock-guarded capture with dangling-note closeout, the three-thread
concurrency model, hybrid CC67 + silence-ladder handover, duration-weighted key/tempo
with confidence floors, the `HeuristicResponder` (restate-vary / mirror / arpeggiate /
harmonize, all snapped in-key) + `humanize()` + `FallbackResponder`, the absolute-target
scheduler with echo-guard, and guaranteed panic/all-notes-off cleanup. Code + tests +
per-OS README all in this folder. The one thing not done here: the manual DAW round-trip
(this container is headless, no `/dev/snd/seq`), which is the operator's to run.

Research, feasibility, AND technical design also complete (including the
Claude-as-engine direction).

- `research.md` - two deep-research passes (landscape + de-risk). Verdict **GO**.
- `research-claude-engine.md` - third + fourth passes on Claude as the engine.
  Third: Claude via **API key** (Haiku) is a great additional engine. Fourth (the
  operator wants NO API key, personal project): driving Claude on a **subscription**
  is permitted but **NO-GO for the live loop** (volatile latency, `--bare` needs a
  key, programmatic use may be separately API-metered). **Recommended no-key engine =
  local AMT** (free, offline, MIDI-native, faster-than-real-time). The thing the
  operator wants (no metered key) is best served by local AMT, not the subscription.
- `scope.md` - the buildable v1 contract (appetite, acceptance criteria, no-gos).
- `design.md` - the full engineering design doc (a design workflow: 4 research
  agents resolved the open questions, 3 architecture proposals were judged, the
  winner was synthesized and adversarially reviewed, 10 gaps fixed), now with
  section 4.5 ClaudeResponder and an updated build plan. Source of truth for the build.
- `plan.md` - the sequenced, task-level BUILD PLAN (a planning workflow: decompose
  -> per-milestone planners -> sequencing -> adversarial review, 10 findings fixed).
  M1-M6 task tables (id / produces / depends-on / acceptance / test), gates G0-G6,
  critical path, session-by-session order, definition of done traced to scope.md, and
  a first-session checklist. Planning only, no implementation code.

Design decisions locked in `design.md`: turn-taking call-and-response; Python
`mido` + `python-rtmidi` over **two** virtual ports (Linux self-read quirk); a
three-thread concurrency model (callback / poll / state+scheduler, no asyncio); a
`Responder` interface with a no-GPU music-theory **HeuristicResponder as the
product** and **AMT** (`stanford-crfm/music-medium-800k`) as the stretch model swap;
hybrid CC67-pedal + silence-ladder handover; echo-guard + panic cleanup safety.

Nothing built yet - stopped before the build by operator request.

## Next action

**Operator: run the manual DAW round-trip** (the acceptance gates that need real ports;
see README "Verify in a DAW"). Start `python agent.py`, confirm Agent In/Out appear in a
DAW, play a phrase, confirm an in-key reply records as editable MIDI, and that turn-taking
loops. Report back and we close G1/G3/G4.

Then the next build increment is **M5 = local AMT engine** (the recommended no-key smart
engine, the "AI duet partner" headline) behind the existing `Responder` seam. M6 (Claude
API, needs a key) is the optional best-quality upgrade.

Deferred follow-up: GitHub Actions CI was planned (X6) but a repo-root `.github/` workflow
is business-scope in this monorepo, so it is left for operator confirmation; for now the
gate is the local `pytest` run (green).

## Blockers

None for the PoC. Deferred pre-build checks for the smart engines (see `design.md`
sections 11 + 13):
- Spot-check the AMT *weights* license on HuggingFace before any *paid* build
  (believed Apache-2.0; the heuristic-only PoC does not need it).
- Per-OS manual verification needs a DAW; the whole core is testable offline via a
  fake MIDI port with an injectable clock.
