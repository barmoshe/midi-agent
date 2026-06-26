# AI + MIDI Innovation — Research & Feasibility Brief

Two deep-research passes (fan-out web search, adversarial 3-vote verification,
cited synthesis) run 2026-06-25 to find a high-leverage, buildable lab project at
the intersection of AI and MIDI. Pass 1 mapped the landscape and ranked concepts;
pass 2 de-risked the top pick. This is the durable write-up; raw run outputs lived
in the session scratchpad and are not committed.

**Verdict up front: GO** on a real-time "Live MIDI Agent", scoped to a turn-taking
call-and-response interaction. That scope flips the single hardest technical risk
(real-time symbolic inference on commodity hardware) into a non-issue.

---

## 1. Landscape and white space (pass 1)

**The obvious idea is already crowded.** "AI controls your DAW via MCP" is a solved,
validated pattern, not white space:

- **AbletonMCP** (`ahujasid/ableton-mcp`): ~2.7k stars, 356 forks, MIT. Two-part
  architecture: a MIDI Remote Script socket server inside Ableton Live + a Python MCP
  server bridging Claude over JSON-over-TCP. Tools include `create_midi_track`,
  `create_clip`, `add_notes_to_clip`, `load_instrument_or_effect`, `set_tempo`,
  playback control.
- **AbletonBridge** (`hidingwill/AbletonBridge`): 359 tools over TCP+UDP, including
  creative generation (Euclidean rhythms, chords, drums, arpeggios).
- **Text-to-MIDI MCP servers already exist:** `tubone24/midi-mcp-server` (JSON ->
  base64 MIDI + piano-roll preview, ships a companion skill) and
  `sandst1/mcp-server-midi` (FastMCP + python-rtmidi, exposes a virtual MIDI out port
  with Note On/Off, CC, and timed sequence tools).

**The genuine open ground is real-time symbolic performance** — a "live media agent
player" that plays and reacts in real time, rather than authoring static clips or
generating audio loops. Most shipping AI music tools are either static clip-authoring
(AbletonMCP/Bridge) or audio-loop generators (OBSIDIAN-Neural, Magenta RealTime). A
real-time, DAW-agnostic, bidirectional *symbolic* MIDI agent is comparatively
unoccupied.

**Design-space anchor.** A CHI 2026 paper, "A Design Space for Live Music Agents"
(184 systems, 31 dimensions, 4 aspects: Usage Context, Interaction, Technology,
Ecosystem), gives a ready-made taxonomy. Audio waveforms dominate (39% input / 58%
output); symbolic MIDI is the clear #2 modality (~27% input / ~37% output). Symbolic
MIDI is under-exploited relative to audio, which is where a DAW-native turn-taking
co-creation tool can sit. (Note: "under-served" is a modest interpretive leap; #2 of
N is common, not neglected. Confidence medium.)

### Building blocks (all verified, production-grade)

| Library | Role | Status |
|---|---|---|
| `mido` (v1.3.x) | MIDI read/write/create/play, full message access | Mature, maintained 2026 |
| `MidiTok` (v3.x) | MIDI tokenization (REMI, Octuple, +8), PyTorch dataset utils | Mature |
| FastMCP + `python-rtmidi` | Virtual MIDI port pattern, stream notes to a DAW | Proven by `sandst1/mcp-server-midi` |
| Ableton Link | Network tempo/start-stop sync | Proven in OBSIDIAN-Neural standalone |

### Models

- **EleutherAI Aria** (`loubb/aria-medium-base`): open-weight (Apache-2.0) autoregressive
  symbolic-music model on LLaMA-3.2-1B, trained on ~60k hrs of solo-piano MIDI. ISMIR
  2025 paper (arXiv 2506.23869). **Piano *continuation* model**, not a from-scratch
  multi-track generator: "performs best when continuing existing piano MIDI files
  rather than generating music from scratch."
- **Magenta RealTime** (Google DeepMind, 2025): 800M open-weights, faster-than-real-time
  on free Colab TPUs. Generates **audio**, not MIDI — out of scope for a symbolic agent.

