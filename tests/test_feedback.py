"""M4 - the echo-guard: the agent must not mistake the DAW's thru of its OWN output for a
human reclaim. is_echo() is true for a recently-emitted (pitch, channel) within the window
and false for a different note or one just past the window."""
from __future__ import annotations

from capture import NoteRecord
from scheduler import Scheduler
from fake_port import FakeClock


def test_own_output_is_recognised_as_echo_not_reclaim():
    clock = FakeClock()
    sent = []
    sch = Scheduler(sent.append, now=clock.now, echo_window_ms=150)
    sch._note_on(NoteRecord(60, 90, 0.0, 0.5))   # emitted at t=0

    # the same note comes back on Agent In 100ms later (DAW thru) -> echo, ignore for reclaim
    assert sch.is_echo(60, 0, now=0.10) is True
    # a DIFFERENT note the human actually played -> not an echo -> would count as reclaim
    assert sch.is_echo(62, 0, now=0.10) is False


def test_echo_window_boundary():
    sch = Scheduler(lambda m: None, now=FakeClock().now, echo_window_ms=150)
    sch._note_on(NoteRecord(67, 90, 0.0, 0.5))   # emitted at t=0
    assert sch.is_echo(67, 0, now=0.14) is True    # within 150ms
    assert sch.is_echo(67, 0, now=0.20) is False   # past the window -> a real (late) note
