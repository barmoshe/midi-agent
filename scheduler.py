"""scheduler.py - stream a response to Agent Out with correct timing + safety.

Plays a response note list note-by-note using ABSOLUTE sleep targets (play_t0 + offset),
never cumulative per-note sleeps, so timing never drifts across a multi-note response.
Tracks sounding notes for guaranteed cleanup, and provides the echo-guard so the agent
never mistakes the DAW's thru of its own output for a human reclaim. See design 2.2, 5.1, 5.2.
"""
from __future__ import annotations

import time
from collections import deque

NOTE_ON = 0x90
NOTE_OFF = 0x80
CC = 0xB0
ALL_NOTES_OFF = 123


class Scheduler:
    def __init__(self, send, *, now=time.perf_counter, sleep=time.sleep, echo_window_ms: int = 150) -> None:
        self.send = send                      # callable(list[int]) -> None
        self.now = now
        self.sleep = sleep
        self.echo_window = echo_window_ms / 1000.0
        self.sounding: set[tuple[int, int]] = set()   # (pitch, channel) currently on
        self._emitted: deque = deque()        # (pitch, channel, t) for the echo-guard
        # introspection for tests:
        self.play_t0: float | None = None
        self.targets: list[float] = []        # absolute sleep target per event, in order

    def play(self, notes: tuple, reclaim=None) -> str:
        """Stream `notes`. If `reclaim()` becomes true mid-stream, abort + all-notes-off.
        Returns 'done' | 'aborted' | 'empty'."""
        if not notes:
            return "empty"
        events = []  # (offset, kind, note)
        for n in notes:
            events.append((n.start_s, "on", n))
            events.append((n.end_s, "off", n))
        # at equal times, note_offs before note_ons (avoid a same-pitch off cancelling a fresh on)
        events.sort(key=lambda e: (e[0], 0 if e[1] == "off" else 1))

        self.play_t0 = self.now()
        self.targets = []
        for offset, kind, n in events:
            target = self.play_t0 + offset      # ABSOLUTE target, never a running sum
            self.targets.append(target)
            dt = target - self.now()
            if dt > 0:
                self.sleep(dt)
            if reclaim is not None and reclaim():
                self.abort()
                return "aborted"
            if kind == "on":
                self._note_on(n)
            else:
                self._note_off(n)
        return "done"

    def _note_on(self, n) -> None:
        self.send([NOTE_ON | n.channel, n.pitch, n.velocity])
        self.sounding.add((n.pitch, n.channel))
        self._emitted.append((n.pitch, n.channel, self.now()))

    def _note_off(self, n) -> None:
        self.send([NOTE_OFF | n.channel, n.pitch, 0])
        self.sounding.discard((n.pitch, n.channel))

    def is_echo(self, pitch: int, channel: int, now: float | None = None) -> bool:
        """True if (pitch, channel) matches one we emitted within echo_window (DAW thru of
        our own output), so the reclaim path should ignore it."""
        t = self.now() if now is None else now
        while self._emitted and t - self._emitted[0][2] > self.echo_window:
            self._emitted.popleft()
        return any(p == pitch and c == channel for (p, c, _t) in self._emitted)

    def abort(self) -> None:
        """Stop and silence: explicit offs for sounding notes + CC123 on all channels."""
        self.all_notes_off()

    def all_notes_off(self) -> None:
        for (pitch, channel) in list(self.sounding):
            self.send([NOTE_OFF | channel, pitch, 0])
        self.sounding.clear()
        for ch in range(16):
            self.send([CC | ch, ALL_NOTES_OFF, 0])
