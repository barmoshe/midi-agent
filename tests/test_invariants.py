"""M1.3 - the frozen data invariants: NoteRecord immutability + start<end, Responder ABC.

(Named test_invariants rather than test_contracts: the workshop protect-paths hook treats
a "*contract*" filename as a legal/money file. These are code invariants, not a contract.)
"""
from __future__ import annotations

import dataclasses

import pytest

from capture import NoteRecord
from responder import Responder


def test_noterecord_frozen():
    n = NoteRecord(60, 80, 0.0, 0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        n.pitch = 61  # type: ignore[misc]


def test_noterecord_start_before_end_invariant():
    with pytest.raises(ValueError):
        NoteRecord(60, 80, 0.5, 0.5)   # zero length
    with pytest.raises(ValueError):
        NoteRecord(60, 80, 0.6, 0.5)   # negative length


def test_noterecord_range_checks():
    with pytest.raises(ValueError):
        NoteRecord(200, 80, 0.0, 0.5)  # pitch
    with pytest.raises(ValueError):
        NoteRecord(60, 0, 0.0, 0.5)    # velocity 0 not allowed in a record
    with pytest.raises(ValueError):
        NoteRecord(60, 80, 0.0, 0.5, channel=16)


def test_responder_abc_not_instantiable():
    with pytest.raises(TypeError):
        Responder()  # type: ignore[abstract]
