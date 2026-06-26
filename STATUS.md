# midi-agent - STATUS

- Updated: 2026-06-26

## Where we are

**M1-M4 proof of concept + the M5 local AMT engine are BUILT and the offline test suite
is green** (52 passing `pytest` tests, no hardware). The complete heuristic turn-taking
agent ships: two virtual ports, lock-guarded capture with dangling-note closeout, the
three-thread concurrency model, hybrid CC67 + silence-ladder handover, duration-weighted
key/tempo with confidence floors, the `HeuristicResponder` (restate-vary / mirror /
arpeggiate / harmonize, all snapped in-key) + `humanize()` + `FallbackResponder`, the
absolute-target scheduler with echo-guard, and guaranteed panic/all-notes-off cleanup.

**M5 (local AMT engine)** is built behind the existing `Responder` seam: `amt_engine.py`
with the model-free NoteRecord <-> temp `.mid` bridge, the guarded-import `AmtResponder`
(constructing it without torch raises a catchable ImportError; the module always imports),
the call-and-response round-trip (continue after the phrase, re-base to t=0), the shared
scale-snap + `humanize` post-pass, and a best-effort `--amt-timeout` in `FallbackResponder`.
`--responder amt` wired through `config.py` with `--amt-*` tunables; the default stays the
heuristic. The model boundary is mocked in `tests/test_amt_responder.py`, so the full path is
verified with **zero** torch / transformers / anticipation installed (which also proves the
graceful fallback). Two things are operator-side: the real model load + a live CPU-latency
pass (M5.2 / M5.10), and the manual DAW round-trip (this container is headless, no
`/dev/snd/seq`).

Relocated 2026-06-26 from the bar_builds monorepo (`lab/midi-agent`) into this standalone
public repo (`github.com/barmoshe/midi-agent`).

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

## Next action

**Operator: run the manual DAW round-trip** (the acceptance gates that need real ports;
see README "Verify in a DAW"). Start `python agent.py`, confirm Agent In/Out appear in a
DAW, play a phrase, confirm an in-key reply records as editable MIDI, and that turn-taking
loops. Report back and we close G1/G3/G4.

**Operator: exercise the M5 AMT engine on real hardware** (M5.2 + M5.10): `pip install -r
requirements-model.txt`, run `--responder amt`, confirm a model-composed in-key reply records
as editable MIDI and loops; observe one real CPU `generate()`'s wall-clock latency and the
loop behavior during it (best-effort timeout posture: the loop returns the heuristic at
`--amt-timeout`; the abandoned generation finishes in the background). Record the observed
latency here. Confirm the AMT *weights* license on HuggingFace before any paid build.

The remaining build increment is **M6 = Claude API engine** (needs a metered key), the
optional best-quality upgrade behind the same `Responder` seam.

CI: a GitHub Actions workflow (`.github/workflows/ci.yml`) runs `pytest` on the core deps on
push/PR (this is now its own repo, so CI is no longer monorepo business-scope).

## Blockers

None for the PoC. Deferred pre-build checks for the smart engines (see `design.md`
sections 11 + 13):
- Spot-check the AMT *weights* license on HuggingFace before any *paid* build
  (believed Apache-2.0; the heuristic-only PoC does not need it).
- Per-OS manual verification needs a DAW; the whole core is testable offline via a
  fake MIDI port with an injectable clock.
