"""config.py - the single source of truth for tunables + CLI.

Defaults are the design.md section 5.0 literals (silence 700ms / hard 3000ms / poll 30ms
/ trigger CC67). Append-only: do not fork or re-declare these values elsewhere.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass
class Config:
    # --- handover (design 5.0) ---
    trigger_cc: int = 67          # una corda / soft pedal; never collides with sustain (CC64)
    silence_ms: int = 700         # settle: held-notes empty + this much silence -> handover
    hard_ms: int = 3000           # hard override: fire even with a note still held
    poll_ms: int = 30             # poll-thread tick that owns the silence timers

    # --- engine ---
    responder: str = "heuristic"  # heuristic | amt (M5) | claude (M6)
    heuristic_mode: str = "restate_vary"  # restate_vary | mirror | arpeggiate | harmonize
    response_bars: int = 2
    seed: int = 0                 # deterministic humanize/choice
    humanize: bool = True

    # --- AMT engine (M5, optional local model; deps in requirements-model.txt) ---
    amt_model: str = "stanford-crfm/music-medium-800k"
    amt_device: str = "auto"      # auto | cpu | cuda | mps
    amt_response_bars: int = 2    # response-length cap (keep ~2 on CPU for latency)
    amt_top_p: float = 0.98       # nucleus sampling
    amt_timeout: float = 10.0     # best-effort: abandon a slow generate, answer via heuristic
    amt_snap: bool = True         # scale-snap model output to the detected key

    # --- musical coherence (M3) ---
    key_lock: str | None = None   # e.g. "C:major" to pin the key; None = estimate
    key_floor: float = 0.5        # below this key-confidence, fall back to last-known/lock
    tempo_floor: float = 0.4      # below this tempo-confidence, fall back to last-known

    # --- ports / safety ---
    port_in_name: str = "Agent In"
    port_out_name: str = "Agent Out"
    echo_window_ms: int = 150     # incoming note matching our own output within this -> echo, not reclaim


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="midi-agent", description="Live MIDI Agent - turn-taking call-and-response.")
    d = Config()
    p.add_argument("--trigger-cc", type=int, default=d.trigger_cc, help="handover pedal CC (default 67 = una corda)")
    p.add_argument("--silence-ms", type=int, default=d.silence_ms, help="silence settle threshold")
    p.add_argument("--hard-ms", type=int, default=d.hard_ms, help="hard handover override")
    p.add_argument("--poll-ms", type=int, default=d.poll_ms, help="poll-thread tick")
    p.add_argument("--responder", default=d.responder, choices=["heuristic", "amt", "claude"], help="generation engine")
    p.add_argument("--heuristic-mode", default=d.heuristic_mode,
                   choices=["restate_vary", "mirror", "arpeggiate", "harmonize"], help="heuristic transform")
    p.add_argument("--response-bars", type=int, default=d.response_bars)
    p.add_argument("--seed", type=int, default=d.seed)
    p.add_argument("--no-humanize", dest="humanize", action="store_false", help="disable timing/velocity humanize")
    p.add_argument("--amt-model", default=d.amt_model, help="HuggingFace AMT checkpoint (M5)")
    p.add_argument("--amt-device", default=d.amt_device, choices=["auto", "cpu", "cuda", "mps"], help="AMT inference device")
    p.add_argument("--amt-response-bars", type=int, default=d.amt_response_bars, help="AMT response length cap in bars")
    p.add_argument("--amt-top-p", type=float, default=d.amt_top_p, help="AMT nucleus sampling top_p")
    p.add_argument("--amt-timeout", type=float, default=d.amt_timeout,
                   help="best-effort AMT generate timeout (s) before heuristic fallback")
    p.add_argument("--amt-no-snap", dest="amt_snap", action="store_false",
                   help="do not scale-snap AMT output to the detected key")
    p.add_argument("--key", dest="key_lock", default=d.key_lock, help='pin the key, e.g. "C:major" or "A:minor"')
    p.add_argument("--port-in-name", default=d.port_in_name)
    p.add_argument("--port-out-name", default=d.port_out_name)
    p.add_argument("--echo-window-ms", type=int, default=d.echo_window_ms)
    return p


def parse_args(argv=None) -> Config:
    a = build_parser().parse_args(argv)
    return Config(
        trigger_cc=a.trigger_cc, silence_ms=a.silence_ms, hard_ms=a.hard_ms, poll_ms=a.poll_ms,
        responder=a.responder, heuristic_mode=a.heuristic_mode, response_bars=a.response_bars,
        seed=a.seed, humanize=a.humanize, key_lock=a.key_lock,
        amt_model=a.amt_model, amt_device=a.amt_device, amt_response_bars=a.amt_response_bars,
        amt_top_p=a.amt_top_p, amt_timeout=a.amt_timeout, amt_snap=a.amt_snap,
        port_in_name=a.port_in_name, port_out_name=a.port_out_name, echo_window_ms=a.echo_window_ms,
    )
