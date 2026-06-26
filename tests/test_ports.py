"""M1.4-M1.6 - ports logic against fake doubles: two distinct ports, send routing,
callback dispatch, same-name warning, the distinct C-major emitter, MIDI parsing."""
from __future__ import annotations

import logging

from config import Config
from ports import Ports, parse_midi, warn_on_collision
from fake_port import FakeMidiIn, FakeMidiOut


def _open(existing_in=None, existing_out=None):
    fin = FakeMidiIn(existing_in)
    fout = FakeMidiOut(existing_out)
    ports = Ports.open(Config(), in_factory=lambda: fin, out_factory=lambda: fout)
    return ports, fin, fout


def test_opens_two_distinct_named_ports():
    _ports, fin, fout = _open()
    assert fin.opened == "Agent In"
    assert fout.opened == "Agent Out"
    assert fin.opened != fout.opened


def test_send_routes_to_out_port():
    ports, _fin, fout = _open()
    ports.send([0x90, 60, 100])
    assert fout.messages == [[0x90, 60, 100]]


def test_callback_fires_on_incoming():
    ports, fin, _fout = _open()
    seen = []
    ports.set_callback(lambda event, data=None: seen.append(parse_midi(list(event[0]))))
    fin.inject([0x90, 64, 90])
    assert seen == [{"type": "note_on", "channel": 0, "pitch": 64, "velocity": 90}]


def test_same_name_collision_warns(caplog):
    with caplog.at_level(logging.WARNING):
        collided = warn_on_collision(["Agent In"], "Agent In")
    assert collided is True
    assert any("already exists" in r.message for r in caplog.records)
    assert warn_on_collision([], "Agent In") is False


def test_emit_test_scale_is_distinct_c_major_not_echo():
    ports, _fin, fout = _open()
    ports.emit_test_scale()  # no sleep in tests
    ons = [m for m in fout.messages if m[0] == 0x90]
    pitches = [m[1] for m in ons]
    assert pitches == [60, 62, 64, 65, 67, 69, 71, 72]
    # every on has a matching off
    offs = [m for m in fout.messages if m[0] == 0x80]
    assert [m[1] for m in offs] == pitches


def test_parse_midi_note_on_off_cc():
    assert parse_midi([0x90, 60, 100]) == {"type": "note_on", "channel": 0, "pitch": 60, "velocity": 100}
    # note_on velocity 0 == note_off
    assert parse_midi([0x90, 60, 0])["type"] == "note_off"
    assert parse_midi([0x82, 60, 40]) == {"type": "note_off", "channel": 2, "pitch": 60, "velocity": 40}
    assert parse_midi([0xB0, 67, 127]) == {"type": "control_change", "channel": 0, "control": 67, "value": 127}
    assert parse_midi([]) is None
