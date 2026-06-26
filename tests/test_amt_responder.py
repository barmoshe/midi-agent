"""M5.4 / M5.5 / M5.8 - AmtResponder: the guarded import, the mocked call-and-response
round-trip, the response-window filter + t=0 re-base, and the scale-snap / humanize
post-passes. The model boundary (_encode / _generate / _decode) is mocked so the whole
path runs offline with no torch / transformers / anticipation installed."""
from __future__ import annotations

import pytest

import amt_engine
from amt_engine import AmtResponder
from capture import NoteRecord
from config import Config


def test_module_imports_but_construction_raises_without_deps(monkeypatch):
    # Importing the module must always work (no model deps at module level). When the deps
    # are absent, constructing AmtResponder must raise a catchable ImportError. We simulate
    # "deps absent" by blocking the transformers import, so this holds whether or not the
    # optional model deps happen to be installed in the venv.
    import sys

    monkeypatch.setitem(sys.modules, "transformers", None)
    assert amt_engine is not None
    with pytest.raises(ImportError):
        AmtResponder(Config())


def _deferred(config=None):
    # _deferred_load=True skips the model load so we can inject the boundary seams.
    return AmtResponder(config or Config(), _deferred_load=True)


def test_empty_phrase_returns_empty():
    assert _deferred().respond((), None) == ()


def test_respond_windows_rebases_and_snaps(c_major_phrase, c_major_context):
    r = _deferred()
    t_end = max(n.end_s for n in c_major_phrase)
    # Canned decode output (model-absolute times): one note BEFORE t_end (echoed history,
    # must be dropped), two AFTER, one of them out of key (C# = pc 1) so snap must fix it.
    decoded = [
        NoteRecord(60, 80, t_end - 1.0, t_end - 0.6),  # before the window -> filtered out
        NoteRecord(61, 80, t_end + 0.0, t_end + 0.4),  # out of key -> snapped into C major
        NoteRecord(67, 80, t_end + 0.5, t_end + 0.9),
    ]
    captured = {}

    def fake_generate(model, **kw):
        captured.update(kw)
        return ["EVENTS"]

    r._encode = lambda phrase: ["HISTORY"]
    r._generate = fake_generate
    r._decode = lambda events: list(decoded)

    out = r.respond(c_major_phrase, c_major_context)

    assert len(out) == 2                                  # the pre-window note was dropped
    assert min(n.start_s for n in out) == 0.0             # re-based to the handover instant
    assert all(n.start_s < n.end_s for n in out)          # dangling-free
    for n in out:
        assert n.pitch % 12 in c_major_context.scale      # in key after snap
    # call-and-response: the model was asked to continue AFTER the phrase (M5.8)
    assert captured["start_time"] >= t_end
    assert captured["end_time"] > captured["start_time"]
    assert captured["top_p"] == Config().amt_top_p


def test_snap_off_preserves_model_pitches(c_major_phrase, c_major_context):
    r = _deferred(Config(amt_snap=False, humanize=False))
    decoded = [NoteRecord(61, 80, 5.0, 5.4)]  # out of key
    r._encode = lambda phrase: ["H"]
    r._generate = lambda model, **kw: ["E"]
    r._decode = lambda events: list(decoded)
    out = r.respond(c_major_phrase, c_major_context)
    assert out[0].pitch == 61  # not snapped when amt_snap is off


def test_humanize_bounds(c_major_phrase, c_major_context):
    r = _deferred(Config(seed=3))
    decoded = [NoteRecord(72, 80, 5.0, 5.4), NoteRecord(76, 80, 5.5, 5.9)]  # both in key
    r._encode = lambda phrase: ["H"]
    r._generate = lambda model, **kw: ["E"]
    r._decode = lambda events: list(decoded)
    out = r.respond(c_major_phrase, c_major_context)
    assert all(1 <= n.velocity <= 127 for n in out)
    assert all(abs(n.velocity - 80) <= 4 for n in out)   # humanize velocity jitter is small
    assert min(n.start_s for n in out) == 0.0
