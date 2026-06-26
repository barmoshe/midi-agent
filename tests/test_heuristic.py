"""M3 - the HeuristicResponder: determinism, the in-key invariant, dangling-free output,
and the FallbackResponder dropping to the heuristic on a broken engine."""
from __future__ import annotations

from config import Config
from responder import FallbackResponder, HeuristicResponder, Responder


def test_empty_phrase_returns_empty(c_major_context):
    assert HeuristicResponder(Config()).respond((), c_major_context) == ()


def test_deterministic_same_input_same_output(c_major_phrase, c_major_context):
    r = HeuristicResponder(Config(seed=7))
    a = r.respond(c_major_phrase, c_major_context)
    b = r.respond(c_major_phrase, c_major_context)
    assert a == b
    assert len(a) == len(c_major_phrase)


def test_every_output_pitch_is_in_key(c_major_phrase, c_major_context):
    for mode in ("restate_vary", "mirror", "arpeggiate", "harmonize"):
        out = HeuristicResponder(Config(heuristic_mode=mode)).respond(c_major_phrase, c_major_context)
        assert out, mode
        for n in out:
            assert n.pitch % 12 in c_major_context.scale, (mode, n.pitch)


def test_output_is_dangling_free_and_anchored(c_major_phrase, c_major_context):
    out = HeuristicResponder(Config()).respond(c_major_phrase, c_major_context)
    assert all(n.start_s < n.end_s for n in out)
    assert all(n.start_s >= 0.0 for n in out)
    assert min(n.start_s for n in out) == 0.0   # anchored to t=0


def test_humanize_off_is_pure_transform(c_major_phrase, c_major_context):
    out = HeuristicResponder(Config(humanize=False)).respond(c_major_phrase, c_major_context)
    # restate_vary up a diatonic third (walks up from each pitch):
    # C4->E4, D4->F4, E4->G4, G4->B4, C5->E5
    assert [n.pitch for n in out] == [64, 65, 67, 71, 76]


class _BrokenResponder(Responder):
    def respond(self, phrase, context):
        raise RuntimeError("engine down")


def test_fallback_drops_to_heuristic_on_failure(c_major_phrase, c_major_context):
    heuristic = HeuristicResponder(Config())
    wrapped = FallbackResponder(_BrokenResponder(), heuristic)
    out = wrapped.respond(c_major_phrase, c_major_context)
    assert out == heuristic.respond(c_major_phrase, c_major_context)
