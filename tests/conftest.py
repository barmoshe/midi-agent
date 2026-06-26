"""Shared fixtures: a fake clock, canonical phrases, and a music context for key/tempo tests."""
from __future__ import annotations

import pytest

from capture import NoteRecord
from theory import build_context
from fake_port import FakeClock


@pytest.fixture
def clock():
    return FakeClock()


def make_phrase(spec):
    """spec: list of (pitch, start_s, end_s[, velocity]). Returns a tuple of NoteRecord."""
    out = []
    for item in spec:
        pitch, start, end = item[0], item[1], item[2]
        vel = item[3] if len(item) > 3 else 80
        out.append(NoteRecord(pitch, vel, start, end))
    return tuple(out)


@pytest.fixture
def c_major_phrase():
    # C D E G C - a clear C-major melody, quarter-note grid
    return make_phrase([
        (60, 0.0, 0.45),
        (62, 0.5, 0.95),
        (64, 1.0, 1.45),
        (67, 1.5, 1.95),
        (72, 2.0, 2.45),
    ])


@pytest.fixture
def c_major_context(c_major_phrase):
    return build_context(c_major_phrase)
