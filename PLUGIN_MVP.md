# MIDI Agent: MVP Plugin Design

A live MIDI accompanist that listens to your solo and plays chords that follow you, in key, bar by bar. This doc commits the MVP to a single form factor, a single mode, and a single honest engine choice, and sizes the build in hours-to-days.

---

## Form factor: Max for Live MIDI device (logic ported to v8 JavaScript)

**Ship a single `.amxd` Max for Live MIDI-effect device whose brain is a v8 JavaScript object.** The device sits inline on a MIDI track *before* the instrument: `midiin` receives the track's live MIDI, the v8 object runs the harmony logic, and `midiout` passes the generated comp downstream into the instrument on the *same* track.

**Why this and not a plugin.** This is the only form factor that does what the user actually wants inside Ableton: load as a generating MIDI effect inline, receive the track's MIDI, and emit generated notes into the instrument with no virtual ports, no two-track routing, and no signing. Every plugin-format alternative hits an Ableton-specific wall:

- **VST3 MIDI effect (JUCE):** Ableton will not load a third-party MIDI effect before an instrument on the same track. It forces a separate MIDI track plus cross-track routing, the exact friction we are trying to delete. It also forces a C++ rewrite of the logic and a `$99/yr` Apple Developer ID plus notarization.
- **AU / AUv3:** cannot output or route MIDI in Ableton at all. Non-starter for a generating MIDI effect.
- **CLAP:** Ableton does not load CLAP as of 2026. It will not open.
- **Standalone app + CoreMIDI virtual ports:** keeps the Python verbatim, but cannot be an in-track device. The user still routes controller-in and accompaniment-out across tracks, the feedback trap is only mitigated rather than structurally gone, and it carries the `$99/yr` signing and PyInstaller tail.

The decisive distribution win: **a single unsigned `.amxd` dropped into the User Library.** No Apple Developer account, no notarization, no Gatekeeper prompt, no installer. The feedback trap that haunts the Python PoC becomes structurally impossible, because the device only ever re-reads its own track input.

**The two costs to own, not wave away:**

1. **Audience gate.** It runs only for users who own Ableton Live Suite or the paid Max for Live add-on, not Intro or Standard. This is the smallest reach of any path, and the deliberate price of the cleanest UX with zero distribution tail.
2. **The port is a rewrite.** This is the one path that re-codes the validated logic (~270 LOC of pure harmony math) from Python into v8 JS. A subtle off-by-one in the snap, decay, or diatonic-third math yields out-of-key or flip-floppy comping that is hard to debug by ear. The mitigation (a Node golden-vector oracle proving parity before the port ever loads in Max) is mandatory, not optional, and is real work in M0.

**Safer runner-up if the priority changes.** If the priority becomes maximum code reuse and lowest correctness risk rather than the cleanest UX, the **Hybrid M4L shell plus a local Python sidecar** is the fallback: same inline-Ableton UX and no plugin signing, but it ships `follow.py` verbatim (all existing tests stay green on the actually-shipping code) and keeps the neural-engine upgrade path alive that v8 can never host. Its cost is one extra process and notarizing that sidecar binary. Recommend v8 for the MVP; keep the sidecar in the back pocket.

---

## MVP scope: ONE mode, the follow-along comp

**Ship exactly one mode: the follow-along comp / AI accompanist (`follow.py`), "the chords follow your solo."**

You play a solo into the track. The device keeps a recency- and duration-weighted pitch-class histogram of your incoming notes, scores every diatonic triad for fit, adds hold-bias hysteresis so it does not flip-flop, and plays the best-matching chord plus bass plus groove under you, bar by bar, in key.

**Why this mode:**

1. **It is the operator-validated standout.** The alternatives were heard and rejected: the raw neural backing (`ai_backing.py`) sounded *aimless*, and the turn-taking call-and-response (`agent.py`) is stop-start. `follow.py` is the one mode judged the genuinely reactive "AI" the operator wanted, because the chords actually track the soloist via analysis, not a hallucinating model.
2. **It is a complete musical experience from one gesture.** The user just plays, and harmony appears under them. There is no phrase / turn / handover protocol to teach, no "now it is your turn" UX. That makes it the most demo-able and lowest-friction first product, legible to a non-technical listener in five seconds.
3. **Its core is pure and tiny.** Roughly 120 lines of integer/float math (`pitch_histogram`, `score_chord`, `best_degree`, `chord_bar_events`, `chord_name`), built on `build_triad` and `timeline_for_cycle`. It ports to v8 in days, and the 6 `follow.py` tests plus 7 `theory.py` tests become a bit-for-bit conformance oracle.

The one caveat to design around: this is the mode that both listens *and* plays, so it carries the feedback trap. The MVP owns that in the form factor (inline routing only re-reads track input) and in code (gate generated notes out of the listen buffer), rather than leaving it to the user.

