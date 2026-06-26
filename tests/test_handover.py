"""M2 - handover detection via the poll path: silence ladder, hard override, trigger CC,
and the dangling-note closeout at snapshot. Driven by a deterministic clock, no real waits."""
from __future__ import annotations

from capture import PhraseBuffer
from config import Config
from handover import HandoverDetector


def _played_buffer(t_on=0.0, t_off=0.2):
    buf = PhraseBuffer()
    buf.note_on(60, 80, 0, t_on)
    buf.note_off(60, 0, t_off)   # released, nothing held
    return buf


def test_silence_fires_only_after_threshold():
    buf = _played_buffer(t_off=0.2)
    det = HandoverDetector(Config(silence_ms=700), buf)
    # 0.2s + 0.5s silence -> not yet
    assert det.should_fire(0.2 + 0.5) is None
    # 0.2s + 0.7s silence -> fires
    assert det.should_fire(0.2 + 0.7) == "silence"


def test_silence_does_not_fire_while_a_note_is_held():
    buf = PhraseBuffer()
    buf.note_on(60, 80, 0, 0.0)   # held, never released
    det = HandoverDetector(Config(silence_ms=700, hard_ms=3000), buf)
    assert buf.held_count == 1
    assert det.should_fire(0.0 + 1.0) is None       # silence ladder gated by held note


def test_hard_override_fires_even_with_a_note_held():
    buf = PhraseBuffer()
    buf.note_on(60, 80, 0, 0.0)
    det = HandoverDetector(Config(silence_ms=700, hard_ms=3000), buf)
    assert det.should_fire(3.0) == "hard"


def test_trigger_cc_fires_immediately():
    buf = _played_buffer()
    det = HandoverDetector(Config(trigger_cc=67), buf)
    det.on_control_change(67, 100)
    assert det.should_fire(0.21) == "trigger_cc"


def test_trigger_cc_ignores_other_cc_and_low_values():
    buf = _played_buffer()
    det = HandoverDetector(Config(trigger_cc=67), buf)
    det.on_control_change(64, 127)   # sustain, not the trigger
    det.on_control_change(67, 10)    # below 64
    assert det.should_fire(0.3) is None


def test_empty_buffer_never_fires_on_silence():
    det = HandoverDetector(Config(), PhraseBuffer())
    assert det.should_fire(100.0) is None


def test_snapshot_closes_dangling_note_and_normalizes():
    buf = PhraseBuffer()
    buf.note_on(60, 80, 0, 1.00)
    buf.note_off(60, 0, 1.40)
    buf.note_on(64, 80, 0, 1.50)   # left open (dangling)
    phrase = buf.snapshot(handover_t=2.00)
    assert len(phrase) == 2
    # normalized: first onset at 0
    assert phrase[0].start_s == 0.0
    # dangling note closed at the handover instant, normalized
    last = phrase[-1]
    assert last.pitch == 64
    assert abs(last.end_s - (2.00 - 1.00)) < 1e-9
    # every note valid (start < end)
    assert all(n.start_s < n.end_s for n in phrase)
