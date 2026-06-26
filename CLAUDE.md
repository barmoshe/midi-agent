# midi-agent - CLAUDE.md

Per-project context. Loads only when working in this folder. Business-wide rules live
in the repo-root `CLAUDE.md`.

- **What it is:** An AI + MIDI lab project. A turn-taking "Live MIDI Agent": you play a
  phrase into a virtual MIDI port, it replies with editable MIDI in your DAW.
- **Stage:** M1-M4 proof of concept BUILT (heuristic engine). Offline test suite green;
  manual DAW round-trip is the operator's to run. Smart engines (M5 local AMT, M6 Claude
  API) designed but not built.
- **Stack:** Python 3.10+, `mido` + `python-rtmidi`, two virtual ports, three threads
  (callback / poll / state+scheduler), no asyncio. macOS/Linux first.
- **Build lives in:** this folder, flat (no `mvp/`, no package nesting). Modules at the
  folder root, tests under `tests/`. Run: `python agent.py`; test: `pytest`.
- **Local conventions:** No em dashes in committed docs (house style). Scope to
  turn-taking, not sub-20ms jamming. The offline core is testable via `tests/fake_port.py`
  with an injectable clock (no DAW). Two hook false-positives to know: a `*contract*`
  filename trips protect-paths (the test is `test_invariants.py`), and the word "contract"
  + a `>` in a commit message trips fs-safe.
- **Canonical state:** `STATUS.md` (where we are), `brief.md` (immutable ask),
  `scope.md` (acceptance), `design.md` (source of truth), `plan.md` (build plan),
  `research*.md` (the cited research). Per-project ADRs would go in a local `decisions/`.
