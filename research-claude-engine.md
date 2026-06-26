# Research - Claude as the live generative engine (third pass)

A focused deep-research pass (fan-out web search + adversarial 3-vote verification,
~108 agents, 2026-06-26) on the operator's pivot: use Claude (the Anthropic LLM) as
the generative engine for the Live MIDI Agent, instead of a local model (AMT) or
rules. Folded into `design.md` section 4.5. This is the durable record.

**Verdict: GO - as an ADDITIONAL, recommended engine, not a blind default.** The
offline heuristic stays the always-works default; Claude becomes the flagship "smart"
engine. Recommended wiring: a direct Anthropic Messages API call from the Python
agent, Haiku tier, streaming + tool-use JSON notes + prompt caching.

## Subscription path (no API key) - personal use [VERIFIED, fourth pass]

The operator has a Claude Pro/Max subscription, prefers not to use a metered API key,
and is building this as a **personal, single-user, non-distributed** tool. A dedicated
fresh deep-research pass (4th pass, ~111 agents, 3-vote verification) settled this.

**Verdict: PERMITTED for personal use, but NO-GO as the live generative engine.**
Recommended no-key engine is **local AMT** (offline, free), not the subscription.

- **Terms = NOT the blocker.** Anthropic's legal-and-compliance page blesses
  OAuth/subscription login for "ordinary, individual use of Claude Code and the Agent
  SDK." The only prohibition is multi-user / third-party routing ("offer Claude.ai
  login" or "route requests through Pro/Max credentials on behalf of their users").
  A single user automating their own subscription is allowed. Switch to an API key only
  if it is ever distributed/monetized.
