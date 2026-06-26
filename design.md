> Status: design approved for build (revised after engineering review). Source of truth for the next build session.
> Scope contract: `lab/midi-agent/scope.md`. Decided scope: ADR 0115. Research: `lab/midi-agent/research.md`.
> Appetite: 2-3 days for the PoC (M1-M4). AMT model swap (M5) is stretch, out of the critical path.

# Live MIDI Agent - Design Doc (v1 PoC)

## 1. Overview and design thesis

The Live MIDI Agent is a turn-taking, call-and-response AI musician. A human plays a musical phrase into a virtual MIDI port; the agent detects that the human's turn has ended, generates a musically-coherent answering phrase, and streams it back into the DAW as ordinary, editable MIDI notes. It is symbolic (MIDI in, MIDI out), not audio. It is phrase-level turn-taking (hundreds of ms to ~2s of response latency is fine), not sub-20ms simultaneous jamming.

### Design thesis

1. **Plumbing first, model second.** The hard, reusable value is the MIDI turn-taking loop: two virtual ports, phrase capture, handover detection, a clean response interface, and a streaming scheduler. The generation model is a hot-swappable plugin behind one interface, never a v1 dependency.

2. **The no-GPU path is the product, not a degraded mode.** The default responder is a deterministic, music-theory-aware engine that runs on any laptop with zero model download and zero GPU. It answers the human's *own* material (transpose / invert / echo, snapped to the detected key) so it reads as a musical reply, not a random transform. This guarantees every acceptance criterion is met before any model is touched.

3. **One clean seam for the model swap.** A single `Responder` abstraction means upgrading to a neural model is a config choice, not a rewrite. The swap target is chosen for license cleanliness so a future paid version is not blocked.

4. **Match the appetite.** v1 is the smallest surface that satisfies the acceptance criteria. Flat module layout, single process, stdlib + two MIDI libraries. The model path and latency optimizations are documented stretch hooks, not v1 work.

### What the research settled (do not re-litigate)

| Question | Verdict |
|---|---|
| Interaction model | Phrase-level turn-taking (Aria-Duet / "Ghost in the Keys", arXiv 2511.01663). NOT sub-20ms jamming. |
| Substrate | Python `mido` + `python-rtmidi`. `open_virtual_port()` is native on macOS (CoreMIDI) and Linux (ALSA). |
| Latency | Safe. A few-bar response is ~60-240 tokens; the only real trap is prefill, hidden during the human's turn (documented stretch, not v1). The heuristic responder is effectively instant. |
| Smart engine - no API key (RECOMMENDED for this personal build) | **Local AMT** (Anticipatory Music Transformer, `stanford-crfm/music-medium-800k`, Apache-2.0). Free, offline, no key, no metering, MIDI-native, faster-than-real-time on a consumer laptop. Best fit for the operator's no-metered-key goal (section 4.4). |
| Smart engine - with API key (best quality) | **Claude via a direct Messages API call**, Haiku tier, streaming + tool-use JSON notes + prompt caching (section 4.5). ~1s, ~a quarter-cent/turn. Use if a cheap metered key is acceptable. |
| Subscription Claude (no key) | **NOT recommended for the live loop** (section 4.6). Permitted for personal use, but latency is volatile (~3-5s, a documented regression hit ~60s), `--bare` is incompatible with subscription auth, and programmatic use may now be separately API-metered. Reserve for non-real-time use. |
| Excluded models | MIDI-GPT (CC-BY-NC weights + data); Aria (NC-data caveat, 3.11 pin, MLX-only real-time). |
| Handover | Hybrid: configurable CC67 (una corda) pedal primary + silence ladder (700ms settle / 3000ms hard override). Mandatory note-off synthesis at handover. |

## 2. System architecture

A single Python process with three cooperating threads (see section 2.1; **no asyncio in v1**). Two separate virtual MIDI ports (the Linux self-read quirk: RtMidi cannot read its own virtual output port, so input and output are distinct ports; the DAW sees both fine). Flat module layout, no package nesting, no server, no framework.

### Components

| Module | Responsibility |
|---|---|
| `ports.py` | Opens the two virtual ports: `MidiIn` "Agent In" (DAW -> agent) and `MidiOut` "Agent Out" (agent -> DAW). Registers the non-blocking input callback. Exposes a raw send primitive. Owns clean teardown (close on exit) and the same-name-port startup warning. The only module that touches RtMidi. |
| `capture.py` | `NoteRecord` dataclass + `PhraseBuffer`. The input callback (native rtmidi thread) only appends to a lock-guarded buffer, updates the held-notes set, and updates `last_event_time`. Accumulates `(pitch, velocity, start_s, end_s)` records. On handover, synthesizes note_offs for still-open notes at the handover timestamp and snapshots an immutable phrase normalized to `phrase_t0` (section 2.2). |
| `handover.py` | `HandoverDetector` + the **poll loop** (its own thread). Hybrid turn-end detection: a trigger-CC check evaluated inside the callback, plus silence/hard-override timers evaluated by the independent poll thread (because no callback fires while the human is silent). Emits a single handover event with the frozen, dangling-closed phrase. |
| `theory.py` | `MusicalContext`. Duration-weighted key/scale estimation (pitch-class histogram weighted by note length + Krumhansl-Schmuckler profile match) with a confidence threshold, tempo estimation with its own confidence floor (median inter-onset interval), and scale-snap / transpose helpers. Shared by every responder. |
| `responder.py` | `Responder` ABC + `HeuristicResponder` (default, no-GPU) + `FallbackResponder` wrapper + `AmtResponder` (stretch, guarded import). Also the small `MotifAnalyzer` and `humanize()` post-pass helpers. |
| `scheduler.py` | Output player on a single worker thread. Streams a response note list to "Agent Out" using `perf_counter`-targeted absolute sleeps (section 2.2). Tracks sounding note_ons for guaranteed cleanup. Aborts and sends all-notes-off if the human reclaims, with an echo-guard so the agent never mistakes its own output for a reclaim (section 5.1). |
| `agent.py` | Main loop / state machine (LISTEN -> HANDOVER -> RESPOND -> LISTEN). Wires the parts, owns config, installs the panic/cleanup handlers (section 5.2), CLI entrypoint (`python agent.py` / `python -m midi_agent`). |
| `config.py` | Tunables dataclass + argparse. `--trigger-cc`, `--silence-ms`, `--hard-ms`, `--poll-ms`, `--responder`, `--response-bars`, `--port-names`. |
| `tests/` | Offline tests against a fake MIDI port: handover timers, dangling-note closeout, heuristic determinism, key/tempo estimation, scheduler drift, feedback-during-respond, panic cleanup. No hardware, no DAW. |

