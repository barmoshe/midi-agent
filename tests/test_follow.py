"""The follow-along accompanist's harmony logic: recency-weighted histogram, chord scoring,
and the chord choice that tracks the soloist (with hysteresis). Pure - no ports."""
from __future__ import annotations

import random

from backing import make_context
from follow import best_degree, chord_bar_events, chord_name, pitch_histogram, score_chord


def test_chord_name_reflects_quality():
    ctx = make_context("C:major")
    assert chord_name(ctx, 48, 1) == "C"     # I major
    assert chord_name(ctx, 48, 6) == "Am"    # vi minor
    assert chord_name(ctx, 48, 5) == "G"     # V major
    assert chord_name(ctx, 48, 7) == "Bdim"  # vii diminished
    assert chord_name(ctx, 48, 2, seventh=True) == "Dm7"


def test_pitch_histogram_recent_weighted_and_drops_old():
    now = 100.0
    h = pitch_histogram([(60, 99.0), (64, 99.5), (72, 80.0)], now, window_s=2.5, halflife=1.2)
    assert set(h) == {0, 4}          # 72 (pc 0) at t=80 is >2.5s old -> dropped
    assert h[4] > h[0]               # 64 is more recent than 60, so weighted higher


def test_score_chord_rewards_fit_penalizes_outside():
    fit = score_chord({0: 1.0, 4: 1.0, 7: 1.0}, frozenset({0, 4, 7}), root_pc=0)
    off = score_chord({1: 1.0, 6: 1.0}, frozenset({0, 4, 7}), root_pc=0)
    assert fit > 0 > off


def test_best_degree_follows_the_emphasized_chord():
    ctx = make_context("C:major")
    tonic = 48
    assert best_degree(ctx, tonic, {0: 1.0, 4: 1.0, 7: 1.0}, current_degree=1) == 1   # C E G -> I
    assert best_degree(ctx, tonic, {5: 1.0, 9: 1.0, 0: 1.0}, current_degree=1) == 4   # F A C -> IV
    assert best_degree(ctx, tonic, {9: 1.0, 0: 1.0, 4: 1.0}, current_degree=1) == 6   # A C E -> vi
    assert best_degree(ctx, tonic, {7: 1.0, 11: 1.0, 2: 1.0}, current_degree=1) == 5  # G B D -> V


def test_hysteresis_holds_current_chord_when_ambiguous():
    ctx = make_context("C:major")
    # a weak/ambiguous histogram should not yank the chord away from the current one
    assert best_degree(ctx, 48, {0: 0.1}, current_degree=4) == 4


def test_chord_bar_events_in_key():
    ctx = make_context("C:major")
    ev = chord_bar_events(ctx, 48, 1, style="pulse", vel=74, rng=random.Random(0))
    assert ev
    for _onset, _dur, pitch, vel in ev:
        assert pitch % 12 in ctx.scale
        assert 1 <= vel <= 127