---

## 2. De-risk pass — go/no-go on the Live MIDI Agent (pass 2)

### The finding that reshapes the plan

**The proven interaction model is phrase-level turn-taking (call-and-response), not
sub-20ms simultaneous jamming.** Aria-Duet / "Ghost in the Keys" (arXiv 2511.01663,
Nov 2025) works as a turn-taking dialogue: the human performs, signals a handover (via
the una corda pedal), and the model generates a coherent continuation. The realistic
latency budget is "does not break the flow" (hundreds of ms at the phrase level).
Genuine continuous-jamming systems (ReaLJam, Magenta) are a separate, harder class.

**Why this matters:** turn-taking removes the need for real-time per-note inference.
The agent waits for the human to finish a phrase, then takes ~1-2s to generate a
response. The scary "real-time symbolic continuation on a commodity CPU is unproven"
risk simply does not apply when you are not generating in real time.

### The risks, named

| Risk | Finding | Mitigation |
|---|---|---|
| **Aria real-time on commodity CPU** | ⚠️ TOP RISK. The only shipped real-time demo is MLX/Apple-Silicon, explicitly "dependent on GPU memory bandwidth." No CPU benchmark for the 1B model exists. | Scope to turn-taking (inference need not be real-time). Don't promise live jamming. |
| **Disklavier 500ms latency** | Real but specific to the Disklavier's solenoid actuation (100-500ms). | N/A — writing MIDI to a DAW does not incur it. |
| **Windows virtual MIDI port** | `python-rtmidi` raises `NotImplementedError` on Windows ("Virtual ports are not supported by the Windows MultiMedia API"). Needs loopMIDI / teVirtualMIDI / pytemidi. | Ship macOS/Linux first; document the Windows helper. |
| **Linux self-monitoring quirk** | On ALSA, RtMidi can't read its own virtual port. | The DAW (a separate client) still sees the agent's output fine. Only affects the agent monitoring its own notes. |
| **Weights vs code license** | Recurring trap: code licenses are clean (Apache/MIT) but *weights* licenses are stated separately and sometimes non-commercial. | Confirm each weights license on HuggingFace before any commercial use. Fine for a lab demo. |

### Virtual MIDI port — exact per-OS reality

- **macOS (CoreMIDI) + Linux (ALSA):** trivial. `python-rtmidi`'s
  `midiout.open_virtual_port("name")` presents a port the DAW sees as input. Low cost.
- **Windows:** no native support. Requires external tooling on Tobias Erichsen's
  teVirtualMIDI driver (loopMIDI app or the `pytemidi` wrapper).

### Model choice

**Continuation path (turn-taking responses to piano):** EleutherAI **Aria** — Apache-2.0
code/weights, purpose-built for piano continuation, with a turn-taking precedent
(Aria-Duet). Bound to piano.

**From-scratch / multi-track path (if we want full arrangements, not just piano):**

| Model | Code license | Multi-track? | Notes |
|---|---|---|---|
| **Anticipatory Music Transformer** (`jthickstun/anticipation`) | Apache-2.0 (verified LICENSE) | Yes (Lakh MIDI, multi-instrument) | Cleanest permissive choice. Does unconditional gen + continuation + accompaniment/infill. Single-stream interleaved tokens; not strongly structure-aware. Checkpoint `stanford-crfm/music-medium-800k`. Confirm weights license. |
| **MIDI-GPT** (`Metacreation-Lab/MIDI-GPT`) | MIT code | Yes (>10 tracks, 128 GM instruments) | True from-scratch + attribute-conditioned new tracks. **Weights appear CC-BY-NC-4.0 (non-commercial)** — blocks commercial use; confirm on HF. |
| **Composer's Assistant** (`m-malandro/composers-assistant-REAPER`) | MIT code + weights | Yes (infilling) | T5-like, interactive multi-track infill. REAPER-coupled, infill-oriented (not pure from-scratch). |

---

## 3. Recommended MVP shape (de-risked)

