"""fake_port.py - in-memory doubles for the rtmidi ports + an injectable clock.

Lets the whole core (capture -> handover -> theory -> responder -> scheduler) run offline:
no real ports, no real sleeps. FakeMidiIn/Out mimic the slice of the rtmidi API that
ports.py uses; FakeClock advances only when told (or when the injected sleep is called),
so the poll-thread silence timers and scheduler timing are deterministic in tests.
"""
from __future__ import annotations


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt

    def sleep(self, dt: float) -> None:
        # an injected sleep advances the deterministic clock
        self.t += max(0.0, dt)


class FakeMidiOut:
    def __init__(self, existing=None, clock: FakeClock | None = None) -> None:
        self._existing = list(existing or [])
        self._clock = clock
        self.opened: str | None = None
        self.sent: list[tuple[list[int], float]] = []
        self.closed = False

    def get_ports(self):
        return list(self._existing)

    def open_virtual_port(self, name):
        self.opened = name

    def send_message(self, msg):
        t = self._clock.now() if self._clock is not None else 0.0
        self.sent.append((list(msg), t))

    def close_port(self):
        self.closed = True

    @property
    def messages(self):
        return [m for (m, _t) in self.sent]


class FakeMidiIn:
    def __init__(self, existing=None) -> None:
        self._existing = list(existing or [])
        self.opened: str | None = None
        self._cb = None
        self.closed = False

    def get_ports(self):
        return list(self._existing)

    def open_virtual_port(self, name):
        self.opened = name

    def set_callback(self, fn):
        self._cb = fn

    def ignore_types(self, **kwargs):
        pass

    def close_port(self):
        self.closed = True

    def inject(self, message, delta: float = 0.0):
        """Simulate an incoming MIDI message reaching the registered callback."""
        if self._cb is not None:
            self._cb((list(message), delta), None)
