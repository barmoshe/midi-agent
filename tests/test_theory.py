"""M3 - musical coherence: duration-weighted key, tempo, confidence-floor fallbacks, snap."""
from __future__ import annotations

from theory import build_context, estimate_key, estimate_tempo
from conftest import make_phrase


def test_estimate_key_c_major(c_major_phrase):
    root, mode, conf = estimate_key(c_major_phrase)
    assert root == 0 and mode == "major"
    assert conf > 0.5


def test_duration_weighting_changes_the_estimate():
    # one long held note dominates the duration-weighted histogram
    phrase = make_phrase([(60, 0.0, 4.0), (61, 4.0, 4.1), (66, 4.1, 4.2)])
    root, _mode, _conf = estimate_key(phrase)
    assert root == 0  # C dominates because it is held longest, not out-voted by count


def test_key_confidence_floor_falls_back_to_prev(c_major_context):
    # a single ambiguous note -> low confidence -> reuse the previous context's key
    weak = make_phrase([(61, 0.0, 0.1)])
    ctx = build_context(weak, prev=c_major_context, key_floor=0.99)
    assert ctx.root == c_major_context.root and ctx.mode == c_major_context.mode


def test_key_lock_overrides_estimate(c_major_phrase):
    ctx = build_context(c_major_phrase, key_lock="A:minor")
    assert ctx.root == 9 and ctx.mode == "minor" and ctx.key_confidence == 1.0


def test_tempo_regular_vs_irregular():
    regular = make_phrase([(60, 0.0, 0.2), (62, 0.5, 0.7), (64, 1.0, 1.2), (65, 1.5, 1.7)])
    ioi, conf = estimate_tempo(regular)
    assert abs(ioi - 0.5) < 1e-6 and conf > 0.8
    irregular = make_phrase([(60, 0.0, 0.1), (62, 0.1, 0.2), (64, 1.5, 1.6)])
    _ioi2, conf2 = estimate_tempo(irregular)
    assert conf2 < conf


def test_snap_keeps_in_key_pitch_and_moves_out_of_key(c_major_context):
    assert c_major_context.snap(64) == 64           # E is in C major
    snapped = c_major_context.snap(61)              # C# -> nearest in-key (C or D)
    assert snapped % 12 in c_major_context.scale


def test_degree_transpose_third(c_major_context):
    # C up a diatonic third in C major = E
    assert c_major_context.degree_transpose(60, 2) == 64
    # G up a third = B
    assert c_major_context.degree_transpose(67, 2) == 71