A **turn-taking call-and-response MIDI co-creation agent**:

> You play a phrase into a virtual MIDI port -> the agent captures it -> generates a
> musical response (model inference, ~1-2s is fine) -> streams the response back out
> into your DAW as editable MIDI.

- **Stack:** `mido` + `python-rtmidi`, macOS/Linux first.
- **Response engine:** start with Aria (piano, Apache-2.0, turn-taking precedent), or
  AMT for multi-instrument. A rules+heuristics fallback keeps the demo alive without a GPU.
- **Form factor:** standalone Python agent first; an MCP wrapper is a natural follow-on.

**Why this is buildable in hours-to-days:** turn-taking removes the latency
engineering; macOS/Linux removes the Windows driver pain; AMT/Aria are off-the-shelf.
The "needs real ML/latency engineering" risk only reappears if we insist on
simultaneous jamming or Windows support in v1.

---

## 4. Open questions (carry into the build decision)

1. Aria's actual per-continuation latency on a commodity laptop CPU / mid-range non-Apple
   GPU. No benchmark exists; measure before promising responsiveness.
2. Exact *weights* licenses (vs code) for MIDI-GPT, AMT checkpoints, Composer's Assistant
   on HuggingFace — confirm before any commercial path.
3. Which from-scratch model gives the most structure-aware output in practice (AMT vs
   MIDI-GPT vs Composer's Assistant vs 2025-26 releases: NotaGen, Museformer, MuseCoco, MMM).
4. Whether a scriptable Windows virtual-port path (pytemidi/loopMIDI automation) is stable
   enough to keep a cross-platform "just works" promise, or stays a manual one-time install.
5. MIDI 2.0 / MPE / hardware angle: no strong primary evidence surfaced in either pass.
   Park it unless a hardware partner or specific need appears.

---

## 5. Key sources

- AbletonMCP — https://github.com/ahujasid/ableton-mcp
- AbletonBridge — https://github.com/hidingwill/AbletonBridge
- midi-mcp-server — https://github.com/tubone24/midi-mcp-server
- mcp-server-midi — https://github.com/sandst1/mcp-server-midi
- EleutherAI Aria — https://github.com/EleutherAI/aria
- Aria-Duet ("Ghost in the Keys") — https://arxiv.org/html/2511.01663v1
- Anticipatory Music Transformer — https://github.com/jthickstun/anticipation (arXiv 2306.08620)
- MIDI-GPT — https://github.com/Metacreation-Lab/MIDI-GPT (arXiv 2501.17011)
- Composer's Assistant — https://github.com/m-malandro/composers-assistant-REAPER (arXiv 2407.14700)
- mido — https://github.com/mido/mido
- MidiTok — https://github.com/Natooz/MidiTok
- python-rtmidi (virtual ports) — https://spotlightkid.github.io/python-rtmidi/readme.html ; Windows gap: github.com/SpotlightKid/python-rtmidi/issues/105
- OBSIDIAN-Neural — https://github.com/innermost47/ai-dj
- A Design Space for Live Music Agents (CHI 2026) — https://dl.acm.org/doi/full/10.1145/3772318.3791291 ; https://live-music-agents.github.io
- Magenta RealTime — https://magenta.withgoogle.com/magenta-realtime

### Verification notes

Both passes used 3-vote adversarial verification. Claims that did not survive (logged
for honesty): "DAWs auto-recognize a virtual MIDI port" (refuted 0-3 — Windows needs a
helper); "live music agents are defined by a live MIDI listener" (refuted 1-2 — do not
assume the listen-and-react half is as mature as the emit half); "Composer's Assistant
weights are commercial-clean" (refuted 1-2). Several primary pages (arXiv, ACM, HF)
returned 403 through the agent proxy, so a few figures (CHI percentages, MIDI-GPT's
CC-BY-NC weights value) rest on multi-source search agreement rather than a direct page
read. The two MVP recommendations are syntheses, not verified existing products: their
building blocks are all verified, but musical quality and the listen-and-react half
remain the real execution risk.
