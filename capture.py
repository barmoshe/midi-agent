"""capture.py - the shared note contract + the lock-guarded phrase buffer.

NoteRecord is the immutable unit every module speaks. PhraseBuffer is written ONLY by the
rtmidi callback thread (note_on/note_off/touch) and read at handover by the state machine.
On snapshot it synthesizes note_offs for still-open notes and normalizes the phrase so the
first onset is at t=0 (phrase_t0). See design.md sections 2.1, 2.2, 5.0.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

# A synthesized or zero-length note gets this minimum positive duration so the
# NoteRecord start_s < end_s invariant always holds.
MIN_DUR_S = 0.005


@dataclass(frozen=True)
class NoteRecord:
    """One note. Times are seconds; in a frozen phrase they are relative to phrase_t0,
    in a response they are offsets from 0 (the handover instant). start_s < end_s always."""
    pitch: int
    velocity: int
    start_s: float
    end_s: float
    channel: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.pitch <= 127:
            raise ValueError(f"pitch out of range: {self.pitch}")
        if not 1 <= self.velocity <= 127:
            raise ValueError(f"velocity out of range (1-127): {self.velocity}")
        if not 0 <= self.channel <= 15:
            raise ValueError(f"channel out of range: {self.channel}")
        if not self.start_s < self.end_s:
            raise ValueError(f"start_s must be < end_s (got {self.start_s} >= {self.end_s})")


class PhraseBuffer:
    """Thread-safe accumulator. The callback thread is the only writer."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._completed: list[dict] = []          # finished notes (absolute times)
        self._open: dict[tuple[int, int], tuple[float, int]] = {}  # (pitch,ch) -> (start, vel)
        self._first_time: float | None = None     # phrase_t0 source (first onset)
        self.last_event_time: float | None = None  # any activity (on/off/cc); silence is measured from here

    # --- writes (callback thread) ---
    def note_on(self, pitch: int, velocity: int, channel: int, t: float) -> None:
        with self._lock:
            self._touch(t, onset=True)
            self._open[(pitch, channel)] = (t, max(1, min(127, velocity)))

    def note_off(self, pitch: int, channel: int, t: float) -> None:
        with self._lock:
            self._touch(t)
            key = (pitch, channel)
            if key in self._open:
                start, vel = self._open.pop(key)
                end = t if t > start else start + MIN_DUR_S
                self._completed.append({"pitch": pitch, "vel": vel, "start": start, "end": end, "ch": channel})

    def touch(self, t: float) -> None:
        """Register non-note activity (e.g. a CC) so it resets the silence timer."""
        with self._lock:
            self._touch(t)

    def _touch(self, t: float, onset: bool = False) -> None:
        if onset and self._first_time is None:
            self._first_time = t
        self.last_event_time = t

    # --- reads (poll thread / state machine) ---
    @property
    def held_count(self) -> int:
        with self._lock:
            return len(self._open)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return not self._completed and not self._open

    def snapshot(self, handover_t: float) -> tuple[NoteRecord, ...]:
        """Freeze the phrase: close dangling notes at handover_t, normalize to phrase_t0,
        return an immutable, time-sorted tuple of NoteRecords. Never mutates the buffer."""
        with self._lock:
            raw = list(self._completed)
            for (pitch, ch), (start, vel) in self._open.items():
                end = handover_t if handover_t > start else start + MIN_DUR_S
                raw.append({"pitch": pitch, "vel": vel, "start": start, "end": end, "ch": ch})
            if not raw:
                return ()
            t0 = min(r["start"] for r in raw)
            raw.sort(key=lambda r: (r["start"], r["pitch"]))
            notes = []
            for r in raw:
                s = r["start"] - t0
                e = r["end"] - t0
                if e <= s:
                    e = s + MIN_DUR_S
                notes.append(NoteRecord(r["pitch"], r["vel"], s, e, r["ch"]))
            return tuple(notes)

    def reset(self) -> None:
        with self._lock:
            self._completed.clear()
            self._open.clear()
            self._first_time = None
            self.last_event_time = None