---

## Music engine: pure theory, and that is the honest "better than AMT"

**The MVP engine is pure music theory: `follow.py`'s diatonic chord-scoring plus voice-leading hysteresis. No neural model in v1.**

This is the honest answer to the want for a better engine than AMT, not a dodge. The operator's complaint about AMT was that it sounded aimless. The research is unambiguous about why: **aimlessness is a missing-structure problem, not a model-size problem.** AMT was run as free self-continuation with no harmonic anchor, so it wandered. Reaching for a bigger model does not fix this:

- **AMT-large (780M)** makes the texture denser, not more directed, and costs more latency (~3 to 8s on CPU).
- **EleutherAI Aria (1B)** is a continuation model with the same structural gap: high per-note pianism, but it does not condition on your harmony, so it wanders too. It is piano-only and its real-time cost on a plain CPU is unmeasured.

`follow.py`'s diatonic chord-scoring *is* the structure those models lack. It is microseconds-latency, always in key, runs on any laptop with no GPU and no checkpoint download, and the operator already judged it the best-sounding mode. So for this MVP, the better engine than AMT is the theory engine, full stop. Pure theory is correct-but-plain by design; the differentiator is that the harmony genuinely follows you, not that the voicings are fancy.

**The v2 north star (designed for, not built now): the hybrid.** Keep the theory core as the harmony brain that picks the chord per bar, then let a model decorate only the surface (voicings, inversions, fills) with every output pitch hard-masked to the theory-chosen chord, so it can never wander. Run it async ahead of the playhead with graceful fallback to pure theory. Used correctly, that means AMT as *melody-conditioned accompaniment* (`anticipation.generate` with the solo as control tokens), not free continuation. The model half can never live in-process in v8 (no torch), so v2 needs the Node-for-Max or Python-sidecar seam. The MVP preserves that seam conceptually (`chooseChord -> events` is one function) so v2 swaps the chord *source* without touching the Max glue.

**Do not** ship AMT-large or Aria as the v1 engine. Both regress on exactly the axis the operator cares about. ReaLchords and ReaLJam are the right idea but have no open commercial weights: mine them for design, do not depend on them.

---

## End-user experience: install, load, use

Zero terminal, zero ports, zero manual routing.

**Install.** Drop one `MidiFollow.amxd` file into your Ableton User Library, or drag it from Finder onto a MIDI track. No installer, no code signing, no notarization, no Gatekeeper prompt, no `pip` / `venv`, no loopMIDI.

**Load.** Drag the device onto a MIDI track, placed in the device chain *before* an instrument (for example a piano). That is the entire routing step. No second track, no MIDI From / To, no Monitor In, no port picking.

**Use.** Play your solo into that track, from a controller or a clip. The device listens to your incoming notes and, bar by bar, plays a comp (chord plus bass plus groove) through to the instrument that follows your harmony. It rides Live's transport clock, so it is sample-locked to the song, not to a wall-clock sleep loop.

The whole `Agent In` vs `Agent Out`, two-virtual-ports, three-track-wiring, and "do not pick All Ins or it feedback-loops" burden from the Python PoC disappears. The feedback trap is structurally gone (the device only re-reads its own track input) and additionally gated in code.

**The device panel:**

- **Key** selector: Auto-detect or pinned (C major, A minor, and so on).
- **Feel** toggle: Pads or Pulse.
- **Chord rate**: every 1 or 2 bars.
- **7ths** on/off.
- **Velocity**.
- **Live readout**: the currently-detected key and the chord name it is playing right now (for example "G7" lighting up). This is the visual feedback the terminal PoC never had: the musician sees what the agent hears instead of reading log lines.

---

## Architecture

One `.amxd` device equals a thin Max patch (UI plus MIDI plumbing) wrapping a single v8 JavaScript object that holds all the music logic, distributed as one self-contained file.

**Signal / event flow per bar:**

