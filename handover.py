"""handover.py - detecting that the human's turn has ended.

Hybrid: an explicit trigger CC (evaluated from the callback) OR a silence ladder that
MUST be evaluated by an independent poll thread - no callback fires while the human is
silent, so a pure-callback silence detector would never trigger. See design.md 2.1, 5.0.
"""
from __future__ import annotations

import threading
import time


class HandoverDetector:
    """Pure decision logic. `should_fire(now)` is called repeatedly by the poll loop."""

    def __init__(self, config, buffer) -> None:
        self.cfg = config
        self.buf = buffer
        self._cc_fired = False

    def on_control_change(self, control: int, value: int) -> None:
        """Called from the callback thread when a CC arrives."""
        if control == self.cfg.trigger_cc and value >= 64:
            self._cc_fired = True

    def should_fire(self, now: float) -> str | None:
        """Return the handover reason ('trigger_cc' | 'silence' | 'hard') or None."""
        if self._cc_fired:
            return "trigger_cc"
        let = self.buf.last_event_time
        if let is None or self.buf.is_empty:
            return None
        silent = now - let
        if self.buf.held_count == 0 and silent >= self.cfg.silence_ms / 1000.0:
            return "silence"
        if silent >= self.cfg.hard_ms / 1000.0:
            return "hard"
        return None

    def reset(self) -> None:
        self._cc_fired = False


class PollLoop:
    """Thin wrapper: wakes every poll_ms and calls the detector. The only home for the
    silence timers. Kept separate from the decision logic so it is testable via run_once()."""

    def __init__(self, detector: HandoverDetector, on_fire, *,
                 now=time.perf_counter, sleep=time.sleep, poll_ms: int = 30) -> None:
        self.detector = detector
        self.on_fire = on_fire
        self.now = now
        self.sleep = sleep
        self.poll_ms = poll_ms
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> str | None:
        """One tick. Returns the reason if it fired (and invokes on_fire)."""
        reason = self.detector.should_fire(self.now())
        if reason:
            self.on_fire(reason)
        return reason

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # a poll tick must never kill the loop
                pass
            self.sleep(self.poll_ms / 1000.0)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="handover-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
