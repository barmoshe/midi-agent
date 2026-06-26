# midi-agent - STATUS

- Updated: 2026-06-26

## Where we are

**M1-M4 PoC + the M5 local AMT engine + a rule-based backing-track mode + a dynamic AI backing
mode are BUILT and the offline test suite is green** (62 passing `pytest` tests, no hardware).
The complete heuristic turn-taking agent ships: two virtual ports, lock-guarded capture with
dangling-note closeout, the
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

**Backing-track modes (added 2026-06-26):** for when turn-taking feels stop-start. Both stream
to Agent Out, never listen (no input routing, no feedback), and you solo over them.
- `backing.py` (rule-based): a continuous in-key chord + bass groove. Diatonic triads on a
  configurable progression, pads/pulse/arp feels, drift-free absolute-time looping. Pure logic
  unit-tested (every note_on has a matching note_off).
- `ai_backing.py` (dynamic/generative): an instant chord intro, then the AMT model takes over and
  keeps generating evolving material, feeding its own output back; every note snapped to key and
  capped under the solo, with the rule-based progression covering any gap. Producer/consumer
  (a generator thread buffers ahead of the player). Verified live (scripts/ai_backing_smoke.py).
  Device finding on this Intel Mac (which has a Metal-capable GPU): CPU generates a ~6s chunk in
  ~3-9s (predictable); MPS is sub-second warm but pays a ~36s first-call Metal compile every run,
  so ai_backing defaults to `--amt-device cpu` to avoid a 36s startup. Either way the 14s
  lookahead buffer + rule-based covers keep it from going silent. Pure mapping (place_chunk) +
  the AmtStream wrapper are unit-tested.

### M5 real-hardware results (2026-06-26, Intel x86_64 Mac, CPU)

The AMT engine was run for real (M5.2 + the runnable half of M5.10): deps installed from
`requirements-model.txt`, `stanford-crfm/music-medium-800k` loaded, and `scripts/amt_smoke.py`
ran several `generate()` turns on a synthetic C-major phrase.

- **Weights license confirmed `apache-2.0`** (HuggingFace card tag; no longer "believed"). Arch: gpt2.
- **Latency (CPU):** model load ~3.0s (cached); generate ~8.8s cold (first inference) then
  ~3-5s warm. Above the "hundreds of ms" turn-taking budget on this Intel-Mac CPU but within
  the research's "~1-3s on a strong laptop CPU / sub-1s on GPU/Apple Silicon" expectation. The
  default `--amt-timeout 10` accommodates it; lower `--amt-response-bars` for snappier turns.
- **Quality:** every turn returned a non-empty, in-key (after scale-snap), t=0-anchored,
  dangling-free reply that loops across turns. AMT is multi-instrument (Lakh), so replies span a
  wide pitch range; for a tighter piano duet, a future option is to constrain the instrument.
- **Platform pins (Intel Mac, torch capped at 2.2.2):** `transformers>=4.40,<4.46`, `numpy<2`,
  `anticipation` from git (not on PyPI). All recorded in `requirements-model.txt` with the why.
- The offline suite stays green with the deps installed (the deps-absent tests simulate the
  missing import via monkeypatch, so they hold either way).

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

**Operator: the AMT engine's last DAW step** (the only un-run part of M5.10). The engine is
installed and verified headless (see M5 real-hardware results above); all that remains is
hearing/recording it through a DAW: `./venv/bin/python agent.py --responder amt`, route Agent
In to an instrument, play a phrase, and arm a track from Agent Out to capture the
model-composed reply as editable MIDI. First reply will lag ~3-9s on CPU.

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
