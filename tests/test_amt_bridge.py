"""M5.3 - the model-free NoteRecord <-> temp .mid bridge: round-trip fidelity, t=0
re-basing, and the dangling-free invariant. No model, no torch."""
from __future__ import annotations

import os

from amt_engine import phrase_to_tempmid, rebase_to_zero, tempmid_to_notes
from capture import NoteRecord


def _phrase():
    return (
        NoteRecord(60, 80, 0.0, 0.45),
        NoteRecord(62, 90, 0.5, 0.95),
        NoteRecord(64, 100, 1.0, 1.45, 1),  # channel 1
        NoteRecord(67, 70, 1.5, 1.95),
    )


def _roundtrip(phrase, rebase=True):
    path = phrase_to_tempmid(phrase)
    try:
        return tempmid_to_notes(path, rebase=rebase)
    finally:
        os.unlink(path)


def test_roundtrip_preserves_pitch_velocity_channel():
    phrase = _phrase()
    out = _roundtrip(phrase)
    assert [n.pitch for n in out] == [n.pitch for n in phrase]
    assert [n.velocity for n in out] == [n.velocity for n in phrase]
    assert [n.channel for n in out] == [n.channel for n in phrase]


def test_roundtrip_preserves_relative_timing():
    phrase = _phrase()
    out = _roundtrip(phrase)
    for a, b in zip(phrase, out):
        assert abs(a.start_s - b.start_s) < 0.01
        assert abs((a.end_s - a.start_s) - (b.end_s - b.start_s)) < 0.01


def test_output_rebased_to_zero_and_dangling_free():
    # a phrase that starts at t=2.0 must rebase so the earliest onset is 0
    phrase = (NoteRecord(60, 80, 2.0, 2.4), NoteRecord(64, 80, 2.5, 2.9))
    out = _roundtrip(phrase, rebase=True)
    assert min(n.start_s for n in out) == 0.0
    assert all(n.start_s < n.end_s for n in out)


def test_no_rebase_keeps_absolute_times():
    phrase = (NoteRecord(60, 80, 2.0, 2.4),)
    out = _roundtrip(phrase, rebase=False)
    assert out[0].start_s > 1.5  # absolute model time preserved, not re-based


def test_rebase_to_zero_empty():
    assert rebase_to_zero([]) == []
