"""Backing-track generator: diatonic chords stay in key, the cycle has the expected shape,
and every note_on has a matching note_off (no stuck notes). Pure logic, no ports."""
from __future__ import annotations

from backing import build_triad, cycle_events, make_context, timeline_for_cycle


def test_triads_are_in_key():
    ctx = make_context("C:major")
    tonic = 48  # C3
    for degree in (1, 2, 3, 4, 5, 6, 7):
        for pitch in build_triad(ctx, tonic, degree):
            assert pitch % 12 in ctx.scale, (degree, pitch)
            assert 0 <= pitch <= 127


def test_progression_i_v_vi_iv_roots():
    ctx = make_context("C:major")
    tonic = 48  # C3
    roots = [build_triad(ctx, tonic, d)[0] % 12 for d in (1, 5, 6, 4)]
    # I=C(0), V=G(7), vi=A(9), IV=F(5)
    assert roots == [0, 7, 9, 5]


def test_cycle_pads_structure_and_in_key():
    ctx = make_context("A:minor")
    events, cycle_beats = cycle_events(ctx, 45, [1, 4, 5, 1], style="pads", bars_per_chord=1)
    # 4 chords x (3 chord tones + 1 bass) = 16 events; 4 chords x 4 beats = 16 beats
    assert len(events) == 16
    assert cycle_beats == 16
    for _onset, _dur, pitch, _vel in events:
        assert pitch % 12 in ctx.scale
        assert 0 <= pitch <= 127


def test_every_note_on_has_a_matching_off():
    ctx = make_context("C:major")
    events, cycle_beats = cycle_events(ctx, 48, [1, 5, 6, 4], style="pulse")
    tl = timeline_for_cycle(events, cstart=0.0, spb=0.5)
    ons = [e for e in tl if e[1] == 1]
    offs = [e for e in tl if e[1] == 0]
    assert len(ons) == len(offs)
    assert sorted(p for _t, _k, p, _v in ons) == sorted(p for _t, _k, p, _v in offs)
    # timeline is time-sorted and every off is at or after its cycle start
    assert tl == sorted(tl, key=lambda e: (e[0], e[1]))


def test_arp_one_chord_tone_per_beat_plus_bass():
    ctx = make_context("C:major")
    events, _ = cycle_events(ctx, 48, [1], style="arp", bars_per_chord=1)
    # 4 beats -> 4 arp notes + 1 held bass = 5 events for a single chord
    assert len(events) == 5
