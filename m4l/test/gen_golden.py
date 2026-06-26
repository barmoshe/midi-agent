"""gen_golden.py - dump golden vectors from the REAL Python harmony functions.

These vectors are the oracle the JS port (engine.js) is checked against in Node (run.js), so
parity is proved against actual Python behavior, not hand-copied expectations. Run with the
project venv:  ./venv/bin/python m4l/test/gen_golden.py   (writes m4l/test/golden.json)

Covers every pure function the Max device reuses: estimate_key, snap, degree_transpose,
build_triad, chord_name, chord_bar_events, pitch_histogram, score_chord, best_degree,
timeline_for_cycle. Velocity humanization is made deterministic with a zero-rng so the JS port
(passing its zero-rng) matches pitch+timing+velocity exactly.
"""
from __future__ import annotations

import json
import os
import sys

# import the real PoC modules from the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backing import build_triad, make_context, timeline_for_cycle  # noqa: E402
from capture import NoteRecord  # noqa: E402
from follow import (best_degree, chord_bar_events, chord_name,  # noqa: E402
                    pitch_histogram, score_chord)
from theory import estimate_key  # noqa: E402

KEYS = ["C:major", "A:minor", "G:major", "F:major", "D:minor", "E:major", "F#:major", "Bb:major"]


class ZeroRng:
    """Deterministic rng so chord_bar_events velocity is reproducible across Python and JS."""

    def randint(self, a, b):
        return 0


def tonic_of(ctx):
    return 48 + ctx.root  # follow.py default tonic octave 3 -> 48 + root


def main():
    cases = []

    def add(fn, inp, out):
        cases.append({"fn": fn, "in": inp, "out": out})

    # estimate_key: the canonical phrase + the duration-weighting case + a minor lean
    phrases = {
        "c_major": [(60, 0.0, 0.45), (62, 0.5, 0.95), (64, 1.0, 1.45), (67, 1.5, 1.95), (72, 2.0, 2.45)],
        "dur_weight": [(60, 0.0, 4.0), (61, 4.0, 4.1), (66, 4.1, 4.2)],
        "a_minor": [(57, 0.0, 0.5), (60, 0.5, 1.0), (64, 1.0, 1.5), (69, 1.5, 2.5)],
        "empty": [],
    }
    for spec in phrases.values():
        notes = [NoteRecord(p, 80, s, e) for (p, s, e) in spec] if spec else []
        root, mode, conf = estimate_key(notes)
        add("estimateKey",
            {"notes": [{"pitch": p, "start": s, "end": e} for (p, s, e) in spec]},
            [root, mode, conf])

    for key in KEYS:
        ctx = make_context(key)
        tonic = tonic_of(ctx)

        for degree in range(1, 8):
            add("buildTriad", {"ctxKey": key, "tonic": tonic, "degree": degree},
                build_triad(ctx, tonic, degree))
            for seventh in (False, True):
                add("chordName", {"ctxKey": key, "tonic": tonic, "degree": degree, "seventh": seventh},
                    chord_name(ctx, tonic, degree, seventh=seventh))

        for degree in (1, 4, 5):
            for style in ("pulse", "pads"):
                for seventh in (False, True):
                    ev = chord_bar_events(ctx, tonic, degree, style=style, vel=74,
                                          rng=ZeroRng(), seventh=seventh)
                    add("chordBarEvents",
                        {"ctxKey": key, "tonic": tonic, "degree": degree, "style": style,
                         "vel": 74, "beats": 4, "seventh": seventh},
                        [list(e) for e in ev])

        for pitch in range(40, 85):
            add("snap", {"ctxKey": key, "pitch": pitch}, ctx.snap(pitch))
            for steps in (-2, -1, 0, 1, 2, 3, 4, 6):
                add("degreeTranspose", {"ctxKey": key, "pitch": pitch, "steps": steps},
                    ctx.degree_transpose(pitch, steps))

        # best_degree: a histogram emphasizing each diatonic triad should pick that degree
        for emph in range(1, 8):
            triad = build_triad(ctx, tonic, emph)
            hist = {}
            for p in triad:
                hist[p % 12] = hist.get(p % 12, 0.0) + 1.0
            for current in (1, emph):
                add("bestDegree", {"ctxKey": key, "tonic": tonic, "hist": hist, "current": current},
                    best_degree(ctx, tonic, hist, current))

    # follow.py direct cases (mirror tests/test_follow.py)
    ctxc = make_context("C:major")
    tonicc = tonic_of(ctxc)

    ph_cases = [
        ([[60, 99.0], [64, 99.5], [72, 80.0]], 100.0, 2.5, 1.2),
        ([[60, 10.0], [62, 10.2], [64, 10.4], [67, 10.6]], 11.0, 2.5, 1.2),
        ([], 5.0, 2.5, 1.2),
    ]
    for notes, now, win, hl in ph_cases:
        h = pitch_histogram(notes, now, window_s=win, halflife=hl)
        add("pitchHistogram", {"notes": notes, "now": now, "windowS": win, "halflife": hl},
            {str(k): v for k, v in h.items()})

    sc_cases = [
        ({0: 1.0, 4: 1.0, 7: 1.0}, [0, 4, 7], 0, 0.5),
        ({1: 1.0, 6: 1.0}, [0, 4, 7], 0, 0.5),
        ({5: 1.0, 9: 0.5, 0: 0.25}, [5, 9, 0], 5, 0.5),
    ]
    for hist, pcs, root_pc, pen in sc_cases:
        add("scoreChord", {"hist": {str(k): v for k, v in hist.items()}, "chordPcs": pcs,
                           "rootPc": root_pc, "outPenalty": pen},
            score_chord(hist, frozenset(pcs), root_pc, out_penalty=pen))

    # explicit best_degree follow cases
    for hist, current in [({0: 1.0, 4: 1.0, 7: 1.0}, 1), ({5: 1.0, 9: 1.0, 0: 1.0}, 1),
                          ({9: 1.0, 0: 1.0, 4: 1.0}, 1), ({7: 1.0, 11: 1.0, 2: 1.0}, 1),
                          ({0: 0.1}, 4)]:
        add("bestDegree", {"ctxKey": "C:major", "tonic": tonicc, "hist": {str(k): v for k, v in hist.items()},
                           "current": current},
            best_degree(ctxc, tonicc, hist, current))

    # timeline_for_cycle on a real chord bar
    ev = chord_bar_events(ctxc, tonicc, 1, style="pulse", vel=74, rng=ZeroRng())
    for cstart, spb in [(0.0, 0.5), (10.0, 0.6)]:
        tl = timeline_for_cycle([tuple(e) for e in ev], cstart, spb)
        add("timelineForCycle", {"events": [list(e) for e in ev], "cstart": cstart, "spb": spb},
            [list(x) for x in tl])

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.json")
    with open(out_path, "w") as f:
        json.dump(cases, f, indent=0)
    print(f"wrote {len(cases)} golden vectors -> {out_path}")


if __name__ == "__main__":
    main()