### 2.1 Concurrency model (explicit - this is real M2 work, ~0.5 day)

The single biggest hidden-work item. The PoC uses **three threads and one queue, no asyncio**:

| Thread | Owns | Must NOT |
|---|---|---|
| **rtmidi callback thread** (native, created by python-rtmidi) | Fires only on an *incoming* message. Stamps `time.perf_counter()`, updates the lock-guarded `PhraseBuffer` (held-notes set, `last_event_time`, appended `NoteRecord`s), evaluates the immediate trigger-CC handover check, and pushes events onto a `queue.Queue`. | Do heavy work, block, or attempt any timing/sleep. It is the only writer of `last_event_time`. |
| **poll thread** (`handover.py`, plain `threading.Thread`) | Wakes every `poll_ms` (default 30ms). Reads `now - last_event_time` under the lock and checks it against `settle_ms` (held-notes empty) and `hard_ms` (override). **This is the only place silence handover can live** - a pure-callback detector never fires when the human stops playing, because no callback fires. On a fire, it signals the state machine. | Touch rtmidi directly (sends go through the scheduler/state machine). |
| **main / state-machine thread** (`agent.py`) | Owns the LISTEN/HANDOVER/RESPOND machine. Drains the queue, runs `theory` + `responder.respond()` at handover, and drives `scheduler.py` (which streams notes via `perf_counter`-targeted `time.sleep` on this same worker path). | - |

