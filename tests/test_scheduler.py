"""M3 - the scheduler: ABSOLUTE-target timing (structural, fake clock) plus a real-clock
non-accumulation check, and sounding-note tracking + all-notes-off."""
from __future__ import annotations

import time

from capture import NoteRecord
from scheduler import Scheduler
from fake_port import FakeClock


def test_absolute_targets_never_a_running_sum():
    clock = FakeClock()
    sent = []
    sch = Scheduler(sent.append, now=clock.now, sleep=clock.sleep)
    notes = (NoteRecord(60, 80, 0.0, 0.5), NoteRecord(64, 80, 0.5, 1.0))
    result = sch.play(notes)
    assert result == "done"
    # events sorted by (offset, off-before-on): 0.0 on, 0.5 off, 0.5 on, 1.0 off
    expected = [sch.play_t0 + off for off in (0.0, 0.5, 0.5, 1.0)]
    assert sch.targets == expected
    # the headline invariant: each target is play_t0 + the note offset, NOT a cumulative sum
    assert sch.targets[-1] == sch.play_t0 + 1.0


def test_realclock_no_accumulated_drift():
    sent = []  # (perf_counter, message)
    sch = Scheduler(lambda m: sent.append((time.perf_counter(), m)), now=time.perf_counter, sleep=time.sleep)
    notes = tuple(NoteRecord(60 + i, 80, i * 0.01, i * 0.01 + 0.004) for i in range(4))
    sch.play(notes)
    ons = [(t, m) for (t, m) in sent if m[0] == 0x90]
    assert len(ons) == 4
    errors = [abs(t - (sch.play_t0 + i * 0.01)) for i, (t, m) in enumerate(ons)]
    # absolute targeting => error does not grow note-over-note (no accumulation)
    assert max(errors) < 0.05
    assert errors[-1] < errors[0] + 0.03


def test_reclaim_aborts_and_silences():
    clock = FakeClock()
    sent = []
    sch = Scheduler(sent.append, now=clock.now, sleep=clock.sleep)
    notes = (NoteRecord(60, 80, 0.0, 1.0), NoteRecord(64, 80, 1.0, 2.0))
    result = sch.play(notes, reclaim=lambda: True)  # reclaim immediately
    assert result == "aborted"
    assert any(m[0] == 0xB0 and m[1] == 123 for m in sent)  # all-notes-off sent


def test_sounding_tracked_and_all_notes_off():
    sent = []
    sch = Scheduler(sent.append, now=FakeClock().now)
    sch.sounding.add((60, 0))
    sch.sounding.add((64, 1))
    sch.all_notes_off()
    assert [0x80, 60, 0] in sent and [0x81, 64, 0] in sent      # explicit offs
    cc123 = [m for m in sent if len(m) == 3 and (m[0] & 0xF0) == 0xB0 and m[1] == 123]
    assert len(cc123) == 16                                      # all channels
    assert sch.sounding == set()
