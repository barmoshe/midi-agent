"""Dynamic AI backing: pure helpers (register cap, time/key mapping, seed) and the AmtStream
continuous-generation wrapper (model boundary mocked, no torch needed)."""
from __future__ import annotations

from ai_backing import cap_register, place_chunk, seed_notes
from amt_engine import AmtStream
from backing import make_context
from capture import NoteRecord
from config import Config


def test_cap_register_drops_octaves_and_snaps():
    ctx = make_context("C:major")
    assert cap_register(ctx, 84, 72) == 72          # C6 -> C5
    p = cap_register(ctx, 73, 72)                     # C#5 -> below cap, snapped into key
    assert p <= 72 and p % 12 in ctx.scale


def test_place_chunk_maps_times_snaps_and_scales_velocity():
    ctx = make_context("C:major")
    new = [NoteRecord(61, 100, 0.0, 0.5), NoteRecord(67, 100, 0.5, 1.0)]  # 61 is out of key
    sched, timeline = place_chunk(new, cursor_s=10.0, wall_base=1000.0, ctx=ctx,
                                  register_cap=72, vel_scale=0.5)
    assert [s[0] for s in sched] == [1010.0, 1010.5]   # wall_base + cursor + onset
    for wall_on, wall_off, pitch, vel in sched:
        assert pitch % 12 in ctx.scale                 # snapped to key
        assert vel == 50                                # 100 * 0.5
        assert wall_off > wall_on
    assert timeline[0].start_s == 10.0                  # continuous model time


def test_seed_notes_in_key_and_nonempty():
    ctx = make_context("C:major")
    notes, total = seed_notes(ctx, 48, [1, 5, 6, 4], style="pulse", bpm=120, cycles=2)
    assert notes and total > 0
    for n in notes:
        assert n.pitch % 12 in ctx.scale
        assert n.start_s < n.end_s


def _deferred_stream():
    return AmtStream(Config(), _deferred_load=True)


def test_amtstream_continue_from_returns_rebased_tail():
    s = _deferred_stream()
    hist = [NoteRecord(60, 80, 0.0, 1.0), NoteRecord(64, 80, 1.0, 2.0)]  # history ends at 2.0
    decoded = [
        NoteRecord(60, 80, 0.5, 1.0),   # inside history -> dropped
        NoteRecord(67, 80, 2.0, 2.5),   # new -> kept, re-based to 0.0
        NoteRecord(72, 80, 2.5, 3.0),   # new -> kept, re-based to 0.5
    ]
    captured = {}

    def fake_generate(model, **kw):
        captured.update(kw)
        return ["E"]

    s._amt._encode = lambda phrase: ["H"]
    s._amt._generate = fake_generate
    s._amt._decode = lambda events: list(decoded)

    out = s.continue_from(hist, 4.0)
    assert [n.pitch for n in out] == [67, 72]
    assert [round(n.start_s, 3) for n in out] == [0.0, 0.5]
    assert captured["start_time"] == 2.0   # continue after the history window
    assert captured["end_time"] == 6.0     # + length_s


def test_amtstream_empty_history_generates_from_scratch():
    s = _deferred_stream()
    s._amt._generate = lambda model, **kw: ["E"]
    s._amt._decode = lambda events: [NoteRecord(60, 80, 0.0, 0.5)]
    out = s.continue_from([], 4.0)
    assert len(out) == 1 and out[0].start_s == 0.0