Rationale for dropping asyncio (was punch-list low #9): the scheduler's job is literally `sleep, emit, sleep, emit`, which is a plain thread with `time.sleep` to absolute `perf_counter` targets. asyncio buys nothing here and would force a `loop.call_soon_threadsafe` bridge from the native callback thread (a known fragility). A `queue.Queue` between callback and state machine is simpler and equally low-latency at phrase granularity.

### 2.2 Coordinate-system contract (one rule, no ambiguity)

Three zero-points exist; each is owned by exactly one module. **Never sum per-note sleeps** (drift across a multi-note response).

1. **Capture normalizes to `phrase_t0`.** At `snapshot()`, `phrase_t0 = perf_counter` of the phrase's first note. Every `NoteRecord.start_s` / `end_s` in the frozen phrase is `(absolute_perf_counter - phrase_t0)`. So the snapshot starts at `0.0`.
2. **`respond()` emits offsets from 0.** The returned response note list is anchored so the first response event is at `t=0` (conceptually the handover instant). Responders never see wall-clock time.
3. **Scheduler uses absolute targets.** On RESPOND entry it captures `play_t0 = perf_counter()`. For each note it sleeps to the **absolute** target: `time.sleep(max(0, (play_t0 + note.start_s) - perf_counter()))`, then emits note_on; the matching note_off is scheduled the same way at `play_t0 + note.end_s`. No cumulative addition of sleep durations.

`NoteRecord` invariant: `start_s < end_s` always (no dangling); enforced in `PhraseBuffer.snapshot()` and unit-tested. A `test_scheduler.py` drift test feeds a long response and asserts emitted timestamps track the absolute targets within tolerance.

### ASCII data-flow diagram

```
        DAW (human plays a phrase)
                  |
                  v   MIDI note_on / note_off / CC
        +-------------------------+
        |  virtual port "Agent In"|  (MidiIn, python-rtmidi)
        +-------------------------+
                  |  non-blocking input callback (NATIVE rtmidi thread)
                  |  -> stamp perf_counter, update held-notes + last_event_time
                  |  -> append NoteRecord, push event to queue.Queue
                  |  -> immediate trigger-CC handover check only
                  v
        +-------------------------+        +---------------------------+
        |  capture.PhraseBuffer   | <----- |  poll thread (every 30ms) |
        |  (lock-guarded)         |  reads |  silence settle > 700ms   |
        |  held-notes set         |  time  |  OR hard override > 3000ms|
        |  last_event_time        |        |  (silence CANNOT live in  |
        |  [NoteRecord, ...]      |        |   the callback)           |
        +-------------------------+        +---------------------------+
                  |                                   |
                  |   queue.Queue                     | fire signal
                  v                                   v
        +-----------------------------------------------------------+
        |  agent.py  state machine  (main thread)                   |
        |  on fire: close dangling notes, freeze snapshot @phrase_t0|
        +-----------------------------------------------------------+
                  |
                  v
        +-------------------------+   duration-weighted key/scale (+confidence),
        |  theory.MusicalContext  |   tempo (+confidence floor)
        +-------------------------+
                  |  phrase + context
                  v
        +-------------------------+
        | responder.respond()     |   FallbackResponder wraps the chosen
        |  HeuristicResponder      |   engine; ImportError/exception ->
        |  (default, no GPU)       |   HeuristicResponder. (timeout: M5
        |  [AmtResponder stretch]  |   process-kill only, see 4.3)
        +-------------------------+   -> humanize() post-pass
                  |  response: [NoteRecord, ...], offsets from 0
                  v
        +-------------------------+   play_t0 = perf_counter() at entry;
        |  scheduler (worker thrd)|   sleep to ABSOLUTE (play_t0+offset);
        |  streams note-by-note   |   track sounding notes; echo-guard +
        |  abort on reclaim       |   panic cleanup on exit/exception
        +-------------------------+
                  |
                  v
        +-------------------------+
        | virtual port "Agent Out"|  (MidiOut, python-rtmidi)
        +-------------------------+
                  |
                  v
        DAW (records response as editable MIDI)
                  |
                  +--> back to LISTEN, clear buffer
```

## 3. The turn-taking state machine

Three states owned by `agent.py`. Single process; capture runs in the rtmidi callback thread, silence detection on the poll thread, the scheduler on a worker thread, the state machine coordinates (section 2.1).

```
        +-----------+   handover fires (CC67 | silence | hard)
        |           |   -> close dangling notes, freeze snapshot
        |  LISTEN   | ----------------------------------------+
        |           |                                         |
        +-----------+                                         v
            ^   ^                                       +-----------+
            |   | response done                         |  HANDOVER |
            |   | (or aborted)                          | (instant) |
            |   |                                        +-----------+
            |   |                                              |
            |   |                                  theory -> respond()
            |   |                                              |
            |   |                                              v
            |   |                                        +-----------+
            |   |  human reclaims (re-press CC67 or      |  RESPOND  |
            |   +-- plays a non-echo note) -> abort,     | (stream)  |
            |       all-notes-off                        +-----------+
            +-----------------------------------------------+
              clear buffer, re-arm capture
```

| State | Enter on | Does | Exit on |
|---|---|---|---|
| LISTEN | startup; response complete; reclaim | Callback stamps + accumulates notes; poll thread watches the silence timers; detector watches each message for the trigger CC | handover fires |
| HANDOVER | detector fires | Synthesize note_offs for open notes; freeze immutable phrase normalized to `phrase_t0`; run `theory` for key/tempo; call `responder.respond()` | always proceeds to RESPOND (instant) |
| RESPOND | responder returns a note list | Scheduler streams notes to "Agent Out" (absolute-target sleeps); watches "Agent In" for reclaim **through the echo-guard** | last note played, OR human reclaims (abort + all-notes-off) |

**Reclaim (barge-in):** during RESPOND, if the human re-presses the trigger CC or plays a note that is **not** part of the agent's own output (echo-guard, section 5.1), the scheduler cancels, sends all-notes-off on "Agent Out", and returns to LISTEN. This mirrors Aria-Duet's "re-press to reclaim" and prevents the agent talking over the human.

## 4. The ResponseEngine abstraction

One interface. The MIDI core (capture / handover / scheduler / theory) never imports a model.

```python
@dataclass(frozen=True)
class NoteRecord:
    pitch: int          # 0-127
    velocity: int       # 1-127
    start_s: float      # seconds; phrase: relative to phrase_t0; response: offset from 0
    end_s: float        # seconds; start_s < end_s always (no dangling)
    channel: int = 0

class Responder(ABC):
    @abstractmethod
    def respond(self, phrase: list[NoteRecord], ctx: MusicalContext) -> list[NoteRecord]:
        """Return an answering phrase, anchored to start at t=0 (handover instant)."""
```

### 4.1 HeuristicResponder (default, no GPU, always importable)

The v1 deliverable. Pure stdlib + simple math. Answers the human's own material so it reads as a duet, not a transform demo.

- **MotifAnalyzer:** extracts the phrase's interval contour, rhythm cells, and the last-N-note tail motif.
- **Response menu** (selectable / weighted): (1) transpose the tail motif up/down a diatonic third, snapped to key; (2) mirror/invert the contour around the phrase center pitch; (3) arpeggiate the implied chord in the detected scale; (4) harmonize with diatonic thirds/sixths. Default = restate-then-vary (echo the rhythm grid, transform the pitch in-key).
- **Coherence:** every output pitch is scale-snapped to the detected key; the response reuses the phrase's relative onset spacing as a literal rhythm template (honestly: a *smart echo*, see section 6); velocity and register are echoed from the call.

### 4.2 humanize() post-pass (applies to ANY responder)

A single function over the response note list, so the feel is uniform whether the source is rules or a model:

- small Gaussian jitter on micro-timing (a few ms) and velocity,
- "leave space": prefer phrase lengths that breathe, insert occasional rests rather than filling every beat.

Tunable and bypassable (a flag) for rubato playing.

### 4.3 FallbackResponder (no-GPU guarantee - scoped honestly)

The no-GPU fallback is **structural, not a remembered code path**. The factory always wraps the chosen responder:

```python
class FallbackResponder(Responder):
    def __init__(self, primary: Responder, fallback: HeuristicResponder, timeout_s: float | None):
        ...
    def respond(self, phrase, ctx):
        try:
            return self.primary.respond(phrase, ctx)   # may be process-isolated (M5)
        except (ImportError, Exception):
            log.warning("primary responder failed; using heuristic")
            return self.fallback.respond(phrase, ctx)
```

**What the wrapper actually guarantees (and what it does not):**

- **ImportError / exception fallback is real and clean.** A missing `torch`, an absent checkpoint, or a crash in the primary -> the heuristic answers. When `--responder heuristic` (the default), the primary *is* the heuristic and the wrapper is a no-op.
- **Timeout fallback is NOT honest for in-process blocking inference.** A blocking `torch.generate()` cannot be interrupted by a Python timeout: you cannot safely kill a thread mid-CUDA-kernel, and signal-based timeouts are main-thread-and-Unix-only. So a slow inference blocks the turn for its full duration regardless of `timeout_s`. Therefore in v1 `timeout_s` is `None` and the timeout path is unused. **Real timeout requires running the model in a separate process (`concurrent.futures.ProcessPoolExecutor`) that can actually be terminated, which is deferred to M5.** The PoC does not depend on it because the default responder is instant. (See punch-list high #2.)

The cleaner long-term answer is prefill/generate during the human's turn (latency hidden, timeout moot), documented as a no-op stretch hook (section 4.4).

### 4.4 AmtResponder (the model swap, STRETCH / M5)

**Chosen model: Anticipatory Music Transformer (AMT), `stanford-crfm/music-medium-800k`.** Why AMT and not the alternatives:

| Model | Weights license | Data license | Integration | Verdict |
|---|---|---|---|---|
| **AMT** (`stanford-crfm/music-*-800k`) | **Believed Apache-2.0** (confirm, sec 11) | **CC-BY-4.0** (Lakh) | One-line stock HF `AutoModelForCausalLM`; `midi_to_events` / `generate` / `events_to_midi`; multi-instrument | **Chosen.** Easiest end-to-end + cleanest permissive license, no NC flag found. |
| Aria (`loubb/aria-medium-base`) | Apache-2.0 | CC-BY-NC-SA-4.0 (Aria-MIDI) | Repo clone, Python 3.11 pin, `ariautils`, MLX-only real-time | Deferred. Unsettled NC-data caveat + more friction. |
| MIDI-GPT | **CC-BY-NC-4.0** | NC (GigaMIDI) | MIT code | **Excluded.** Non-commercial weights AND data. Never ship in a paid build. |
| Composer's Assistant | MIT | public-domain/permissive | REAPER-coupled, infill-shaped | Cleanest data provenance, but heavier to adapt to turn-taking. Future option, not v1. |

Integration shape (guarded import so missing torch never breaks v1; process-isolated so a real timeout is possible):

```python
from transformers import AutoModelForCausalLM           # guarded
from anticipation.convert import midi_to_events, events_to_midi
from anticipation.sample import generate

model = AutoModelForCausalLM.from_pretrained("stanford-crfm/music-medium-800k")  # .cuda() optional
history = midi_to_events(temp_phrase_mid)               # snapshot -> temp .mid -> events
events = generate(model, start_time=t_end, end_time=t_end+resp_len, inputs=history, top_p=.98)
events_to_midi(events).save(temp_resp_mid)              # read back -> NoteRecord list
```

The agent never touches tokens directly; `midi_to_events` / `events_to_midi` is the tokenizer boundary. Do NOT import MidiTok (vocab mismatch with the pretrained checkpoint).

**Latency verdict (why the swap is safe when it lands):** AMT-medium is ~360M params; a few-bar response is ~60-240 tokens. On a GPU or Apple Silicon this is well under 1s; on a strong laptop CPU ~1-3s, which is inside the turn-taking budget. Stream note-by-note so perceived latency = time-to-first-note. The one real latency trap (1-2s prefill of the human phrase after handover) is removed by prefilling during the human's turn; that **prefill-during-listen optimization is a documented stretch hook (no-op by default), not v1 work.**

### 4.5 ClaudeResponder (the flagship smart engine - RECOMMENDED model swap)

Added after a dedicated third research pass (`research-claude-engine.md`). **Claude (the Anthropic LLM) is the recommended "smart" engine, and it supersedes AMT for most cases:** it needs no GPU, no model download, and no weights-license question, and it plugs into the exact same `Responder` interface. The full LLM-to-MIDI-to-DAW path is proven in shipping prior art (`sandst1/llmjam` runs a Claude call-and-response loop; `sandst1/mcp-server-midi`, AbletonMCP, JAMMIN-GPT corroborate).

**Verdict (research-backed): GO as an ADDITIONAL engine, not a blind default.** The heuristic stays the always-works offline default; Claude is the flagship engine selected for the real demo. Two reasons it is not the unconditional default: (1) Claude's specific composition *musicality* is unverified (the prior art proves the wiring, not the song quality; one study had a fine-tuned 7B model beat GPT-4 at composition), and (2) no source publishes a measured end-to-end music-loop latency, so the latency case rests on Haiku TTFT benchmarks plus streaming, not a measured loop.

**Integration path: a DIRECT Anthropic Messages API call from the Python agent.** Not Claude Code + an MCP MIDI server (adds CLI/tool-call latency, documented as not built for real-time; better for offline arrangement) and not the heavier Agent SDK. The agent already owns the ports and the `Responder` seam, so the engine only takes a phrase and returns notes.

| Decision | Choice | Why |
|---|---|---|
| Model | **Claude Haiku** (fastest tier) | TTFT ~sub-500ms to ~0.84s; Sonnet ~500-800ms, Opus ~1-2s. Live loop wants the fastest. Sonnet as a quality-up option. |
| Note format | **JSON note-events via tool-use / structured output** (pitch 0-127, velocity, start_s, end_s, channel) - the same `NoteRecord` shape | Reliable formatting; parseable incrementally while streaming; avoids ABC notation's observed Irish/folk style bias. ABC is what quality studies validated but it biases style. |
| Streaming | **On** | Play the first notes while later ones generate; perceived latency = time-to-first-note. |
| Prompt caching | **On** | A stable musician system prompt cached at $0.10/MTok read cuts per-turn cost and TTFT across a sustained jam. |
| Cost | **~a fraction of a cent / turn on Haiku** | Haiku ~$1/$5 per MTok in/out (approx, mid-2026). A few hundred input + ~100-500 output tokens per turn. A long session costs cents. Not a constraint. |

Integration shape (guarded import so a missing key/SDK never breaks the heuristic default; wrapped by `FallbackResponder` exactly like AMT):

```python
import anthropic   # guarded import; only needed for --responder claude

client = anthropic.Anthropic()                  # ANTHROPIC_API_KEY from env
# system prompt = the musician persona + the JSON note schema (prompt-cached)
# user message = the captured phrase as JSON NoteRecords + MusicalContext (key, tempo)
with client.messages.stream(
    model="claude-haiku-4-5",
    max_tokens=600,
    system=MUSICIAN_SYSTEM,                      # cache_control: ephemeral
    tools=[RESPOND_TOOL],                         # structured note-list output
    messages=[{"role": "user", "content": phrase_json}],
) as stream:
    for event in stream:                          # parse note-events incrementally,
        ...                                       # hand each completed note to the scheduler
```

The `MusicalContext` (key, tempo) computed in `theory.py` is passed in the prompt so Claude answers in key and in time; the same `humanize()` post-pass and scale-snap guard apply to Claude's output, so a stray out-of-key note is corrected before playback. Carry only compact musical context across turns (key, tempo, last phrase), not full history, to keep input tokens and latency low.

**What this simplifies:** Claude-as-engine makes AMT (section 4.4) the *deprioritized local alternative*, not the primary model swap. No GPU, no `torch`/checkpoint download, no weights-license spot-check, no process-isolation-for-timeout machinery (an HTTP call has a normal request timeout). The trade is an API key + network dependency, which is why the offline heuristic remains the default.

**Failure modes + mitigations (LLM music specifics):** invalid/typo'd notes -> tool-use schema validation + drop-and-continue; key drift -> pass the detected key and scale-snap the output; repetition/rambling -> cap `max_tokens` (~2 bars) and prompt for a concise answer; style bias -> JSON format (not ABC) + an explicit style hint in the prompt; network/timeout/no-key -> `FallbackResponder` drops to the heuristic.

### 4.6 ClaudeCodeResponder (subscription / no API key) - NOT recommended for the live loop

A dedicated fresh deep-research pass (`research-claude-engine.md`, "Subscription path")
evaluated driving Claude on a Pro/Max **subscription** via Claude Code headless mode
(`claude -p`), to avoid a metered API key. **Verdict: permitted, but NO-GO as the live
generative engine.** It stays documented as a non-real-time option, not the live path.

- **Terms: allowed for personal use (not the blocker).** Anthropic's legal docs bless
  OAuth/subscription login for "ordinary, individual use of Claude Code and the Agent
  SDK." Only multi-user/third-party routing (offering Claude.ai login to others,
  routing other users' requests) is prohibited. A single user automating their own
  subscription is fine; switch to an API key only if it is ever distributed.
- **Latency: volatile and not loop-safe.** Good-case headless is ~3-5s/turn (already
  marginal for music), but a documented Jan-2026 regression spiked *every* call to a
  near-constant ~60s regardless of prompt. You cannot build an instrument on timing you
  cannot trust. `--bare` (the fast-startup mode) is **incompatible with subscription
  auth** (it requires an API key), so the fastest path is closed; a warm session via the
  Agent SDK streaming-input mode is the best available but still heavy.
- **Cost premise is undercut.** A mid-2026 metering change reportedly moved programmatic
  surfaces (`claude -p`, Agent SDK) onto a *separate, API-priced* credit pool rather
  than the flat subscription, defeating the "use my subscription instead of paying per
  token" goal. (Contested and time-sensitive: one June-2026 source says programmatic use
  still draws on the subscription as before. Verify current Anthropic billing before
  relying on either reading.)

If used at all, it is for **non-real-time** work (compose a seed phrase between
sessions, generate practice material), via a warm Agent SDK streaming-input session
(`--output-format stream-json --verbose --include-partial-messages`, OAuth login, NOT
`--bare`), selected via `--responder claude-code`, always wrapped by `FallbackResponder`.
Note: the `claude -p ... --input-format stream-json` stdin protocol is thinly documented
(GitHub #24594); prefer the Agent SDK's `ClaudeSDKClient` streaming-input mode over
hand-rolled stdin NDJSON.

**The no-API-key recommendation is therefore LOCAL, not the subscription:** use **local
AMT** (section 4.4) as the recommended smart engine - it is free, offline, no key, no
metering, MIDI-native, and runs faster-than-real-time on a consumer laptop (its MLC port
MIDInfinite hits ~51 notes/sec). The thing the operator actually wanted (no metered key,
no per-token cost) is best delivered by local AMT, not by the subscription (which may now
meter this use anyway). The API-key Haiku path (4.5) remains the best-quality option for
anyone who will accept a cheap metered key (~1s, ~a quarter-cent/turn).

## 5. Handover, feedback, and safety

### 5.0 Handover / phrase-end detection

Hybrid detector: explicit pedal primary + silence ladder fallback, exactly per research (Aria-Duet + Google AI Duet). The trigger-CC check is evaluated in the callback; the silence/hard timers are evaluated by the **independent poll thread** (section 2.1), because no callback fires while the human is silent.

**PRIMARY (explicit trigger, evaluated in the callback):**

```python
if msg.type == "control_change" and msg.control == cfg.trigger_cc and msg.value >= 64:
    fire_handover()
```

Default `trigger_cc = 67` (una corda / soft pedal) so it never collides with normal sustain (CC64). Configurable to CC64 (a sustain footswitch) or, when no third pedal exists, a computer hotkey. Re-pressing during RESPOND is a reclaim/barge-in.

**FALLBACK LADDER (poll thread, fires only when no trigger arrives):**

1. held-notes set empty AND `now - last_event_time > settle_ms` (default **700ms**) -> snappy call-and-response.
2. hard override at `now - last_event_time > hard_ms` (default **3000ms**) -> forces a response even if a note is still held.

The settle threshold is the single most interaction-defining knob (too short = barge-in, too long = sluggish), so it is a front-and-center CLI flag.

**CRITICAL at fire (mandatory, all engines):** synthesize note_offs for every still-open note at the handover timestamp **before** freezing the snapshot. Aria-class models corrupt continuations on dangling note_ons / truncated durations (Aria-Duet spends ~100-200ms correcting exactly this), and even the heuristic responder wants complete note lengths for mirroring/harmonizing. Enforced in `PhraseBuffer.snapshot()`, not optional.

**STRETCH:** replace the fixed 700ms with an adaptive threshold `~2-3x running-median-IOI` so it tracks tempo (patient for ballads, snappy for fast runs). Ship the fixed threshold first.

### 5.1 MIDI feedback / echo guard (named risk, was unaddressed)

The agent writes to "Agent Out"; the DAW records it on an armed track. Many DAWs echo an armed track's input/thru back out ("MIDI Thru" / input monitoring). If that thru reaches "Agent In", the agent hears its own response, mistakes it for a human reclaim, aborts itself, and may re-trigger handover. The two ports are logically separate, but the reclaim detector watching "Agent In" during RESPOND can still be fooled by DAW thru. (Punch-list high #3.)

**Mitigation (both layers):**

1. **Echo-guard in code.** While in RESPOND, the scheduler records every `(pitch, channel)` note_on it emits with a timestamp. A note_on seen on "Agent In" that matches a recently-emitted output note within a short window (e.g. 150ms) is treated as the agent's own echo and **ignored for reclaim**. Reclaim fires only on a trigger CC or a note that does not match the current response set.
2. **README warning.** Tell the user to disable input-monitoring / MIDI-thru on the armed "Agent In" track, and never route "Agent Out" back into "Agent In".

A `test_feedback.py` case feeds the agent's own emitted notes back on "Agent In" during RESPOND and asserts no spurious reclaim.

### 5.2 Stuck-note / panic cleanup (guaranteed on any exit)

Aborting on reclaim is handled, but process death, Ctrl-C, or an exception between a note_on and its note_off leaves notes stuck ON until the user manually panics. (Punch-list medium #6.)

**Mitigation:**

- The scheduler tracks the set of currently-sounding `(pitch, channel)` note_ons.
- `agent.py` installs an `atexit` handler and SIGINT/SIGTERM handlers; the scheduler runs its emit loop under `try/finally`.
- On any exit or exception, cleanup sends **explicit note_offs for every tracked sounding note** AND CC123 (all-notes-off) on all 16 channels of "Agent Out" (some synths ignore CC123, hence the explicit offs too).

A `test_panic.py` case raises mid-response and asserts every emitted note_on has a matching note_off after cleanup.

## 6. Musical-coherence strategy

`theory.MusicalContext` is the coherence backbone. Computed from the frozen phrase at handover; consumed by every responder.

- **Key / scale (duration-weighted):** a 12-bin pitch-class histogram **weighted by each note's duration** (not raw count, so a short staccato run does not skew the estimate), correlated against Krumhansl-Schmuckler major/minor profiles -> best key + mode. Every generated note is scale-snapped to the nearest in-key pitch, so transposition/harmony never leaves the tonality. (Punch-list medium #5.)
- **Key confidence threshold:** a short or sparse phrase (e.g. 3 notes) gives a weak histogram. Below a confidence floor, fall back to the last-known key (or a user `--key` scale-lock) rather than guessing wrong and answering out of key, the single most audible failure mode.
- **Tempo / timing (honest scope + its own confidence floor):** v1 does **not** do true beat induction. It estimates a rough pulse from the median inter-onset interval, and the response **reuses the call's literal onset spacing as a rhythm template**. State this plainly: for many inputs this is effectively a *smart echo*, which is honest and fine for a PoC. Median-IOI is fragile on dotted rhythms, held-note-then-run phrases, and free rubato, so tempo gets a confidence floor too: if IOIs are too few or too irregular, fall back to the prior phrase's spacing or a simple fixed grid rather than emitting a misaligned answer. True tempo/beat induction is out of scope (section 12). (Punch-list medium #5.)
- **Call-and-response logic:** the MotifAnalyzer answers the human's *own* tail motif (transpose / invert / augment) rather than emitting generic in-key licks. A "question" phrase ending off-tonic gets a "resolution" toward tonic.
- **Dynamics / feel:** match the velocity envelope and register of the call; apply the `humanize()` post-pass.

The same `MusicalContext` is exactly what the AMT path would consume (key/tempo metadata + a light post-pass scale-snap of stray model output), so the coherence logic survives the model swap.

## 7. Tech stack and module layout

### Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | (AMT path is fine on 3.10+; Aria's 3.11 pin is deferred with Aria) |
| Virtual ports / low-level I/O | `python-rtmidi` | `open_virtual_port()`; the two-port Linux-quirk-safe setup |
| Message ergonomics | `mido` | `Message` objects; optional `.mid` serialization for the model boundary |
| Concurrency / timing | stdlib `threading`, `queue.Queue`, `time.perf_counter`, `time.sleep` | three threads (callback / poll / state+scheduler). **No asyncio in v1** (section 2.1) |
| Data / config | stdlib `dataclasses`, `math`, `argparse` | key histogram + IOI stats are simple math, no numpy needed for v1 |
| Tests | `pytest` | offline, fake-port |
| Local AMT engine (RECOMMENDED no-key, M5) | `transformers` + `torch` + `jthickstun/anticipation` | in `requirements-model.txt`, NOT installed by default; the recommended no-API-key smart engine (section 4.4) |
| Claude API engine (OPTIONAL, needs key, M6) | `anthropic` SDK + `ANTHROPIC_API_KEY` | in `requirements-claude.txt`, NOT installed by default; best-quality option for whoever accepts a metered key (section 4.5) |

### File layout

```
lab/midi-agent/
  agent.py              # main loop + state machine + CLI + panic/cleanup handlers
  ports.py              # two virtual ports; callback reg; send primitive; teardown + name-collision warn
  capture.py            # NoteRecord; PhraseBuffer (lock-guarded, dangling closeout, phrase_t0 normalize)
  handover.py           # HandoverDetector + poll-thread silence/hard timers (+ trigger-CC check)
  theory.py             # MusicalContext (duration-weighted key + confidence, tempo + floor, snap, transpose)
  responder.py          # Responder ABC; HeuristicResponder; MotifAnalyzer; humanize();
                        #   FallbackResponder; ClaudeResponder (guarded import, M5);
                        #   AmtResponder (guarded import, M6 optional)
  scheduler.py          # worker-thread player (absolute-target sleeps), echo-guard, sounding-note tracking
  config.py             # tunables dataclass + argparse
  tests/
    fake_port.py        # in-memory MIDI port double
    test_handover.py    # poll-timer fires + dangling-note closeout
    test_theory.py      # duration-weighted key/tempo estimation + confidence fallbacks
    test_heuristic.py   # responder determinism + in-key guarantee + dangling-free
    test_scheduler.py   # absolute-target timing, no cumulative drift
    test_feedback.py    # agent's own output on Agent In during RESPOND -> no spurious reclaim
    test_panic.py       # exception mid-response -> every note_on gets a note_off
  requirements.txt      # python-rtmidi, mido
  requirements-claude.txt# anthropic  (NOT installed by default; the recommended M5 smart engine)
  requirements-model.txt # transformers, torch, anticipation  (NOT installed by default; optional M6)
  README.md             # per-OS setup, DAW arm steps, Linux own-port quirk, feedback/thru warning, run command
```

No package nesting, no server. `CLAUDE.md` / `STATUS.md` / `scope.md` / `brief.md` / `research.md` already exist in the folder.

## 8. Cross-platform virtual-MIDI notes

| OS | Virtual port support | Notes |
|---|---|---|
| **macOS** | Native (CoreMIDI) | `open_virtual_port()` works directly. Both "Agent In" and "Agent Out" appear in the DAW's MIDI prefs and IAC routing. Reference platform; the only published real-time Aria demo is Apple-Silicon/MLX. |
| **Linux** | Native (ALSA) | `open_virtual_port()` works. **Quirk: RtMidi cannot read its OWN virtual output port.** This is *why* we use two separate ports (a MidiIn and a MidiOut), not one. The DAW sees both fine. M1 loopback proof validates this before any logic. Stale ports can linger after an unclean exit (section 9, M1). |
| **Windows** | **No native virtual ports.** | Document the workaround: install **loopMIDI**, create two loopback ports, point the agent at them by name (`--port-names`). Not a v1 target (per scope no-gos); the code path is identical, only the port creation differs. |

The agent side is DAW-agnostic. README ships per-DAW arming notes (Logic / Ableton / Reaper / Bitwig / GarageBand) since MIDI track arming differs, plus the feedback/thru warning from section 5.1.

## 9. Build plan (ordered, demoable milestones)

Front-load the highest substrate risk (the two-port Linux quirk + DAW round-trip) before any logic.

| Milestone | ~Effort | Deliverable / demo | De-risks |
|---|---|---|---|
| **M1 - Loopback / port proof** | ~0.5 day | Open "Agent In" + "Agent Out". (a) Agent receives on Agent In and prints incoming messages. (b) Agent emits a **distinct test pattern (a C-major scale)** on Agent Out that the DAW records as editable MIDI - NOT a raw echo of input (avoids feedback and gives an unambiguous "the DAW saw our output" signal). Clean teardown on exit; warn if a same-named port already exists. | The two-port Linux self-read quirk, the DAW round-trip, feedback-path awareness, and port teardown/collision discipline, all before any logic. |
| **M2 - Capture + handover + concurrency** | ~1 day | Lock-guarded `PhraseBuffer` (held-notes / last_event / accumulation / dangling closeout / `phrase_t0`) + the **callback->queue + poll-thread** wiring (section 2.1) + `HandoverDetector` silence ladder (700/3000ms). Demo: play a phrase, console prints "handover detected, N notes captured" with the frozen snapshot. | Phrase capture timing, the mandatory note-off synthesis, and the explicit three-thread concurrency model (the biggest hidden-work item, budgeted here, not free). |
| **M3 - Heuristic responder + scheduler** | ~1 day | `theory.py` (duration-weighted key + confidence + tempo floor) + `HeuristicResponder` (transpose-in-key first, then mirror / arpeggiate / harmonize + MotifAnalyzer) + `humanize()` + worker-thread scheduler streaming to "Agent Out" with **absolute-target sleeps** + sounding-note tracking. **THE CORE DEMO: play a phrase, the agent answers in key into the DAW as editable MIDI.** | Musical coherence, the streaming output path, and timing-drift correctness. Meets every acceptance criterion. |
| **M4 - Trigger + safety + polish** | ~0.5 day | Wire CC67 (configurable) primary handover + hotkey fallback; reclaim/barge-in abort **with echo-guard**; panic/all-notes-off cleanup on exit; config flags; README per-OS + DAW arming + Windows loopMIDI + feedback/thru caveat. **Tunable, demoable PoC complete.** | UX knobs, the feedback failure mode, the stuck-note failure mode, and onboarding. |
| **M5 - Local AMT engine (RECOMMENDED next step, no API key)** | +1-2 days | `AmtResponder` (section 4.4) behind the same interface: guarded import (`transformers` + `anticipation`), `FallbackResponder` wrapping it, `midi_to_events`/`generate`/`events_to_midi` round-trip, melody-conditioned accompaniment, `humanize()`/scale-snap post-pass. Swap via `--responder amt`. | The no-key "smart" engine the operator actually wants: free, offline, MIDI-native. Lifts the demo from rule-based to model-composed with no metered key. |
| **M6 - Claude API engine (OPTIONAL, best quality, needs a key)** | +0.5-1 day | `ClaudeResponder` (section 4.5): guarded `anthropic` import, direct Haiku Messages call with streaming + tool-use JSON notes + prompt caching. Swap via `--responder claude` (needs `ANTHROPIC_API_KEY`). | Frontier-quality option for whoever accepts a cheap metered key. Subscription-headless (4.6) is NOT a live-loop option. |

M1-M4 = the shippable PoC (heuristic engine). M5 (local AMT) is the recommended next step for a no-API-key personal build and delivers the "AI duet partner" headline offline. M6 (Claude API) is the optional best-quality upgrade. `FallbackResponder`, the echo-guard, the panic cleanup, and `tests/` are built incrementally across M2-M4 (not deferred), since they de-risk the core.

## 10. Testing and verification

The biggest de-risker for a hardware-in-the-loop build is being able to iterate **without a DAW**.

- **Fake MIDI port (`tests/fake_port.py`):** an in-memory double for the rtmidi port. Lets the whole core (capture -> handover -> responder -> scheduler) run offline by feeding scripted message streams and asserting on the output message list. The poll-thread timers are driven by an injectable clock so silence handover is testable without real waits.
- **Offline unit tests (pytest):**
  - `test_handover.py`: settle timer fires (via the poll thread) only when held-notes is empty; hard override fires with a note held; trigger CC fires immediately; dangling note_ons are closed at the handover timestamp (no `start_s >= end_s`).
  - `test_theory.py`: duration-weighted key estimation on known phrases; tempo from synthetic IOIs; confidence fallback to last-known key on a 3-note phrase; tempo-confidence fallback on irregular IOIs.
  - `test_heuristic.py`: determinism (same phrase + context -> same notes); the in-key invariant (every output pitch is in the detected scale); the dangling-free invariant.
  - `test_scheduler.py`: emitted note timestamps track absolute `play_t0 + offset` targets within tolerance across a long response (no cumulative drift).
  - `test_feedback.py`: feeding the agent's own emitted note_ons back on "Agent In" during RESPOND triggers no reclaim (echo-guard).
  - `test_panic.py`: an exception mid-response leaves no stuck notes (every emitted note_on has a matching note_off after cleanup).
- **Manual hardware verification (the acceptance gate):** run the agent, arm a virtual-port MIDI track in a DAW (input monitoring/thru off, per section 5.1), play a phrase, confirm an audible, in-key, editable MIDI response, and that turn-taking loops without a restart. Done once per OS that is in scope (macOS / Linux). This is the only step that needs a DAW; everything else is covered offline.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Silence handover never fires** (a pure-callback detector can't, since no callback fires while the human is silent) | Independent **poll thread** (~30ms) owns the silence/hard timers; the callback only stamps + appends. Explicit M2 work (section 2.1). |
| Linux own-port read quirk makes the agent appear deaf | Two separate ports (MidiIn "Agent In" + MidiOut "Agent Out"); M1 proof (distinct test pattern, not echo) + explicit README note. macOS unaffected, same code path. |
| **MIDI feedback / DAW thru during RESPOND self-triggers a reclaim** | Echo-guard: scheduler ignores incoming note_ons on "Agent In" that match recently-emitted output within a short window; reclaim requires a trigger CC or a non-echo note. README: disable input-monitoring/thru on the armed track; never route Agent Out back to Agent In. Tested (`test_feedback.py`). |
| **Stuck/hung notes on crash, Ctrl-C, or mid-response exception** | `atexit`+SIGINT/SIGTERM handlers and a `try/finally` send explicit note_offs for all tracked sounding notes plus CC123 on all 16 channels of Agent Out. Tested (`test_panic.py`). |
| **Timing drift across a multi-note response** | Scheduler sleeps to absolute `play_t0 + note.start_s` targets, never sums per-note sleeps (section 2.2). Tested (`test_scheduler.py`). |
| Output timing jitter (Python sleep-based scheduling under load) | Acceptable at phrase-level (hundreds of ms tolerated). `perf_counter`-relative absolute targets keep it tight enough; tightening is a later concern. |
| Handover threshold feel (700ms eager for ballads / sluggish for fast runs) | Front-and-center CLI flag; pedal primary sidesteps it; adaptive-IOI as a documented stretch. |
| Dangling note_ons at handover corrupt the response | Mandatory note-off synthesis in `PhraseBuffer.snapshot()`, enforced and unit-tested, not optional. |
| **Tempo/median-IOI is fragile and could sound like a delay effect** | Honest downscope: v1 reuses the call's onset spacing as a literal rhythm template (a "smart echo"); tempo has its own confidence floor (fall back to prior spacing / fixed grid on too-few/irregular IOIs); true beat induction is out of scope. Krumhansl-Schmuckler is duration-weighted. |
| Rule responder sounds mechanical | MotifAnalyzer (answer the human's own material) + key/tempo-aware snapping + restate-then-vary default + `humanize()` jitter/leave-space. Model swap is the upgrade path if musicality is still the bottleneck. |
| Key estimation wrong on short/sparse phrases (out-of-key answer = most audible failure) | Confidence threshold -> fall back to last-known key or `--key` scale-lock rather than guess. |
| No-GPU guarantee is fragile | `FallbackResponder` makes ImportError/exception fallback structural. **Timeout fallback is honestly NOT guaranteed for in-process blocking inference** (no safe thread kill mid-CUDA-kernel); real timeout needs process isolation, deferred to M5. The instant heuristic default means the PoC never depends on it. |
| Model-path latency creep (if M5 lands) | Bounded by the heuristic default; process-isolated AMT can be terminated; AMT targets GPU / Apple Silicon where the budget is comfortable; keep responses short (~2 bars) on CPU. |
| **Port-name collision / stale ports on re-run** | Clean teardown in finally/atexit; startup warning if a same-named port already exists; README note that a hard kill may require reopening the DAW's MIDI prefs (Linux/ALSA). Folded into M1. |
| Licensing / provenance for a future paid build | AMT (**believed** Apache-2.0 weights, CC-BY-4.0 data) is the chosen clean swap. MIDI-GPT excluded entirely. Aria deferred (unsettled NC-data caveat). Interface isolation keeps this a config choice. **The Apache-2.0 weights claim rests on multi-source search agreement (HF model card was 403 in the research env); do a 2-minute manual spot-check of the HF model-card license tags before any paid build.** |
| DAW-specific MIDI arming differences | README per-DAW setup notes; the agent side is DAW-agnostic. |

## 12. Out of scope (explicit no-gos for this appetite)

- **Sub-20ms simultaneous jamming** (a separate, harder class of system; ADR 0115).
- **Real-time symbolic inference on commodity CPU** as a *requirement* (the heuristic default removes the need; AMT on CPU is best-effort, not a v1 guarantee).
- **True tempo / beat induction.** v1 reuses the call's literal onset spacing (a smart echo) with a confidence floor; real beat tracking is a later layer.
- **Timeout-based interruption of in-process model inference.** Real timeout needs process isolation, deferred to M5.
- **asyncio.** v1 is three plain threads + a queue (section 2.1).
- **Native Windows virtual-port support** (document the loopMIDI workaround instead).
- **MIDI-GPT in any build** (CC-BY-NC weights + NC data; never commercial).
- **Aria as a model** (deferred: Python 3.11 pin, `ariautils`, MLX-only real-time, unsettled NC-data caveat). Smart-engine order is now Claude (M5, recommended) then AMT (M6, optional local alternative).
- **Claude as the v1/PoC default** (the offline heuristic stays the default; Claude is an additional, recommended engine selected via `--responder claude`, not a blind default - its specific musical quality and real-loop latency are unverified, see `research-claude-engine.md`).
- **Claude Code + MCP, or the Agent SDK, as the Claude integration** (both add latency and are not built for a real-time loop; a direct Messages API call is the chosen path).
- **prefill-during-listen** and **adaptive-IOI handover** (documented stretch hooks, no-op by default; not v1 work).
- **Commercial deployment** (pending the HF weights-license spot-check).
- **A polished GUI / WebMIDI front end** (a possible later layer, not v1).

## 13. Pre-build checklist for the next session

1. Greenlight confirmed (scope.md says "not yet greenlit"; STATUS.md next action is the operator greenlight). Confirm before building.
2. Build M1 first; do not write logic until the port round-trip is verified in a DAW on the build OS - and validate M1 with a **distinct emitted test pattern** (C-major scale), not a raw echo, to avoid the feedback path.
3. Build `tests/fake_port.py` with an **injectable clock** early (during M2) so the poll-thread silence timers and the whole core are iterable without hardware or real waits.
4. Treat the **three-thread concurrency model** (callback / poll / state+scheduler) as explicit M2 work; it is the biggest hidden-work item, not free.
5. Keep `requirements-model.txt` separate; the default install is `python-rtmidi` + `mido` only.
6. Defer the HF license spot-check until a paid build is actually contemplated; AMT is the documented (believed-clean) target.

## Appendix - review follow-ups not applied in v1

These were the low-severity punch-list items; all are addressed or consciously deferred above:

- **L8 (M1 echo could mislead/feed back):** applied - M1 now emits a distinct C-major scale, not an echo (section 9).
- **L9 (asyncio is over-machinery):** applied - dropped asyncio for v1; three threads + a queue (section 2.1, section 12).
- **L10 (AMT license overstated vs research):** applied - softened to "believed Apache-2.0, confirm before any paid build" everywhere it appears (sections 1, 4.4, 11, 13).

No remaining low items are deferred without resolution.