- **Latency = the real problem.** Good-case headless `claude -p` is ~3-5s/turn (already
  marginal for music). A documented Jan-2026 regression (GitHub #20527, #17330) spiked
  *every* call to a near-constant ~60-63s regardless of prompt (a transient,
  version-specific timeout bug, since fixed, but it shows the timing cannot be trusted).
  `--bare` (fastest startup, skips CLAUDE.md/MCP/hooks) is **incompatible with
  subscription auth** - it requires an API key (GitHub #38022) - so the fast path is
  closed.
- **Cost premise undercut.** A mid-2026 metering change reportedly moved programmatic
  surfaces (`claude -p`, Agent SDK) onto a *separate, API-priced* credit pool, not the
  flat subscription - defeating the no-metered-key goal. CONTESTED/time-sensitive: a
  June-2026 source says programmatic use still draws on the subscription "exactly as
  before." Verify current Anthropic billing before relying on either.
- **Mechanics (if used for non-real-time).** Warm session via the Agent SDK
  streaming-input mode (`ClaudeSDKClient`, persistent process, exposes `ttft_ms`), or
  `claude -p --output-format stream-json --verbose --include-partial-messages` over
  OAuth (NOT `--bare`). The `--input-format stream-json` stdin protocol is thinly
  documented (GitHub #24594); prefer the SDK's streaming-input mode over hand-rolled
  NDJSON. Reserve for non-real-time work (seed phrases between sessions), `--responder
  claude-code`, always `FallbackResponder`-wrapped.

### Recommended no-key engine: local AMT

The fresh pass's strong recommendation. Anticipatory Music Transformer
(`stanford-crfm/music-medium-800k`, Apache-2.0) is the best no-key fit:

- **Free, offline, no key, no metering** - exactly the operator's underlying goal.
- **Symbolic-MIDI-native:** `midi_to_events` / `generate(top_p=.98)` / `events_to_midi`
  (returns a `mido` MidiFile) drops straight into the mido/python-rtmidi pipeline, no
  notation-parsing step.
- **Melody-conditioned accompaniment** = the responder behavior (call -> response).
- **Faster-than-real-time on commodity hardware:** the MLC port (MIDInfinite) hits
  ~51 notes/sec, faster than real-time for 72.9% of generations on an M3 MacBook.
- *Caveat:* AMT accompaniment is co-temporal (plays WITH the melody) rather than
  strictly after-the-phrase; the Responder plugin adapts it to sequential turn-taking.
  "Notes/sec" is streaming throughput, not round-trip turn latency (measure at build).

**ChatMusician** (local 7B, ABC notation, runs via standard HF tooling, quantized
variants exist) is a viable *creative* alternative but heavier and needs an ABC->MIDI
parse step (abc2midi/music21) that AMT avoids. The **rule-based heuristic** stays the
zero-dependency default/fallback.

### Engine ranking for a no-API-key personal build

1. **Rule-based heuristic** - default, instant, offline, zero deps.
2. **Local AMT** - recommended smart engine; free, offline, MIDI-native, fast.
3. **ChatMusician (local 7B)** - optional creative alternative; heavier + ABC parse.
4. **Claude API (Haiku)** - best quality, ~1s, but needs a (cheap) metered key.
5. **Subscription Claude Code headless** - permitted but NOT for the live loop; volatile
   latency + possible separate API-metering. Non-real-time use only.

## Why GO

- **The full path is proven in shipping prior art.** `sandst1/llmjam` runs a
  call-and-response loop (human phrase -> pitch detection -> MIDI -> LLM with a
  musician prompt -> notes back -> virtual port -> loop) and explicitly supports
  Anthropic Claude (3.7 Sonnet via OpenRouter) as an interchangeable backend. That is
  exactly the `Responder`-plugin shape this project already has. `sandst1/mcp-server-midi`
  uses the SAME mido + python-rtmidi virtual-port stack as our design. AbletonMCP,
  JAMMIN-GPT, and tubone24/midi-mcp-server corroborate working LLM-to-MIDI-to-DAW.
- **Latency works for turn-taking (not for tight real-time).** Claude Haiku is
  Anthropic's fastest model (TTFT ~sub-500ms to ~0.84s; Sonnet ~500-800ms; Opus
  ~1-2s). Streaming lets the first notes play while later ones generate. That lands
  inside the phrase-level turn-taking budget (hundreds of ms to ~2s). Sample-accurate
  simultaneous jamming is still out (already out of scope).
- **Cost is a non-issue.** Haiku ~$1/$5 per MTok in/out (approx, mid-2026). A turn is
  a few hundred input + ~100-500 output tokens = a small fraction of a cent. A long
  session costs cents. Prompt caching ($0.10/MTok read) cuts the repeated system
  prompt further. Cost actively favors Haiku as the live-loop default model.
- **It simplifies the build.** No GPU, no model download, no weights-license question,
  no process-isolation-for-timeout machinery. Trade: an API key + network dependency,
  which is exactly why the offline heuristic stays the default.

## Why NOT a blind default (the honest caveats)

- **Claude's specific composition *musicality* is UNVERIFIED.** All direct
  composition-quality evidence is for ChatMusician (fine-tuned 7B), GPT-4, or
  GPT-4-turbo. The llmjam Claude support proves the *wiring*, not the song quality. No
  source measured Claude Opus/Sonnet/Haiku output musicality.
- **A fine-tuned local 7B model BEAT GPT-4 at composition.** ChatMusician surpassed
  GPT-4 on ABC-format correctness (99.6% vs 94.6%) and was preferred 76% of the time
  in a human listening study. So a frontier API LLM is not the obvious quality winner
  over the local-symbolic-model route - it is the easiest and most flexible, not
  provably the best musician.
- **No measured end-to-end music-loop latency exists.** The latency case rests on
  general Haiku TTFT benchmarks plus streaming, not a measured phrase-to-first-note
  loop. llmjam markets real-time but publishes no numbers.
- **Music *reasoning* is weak in general LLMs.** On MusicTheoryBench, even GPT-4
  barely exceeded the random baseline (weak/old proxy, but a caution).

## Best MIDI-to-text representation

- **ABC notation** is the most LLM-friendly and what the quality studies validated
  (ChatMusician, JAMMIN-GPT -> abc2midi). BUT it biases output toward Irish/folk style
  regardless of prompt (observed in both). 
- **JSON note-events** (pitch 0-127, velocity, start_s, end_s, channel) - the working
  MCP servers all use structured note formats; this is the bias-free, incrementally
  parseable choice and matches our `NoteRecord`. 
- **Decision for this project: JSON note-events via tool-use / structured output**,
  with an explicit style hint in the prompt to compensate for not using ABC. Reliable
  formatting beats ABC's stylistic bias for a general-purpose duet. Reconsider ABC only
  if musical quality testing shows JSON output is markedly weaker.

## Integration path (chosen: direct Messages API)

| Path | Verdict |
|---|---|
| **Direct Anthropic Messages API call** (Haiku + streaming + tool-use JSON + prompt caching) | **CHOSEN.** Fewest moving parts, lowest latency, plugs straight into the existing `Responder`. Validated by llmjam's direct-call pattern. |
| Claude Code (CLI) + MCP MIDI server | Proven to work (AbletonMCP, sandst1/mcp-server-midi) but documented as NOT built for real-time; adds CLI + tool-call mediation latency. Better for offline arrangement/songwriting, not the in-the-loop musician. |
| Claude Agent SDK (long-running agent) | Heavier than needed; the engine only takes a phrase and returns notes. No benefit over a direct call for this loop. |

Rated medium-confidence on the ranking: no source directly benchmarks direct-API vs
MCP latency for a music loop; the ordering is inferred from architecture plus the
real-time caveats on the MCP path.

## Failure modes + mitigations (LLM music specifics)

| Failure mode | Mitigation |
|---|---|
| Invalid / malformed notes | tool-use schema validation; drop-and-continue on a bad event |
| Key drift | pass the detected key in the prompt; scale-snap the output (`theory.py`) |
| Repetition / rambling | cap `max_tokens` (~2 bars); prompt for a concise answer |
| Style bias (esp. ABC) | use JSON note format; explicit style hint in the prompt |
| Network / timeout / missing API key | `FallbackResponder` drops to the offline heuristic |

## How this changes the design

- New engine `ClaudeResponder` documented in `design.md` section 4.5, behind the
  existing `Responder` interface, wrapped by `FallbackResponder` like any engine.
- Build plan: **M5 = Claude engine (recommended next step after the heuristic PoC)**;
  AMT demoted to **M6 (optional local alternative)**.
- Stack: `anthropic` SDK in a separate `requirements-claude.txt`, not installed by
  default. The PoC (M1-M4) is unchanged and still runs offline with zero API
  dependency.
- The heuristic remains the default engine; Claude is selected via `--responder claude`.

## Open questions (carry into the build)

1. Claude Haiku's actual zero-shot composition quality (musicality, rhythm, key
   stability) vs the heuristic and vs a local model - measure on real phrases.
2. Real measured round-trip latency (phrase -> Haiku stream -> first note out) for a
   few-bars generation. Does it land in the hundreds-of-ms-to-2s window in practice?
3. JSON note-events vs ABC for Claude specifically, and whether streamed JSON parses
   incrementally fast enough to start playback before the response completes.
4. Whether prompt caching + a stable musician system prompt meaningfully cut per-turn
   TTFT/cost in a sustained jam, and how to carry musical context (key, tempo, prior
   phrases) across turns without bloating input tokens.

## Key sources

- llmjam (Claude call-and-response jam) - https://github.com/sandst1/llmjam
- mcp-server-midi (virtual port, same stack) - https://github.com/sandst1/mcp-server-midi
- AbletonMCP - https://github.com/ahujasid/ableton-mcp
- tubone24/midi-mcp-server - https://github.com/tubone24/midi-mcp-server
- JAMMIN-GPT (ABC -> abc2midi) - https://arxiv.org/html/2312.03479v1
- ChatMusician (ABC, beats GPT-4 at composition) - https://arxiv.org/abs/2402.16153
- MuseCoco (text-to-attribute-to-music) - https://arxiv.org/pdf/2306.00110
- Claude latency guidance (Haiku fastest) - https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency
- Claude pricing - https://platform.claude.com/docs/en/about-claude/pricing

### Verification notes

3-vote adversarial verification, 0 claims refuted this pass. Soft spots: Claude's own
composition quality and real-loop latency are inferred, not measured (no system
publishes either for Claude); pricing and "Haiku is fastest" are time-sensitive vendor
figures current as of mid-2026; some corroborating blogs returned HTTP 403. The two
build-blocking unknowns (musical quality, real latency) are cheap to settle at build
time by trying it - which is itself an argument for building the Claude engine and
listening.
