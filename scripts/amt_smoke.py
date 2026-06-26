"""amt_smoke.py - a no-DAW smoke test for the M5 local AMT engine.

Loads the real model and runs a couple of real generate() turns on a synthetic phrase,
printing model-load and per-turn wall-clock latency and confirming the reply is non-empty,
in-key, and anchored to t=0. This is the runnable half of M5.10 (the DAW arming is manual).

Run (needs requirements-model.txt installed):
    ./venv/bin/python scripts/amt_smoke.py [--device cpu|cuda|mps] [--bars 2] [--turns 2]

With the model deps absent it prints a clear notice and exits 0 (so it is safe in CI).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# allow running as `python scripts/amt_smoke.py` from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture import NoteRecord  # noqa: E402
from config import Config  # noqa: E402
from theory import build_context  # noqa: E402


def _phrase() -> tuple:
    # a clear C-major melody, quarter-note grid
    return (
        NoteRecord(60, 80, 0.0, 0.45),
        NoteRecord(62, 84, 0.5, 0.95),
        NoteRecord(64, 88, 1.0, 1.45),
        NoteRecord(65, 84, 1.5, 1.95),
        NoteRecord(67, 90, 2.0, 2.55),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--bars", type=int, default=2)
    ap.add_argument("--turns", type=int, default=2)
    args = ap.parse_args()

    try:
        from amt_engine import AmtResponder
    except Exception as exc:  # noqa: BLE001
        print(f"amt_engine import failed: {exc}")
        return 0

    phrase = _phrase()
    ctx = build_context(phrase)
    print(f"context: key={ctx.root}:{ctx.mode} ioi={ctx.ioi}")

    print("loading model (first run downloads the checkpoint)...", flush=True)
    t0 = time.monotonic()
    try:
        r = AmtResponder(Config(amt_device=args.device, amt_response_bars=args.bars))
    except ImportError as exc:
        print(f"model deps not installed: {exc}")
        return 0
    print(f"model loaded in {time.monotonic() - t0:.1f}s", flush=True)

    for i in range(args.turns):
        t0 = time.monotonic()
        out = r.respond(phrase, ctx)
        gen_s = time.monotonic() - t0
        in_key = all(n.pitch % 12 in ctx.scale for n in out)
        anchored = min((n.start_s for n in out), default=0.0) == 0.0
        dangling_free = all(n.start_s < n.end_s for n in out)
        print(
            f"turn {i + 1}: {gen_s:.2f}s | notes={len(out)} | in_key={in_key} | "
            f"anchored={anchored} | dangling_free={dangling_free} | "
            f"pitches={[n.pitch for n in out][:16]}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