1. `midiin` (the track's live MIDI) feeds the v8 object's note handler, which appends `(pitch, time)` to a rolling buffer with the same recency window as the PoC's `RollingNotes`.
2. A `transport`-synced bar clock (a metro or transport bang at the chosen chord rate, locked to Live's tempo) fires each bar.
3. On each bar the v8 object: (a) optionally auto-detects key via the ported Krumhansl-Schmuckler `estimate_key` once enough notes have arrived, then locks; (b) builds the recency-weighted `pitch_histogram`; (c) runs `best_degree` (`score_chord` over the 7 diatonic triads plus hold-bias hysteresis) to choose the chord, reusing the ported `build_triad`; (d) generates `chord_bar_events` for that chord, feel, and velocity; (e) sends note-ons/offs out `midiout` into the instrument, scheduled against Live's clock.

**Three layers:**

- **JS music core** — a direct port of `theory.js` (`estimate_key`, scale, `snap`, `degree_transpose`, `build_triad`), `follow.js` (`pitch_histogram`, `score_chord`, `best_degree`, `chord_name`, `chord_bar_events`), and `timeline_for_cycle`. Pure, unit-testable in Node *outside* Max.
- **Max glue** — `midiin` / `midiout` objects, the transport-synced bar clock, the UI bindings (`live.menu` / `live.toggle` / `live.numbox` for key / feel / rate / 7ths, plus an LED or comment for the live key and chord readout), and LOM access via `live.thisdevice`.
- **Device lifecycle** — Max owns open / close; on device-off or transport-stop we flush sounding notes (the in-device analog of all-notes-off) so nothing hangs.

**Schedule note timing off Live's transport, not the JS thread.** The v8 object runs only in Max's low-priority thread, which adds inter-thread latency. The chord *decision* happens in v8, but note on/off *emission* goes through a transport-synced metro / `@clocksource live` so timing quantizes to Live's clock. Bar-level comping (1 to 2s) absorbs the low-priority-thread jitter comfortably; do not drive note timing from a JS sleep loop.

The Python concurrency model (3 threads, RLock / Event, atexit / signal handlers, virtual-port creation, ALSA stale-port recovery) is entirely *replaced* by Max's single-threaded scheduler plus transport. All of that plumbing is deleted, not ported. The Responder seam is preserved conceptually so v2 can swap the chord source for a Node-for-Max sidecar without touching the Max glue.

---

## Milestone build plan (hours-to-days)

Realistic envelope: **5 to 6 working days** for a polished v1, with a usable demo in **2 to 3 days**. Build M1 first to validate the one Ableton-specific fact before investing in logic wiring. Add 1 to 2 days if Max is new ground (v8 idioms, transport sync, single-file `.amxd` freezing, LOM quirks).

| Milestone | Size | What ships |
|---|---|---|
| **M0 — Port the pure logic to JS, outside Max** | 1 day | Translate `theory.py` (`estimate_key` / `_pearson` / scale / `snap` / `degree_transpose`) and `follow.py`'s harmony core (`pitch_histogram` / `score_chord` / `best_degree` / `chord_name` / `chord_bar_events`) plus `build_triad` / `timeline_for_cycle` into a plain `.js` module. Re-encode the 6 `follow.py` and 7 `theory.py` tests as Node assertions / golden vectors and prove the JS matches Python bit-for-bit. **No Max yet. This is the hard precondition that neutralizes the port-correctness risk.** |
| **M1 — Minimal Max device, MIDI pass-through** | 0.5 day | An `.amxd` with `midiin -> v8 -> midiout` that forwards notes, loads inline before an instrument on a MIDI track in Live, and confirms the inline-MIDI-effect routing works. **Validate this first, hands-on, on Bar's machine.** |
| **M2 — Bar clock plus chord generation** | 1 day | Drive a transport-synced bar bang into the v8 object; on each bar run `best_degree` over the rolling buffer and emit `chord_bar_events` out `midiout`. Pinned key first (skip auto-detect). First sound: chords that follow a played solo, locked to Live's tempo. |
| **M3 — Auto-detect key, echo gate, note flush** | 1 day | Port the Krumhansl auto-detect-then-lock path; gate the device's own generated notes out of the listen buffer (in-process echo guard); flush sounding notes on device-off / transport-stop so nothing hangs. |
| **M4 — Device UI plus live readout** | 1 day | Key (auto / pinned), feel (pads / pulse), chord rate (1 / 2 bars), 7ths toggle, velocity, plus a live readout of detected key and current chord name. Tidy the patch, set the device title and scaffolding. |
| **M5 — Real-DAW play-test, tuning, package** | 1 day | Play it for real in Ableton; tune the window / halflife / switch-margin for feel (the most interaction-defining knobs); freeze the device as a single self-contained `.amxd`; write a one-paragraph "drop this on a MIDI track before an instrument" readme; ship. |

---

## What to reuse from the Python PoC

The validated asset is the music logic; the I/O layer is discarded because Max owns MIDI, transport, and lifecycle.

**Port 1:1 (the asset):**

- **`theory.py`** (149 LOC): `estimate_key` (duration-weighted Krumhansl-Schmuckler), `_pearson`, `_scale_for`, `snap`, `degree_transpose` (diatonic-interval math), `parse_key_lock`. Pure, no I/O.
- **`follow.py` harmony core** (~120 lines, lines 41-125): `pitch_histogram` (recency / exponential decay), `score_chord` (root / chord-tone / out-of-chord weighting), `best_degree` (diatonic search plus hold-bias hysteresis), `chord_name`, `chord_bar_events`.
- **`backing.py` chord primitives** (lines 40-141): `build_triad` (diatonic stacked-thirds so chord quality follows the key), `timeline_for_cycle` (events to time-sorted on/off pairs), `_clampv`, `make_context`. `follow.py` imports these, so they port together.

**Reuse as oracle and reference:**

- **The pytest suite as a conformance oracle**, especially `tests/test_follow.py` (6 tests: histogram weighting, `score_chord` fit/penalty, `best_degree` follows the emphasized chord, hysteresis holds when ambiguous, `chord_bar_events` in key) and `tests/test_theory.py` (7 tests). Re-encode as Node golden vectors to prove the JS port matches Python.
- **`parse_midi`** byte-parsing convention (`note_on` vel 0 = `note_off`, `ports.py` lines 22-39) as a reference for how to read `midiin` events.
- **The Responder seam contract** (`respond(phrase, context) -> notes`, `responder.py` lines 22-27) as the design boundary to keep, so a v2 model sidecar can slot in without touching the Max glue.

**Discarded, not reused** (replaced by Max's transport plus scheduler): `ports.py` (RtMidi / virtual ports), the three-thread model, `atexit` / signal lifecycle, ALSA stale-port recovery, and the timestamp echo-guard.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Port re-introduces correctness risk (the riskiest assumption).** This is the one path that hand-rewrites the validated ~270 LOC into v8 JS. An off-by-one in `degree_transpose` / `build_triad` / histogram decay produces out-of-key or flip-floppy comping that is hard to hear-debug. | Build the **Node golden-vector oracle in M0** and prove bit-for-bit parity *before* the port ever loads in Max. This is a hard precondition, not a nicety. The standalone-app and hybrid-sidecar fallbacks avoid this cost entirely if it proves too painful. |
| **Transport-synced real-time scheduling in Max is the only genuinely new engineering.** Locking the bar clock to Live's tempo and keeping note on/off timing clean (no stuck notes, no jitter) is where the unknowns are; the v8 object's low-priority thread adds latency. | Prove pass-through in M1 first. Emit notes via a transport-synced metro / `@clocksource live`, never a JS sleep loop. Flush sounding notes on stop / device-off. Bar-level comping absorbs the jitter. |
| **The feedback trap must be owned in-device.** This is THE mode that both listens and plays; if its own comp leaks back into the listen buffer it chases itself. | Structurally, inline routing only re-reads track input. Additionally gate generated note-ons out of the histogram buffer in code (the in-process analog of the 150ms echo-guard). Verify explicitly in M3. |
| **Auto-detect key can lock to the wrong key** on a sparse or chromatic opening (the PoC needs >=8 notes and confidence >=0.6). A wrong lock makes the comp fight the soloist. | Expose a manual Key pin in the UI as the reliable default; treat auto-detect as a convenience. Surface the detected key in the readout so the user can see and correct it. |
| **v1 is pure theory with no neural flavor**, so a listener expecting "AI" voicings may find the comp correct-but-plain. | Set expectations honestly: the differentiator is that the harmony genuinely follows you, not that the voicings are fancy. The hybrid sidecar (v2) adds surface flavor without sacrificing structure. |
| **Audience lock-in.** Runs only for users who own Live Suite or the Max for Live add-on (not Intro / Standard), the smallest reach of any path. | Flag this to Bar up front as the deliberate cost of the cleanest UX and zero signing tail. It is also a single unsigned file, the cheapest possible SKU and lab/lead-gen-friendly. If cross-DAW reach is later wanted, the same JS logic feeds a JUCE rebuild. |

---

## NOT in the MVP

- **Turn-taking call-and-response** (`agent.py`) — the stop-start LISTEN -> HANDOVER -> RESPOND mode. v2 device-family candidate.
- **Standalone backing arranger** (`backing.py`) as its own device — its primitives are reused as a library, but it does not ship as a separate mode.
- **Any neural engine in v1** — AMT (medium, large, or melody-conditioned), Aria, and the Claude engine. The hybrid theory-plus-masked-model sidecar is the v2 north star, not a launch dependency.
- **AMT-large or Aria as the engine** — explicitly rejected; they regress on the aimlessness axis the operator cares about and cost latency.
- **The Python sidecar / Node-for-Max bridge** — the seam is preserved conceptually, but no out-of-process engine ships in v1.
- **Cross-DAW support** (VST3 / AU / CLAP / standalone app) — Ableton-first only. The same JS logic can feed a JUCE rebuild later if reach is needed.
- **Code signing, notarization, an installer, or any distribution pipeline** — the deliverable is one unsigned `.amxd`.
- **Recording the generated comp to a clip on the same track** — Live blocks printing a MIDI effect's output to a clip on its own track. The MVP UX is live playback through the instrument, not clip recording.
