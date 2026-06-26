"""ports.py - the ONLY module that touches RtMidi.

Opens two SEPARATE virtual ports (the Linux quirk: RtMidi cannot read its own virtual
output, so input and output must be distinct ports; the DAW sees both fine). Registers a
non-blocking input callback, exposes a raw send primitive, warns on a same-name-port
collision, and owns clean teardown. Factories are injectable so the logic is testable
against fake_port without real hardware. See design.md section 8, 5.1.
"""
from __future__ import annotations

import logging

import rtmidi

log = logging.getLogger("midi_agent.ports")

NOTE_ON = 0x90
NOTE_OFF = 0x80
CC = 0xB0


def parse_midi(data: list[int]) -> dict | None:
    """Parse a raw MIDI byte list into a small event dict, or None if unhandled.
    type in {'note_on','note_off','control_change'}."""
    if not data:
        return None
    status = data[0]
    kind = status & 0xF0
    channel = status & 0x0F
    if kind == NOTE_ON and len(data) >= 3:
        # note_on with velocity 0 is a note_off by convention
        if data[2] == 0:
            return {"type": "note_off", "channel": channel, "pitch": data[1], "velocity": 0}
        return {"type": "note_on", "channel": channel, "pitch": data[1], "velocity": data[2]}
    if kind == NOTE_OFF and len(data) >= 3:
        return {"type": "note_off", "channel": channel, "pitch": data[1], "velocity": data[2]}
    if kind == CC and len(data) >= 3:
        return {"type": "control_change", "channel": channel, "control": data[1], "value": data[2]}
    return None


def warn_on_collision(existing: list[str], wanted: str) -> bool:
    """Warn (once) if `wanted` already exists among `existing` port names. Returns True if
    a collision was found (e.g. a stale ALSA port from an unclean exit)."""
    if wanted in existing:
        log.warning("a MIDI port named %r already exists (possibly a stale port from an "
                    "unclean exit); opening another may show as %r 2. See README recovery note.",
                    wanted, wanted)
        return True
    return False


class Ports:
    """Owns the two virtual ports. Construct via Ports.open()."""

    def __init__(self, midi_in, midi_out, config) -> None:
        self._in = midi_in
        self._out = midi_out
        self.cfg = config
        self._open = True

    @classmethod
    def open(cls, config, *, in_factory=rtmidi.MidiIn, out_factory=rtmidi.MidiOut) -> "Ports":
        midi_in = in_factory()
        midi_out = out_factory()
        warn_on_collision(midi_in.get_ports(), config.port_in_name)
        warn_on_collision(midi_out.get_ports(), config.port_out_name)
        midi_in.open_virtual_port(config.port_in_name)
        midi_out.open_virtual_port(config.port_out_name)
        if hasattr(midi_in, "ignore_types"):
            midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        log.info("opened virtual ports: in=%r out=%r", config.port_in_name, config.port_out_name)
        return cls(midi_in, midi_out, config)

    def set_callback(self, fn) -> None:
        """fn receives (event, data) where event = (raw_bytes, delta_time), per rtmidi."""
        self._in.set_callback(fn)

    def send(self, message) -> None:
        self._out.send_message(list(message))

    def emit_test_scale(self, sleep=None) -> None:
        """Emit an ascending C-major scale (distinct test pattern, NOT an echo of input)."""
        for pitch in (60, 62, 64, 65, 67, 69, 71, 72):
            self.send([NOTE_ON, pitch, 96])
            if sleep is not None:
                sleep(0.18)
            self.send([NOTE_OFF, pitch, 0])
            if sleep is not None:
                sleep(0.04)

    def all_notes_off(self) -> None:
        for ch in range(16):
            self.send([CC | ch, 123, 0])

    def close(self) -> None:
        if not self._open:
            return
        try:
            self.all_notes_off()
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        for port in (self._in, self._out):
            try:
                port.close_port()
            except Exception:  # noqa: BLE001
                pass
        self._open = False
        log.info("ports closed")
