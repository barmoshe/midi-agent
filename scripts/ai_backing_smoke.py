"""ai_backing_smoke.py - a no-DAW smoke for the dynamic AI backing generator.

Loads the model and runs a few real continue_from() chunks off a chord seed, printing per
-chunk latency and note counts, to prove the streaming generation works (the real-time MIDI
threads are exercised by running ai_backing.py against a DAW). Deps-guarded -> safe in CI.

Run: ./venv/bin/python scripts/ai_backing_smoke.py [--chunks 4] [--chunk-secs 6]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_backing import _rebase, seed_notes  # noqa: E402
from backing import make_context  # noqa: E402
from capture import NoteRecord  # noqa: E402
from config import Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", type=int, default=4)
    ap.add_argument("--chunk-secs", type=float, default=6.0)
    args = ap.parse_args()

    try:
        from amt_engine import AmtStream
    except Exception as exc:  # noqa: BLE001
        print(f"amt_engine import failed: {exc}")
        return 0

    ctx = make_context("C:major")
    tonic = 48
    print("loading model...", flush=True)
    t0 = time.monotonic()
    try:
        stream = AmtStream(Config(amt_device="cpu", amt_top_p=0.98))
    except ImportError as exc:
        print(f"model deps not installed: {exc}")
        return 0
    print(f"loaded in {time.monotonic() - t0:.1f}s", flush=True)

    seed, _ = seed_notes(ctx, tonic, [1, 5, 6, 4], style="pulse", bpm=100, cycles=2)
    timeline = list(seed)
    cursor = max(n.end_s for n in timeline)

    for i in range(args.chunks):
        window = _rebase([n for n in timeline if n.start_s >= cursor - 8.0])
        t0 = time.monotonic()
        new = stream.continue_from(window, args.chunk_secs)
        dt = time.monotonic() - t0
        in_key = sum(1 for n in new if n.pitch % 12 in ctx.scale)
        lo = min((n.pitch for n in new), default=0)
        hi = max((n.pitch for n in new), default=0)
        print(f"chunk {i + 1}: {dt:.1f}s | notes={len(new)} | in_key(raw)={in_key}/{len(new)} | "
              f"pitch_range={lo}-{hi} | onsets={[round(n.start_s, 2) for n in new[:6]]}", flush=True)
        for n in new:
            timeline.append(NoteRecord(n.pitch, n.velocity, cursor + n.start_s, cursor + n.end_s, 0))
        cursor += args.chunk_secs
    print("ok - streaming generation works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
