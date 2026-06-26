"""M1 slice + M4 - guaranteed cleanup: panic_cleanup silences everything, and Agent.cleanup
is idempotent (runs once) and closes the ports on any exit."""
from __future__ import annotations

from agent import Agent, panic_cleanup
from config import Config
from scheduler import Scheduler
from fake_port import FakeClock


def test_panic_cleanup_silences_sounding_and_all_channels():
    sent = []
    sounding = {(60, 0), (64, 1)}
    panic_cleanup(sent.append, sounding)
    assert [0x80, 60, 0] in sent and [0x81, 64, 0] in sent   # explicit offs for held notes
    cc123 = [m for m in sent if len(m) == 3 and (m[0] & 0xF0) == 0xB0 and m[1] == 123]
    assert len(cc123) == 16
    assert sounding == set()


def test_panic_cleanup_runs_once_in_try_finally():
    sent = []
    calls = {"n": 0}

    def guarded():
        try:
            raise RuntimeError("mid-response boom")
        finally:
            calls["n"] += 1
            panic_cleanup(sent.append, {(72, 0)})

    try:
        guarded()
    except RuntimeError:
        pass
    assert calls["n"] == 1
    assert [0x80, 72, 0] in sent


class _FakePorts:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def test_agent_cleanup_is_idempotent_and_closes_ports():
    agent = Agent(Config())
    agent.ports = _FakePorts()
    agent.scheduler = Scheduler(lambda m: None, now=FakeClock().now)
    agent.scheduler.sounding.add((60, 0))
    agent.cleanup()
    agent.cleanup()   # second call must be a no-op
    assert agent.ports.closed == 1
