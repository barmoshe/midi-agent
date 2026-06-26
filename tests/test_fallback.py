"""M5.6 / M5.7 - the FallbackResponder timeout posture and the amt factory degrading to
the heuristic when the model deps are absent."""
from __future__ import annotations

import logging
import time

from config import Config
from responder import FallbackResponder, HeuristicResponder, Responder, build_responder


class _SlowResponder(Responder):
    def __init__(self, delay):
        self.delay = delay

    def respond(self, phrase, context):
        time.sleep(self.delay)
        return ("SHOULD_NOT_BE_USED",)


def test_timeout_falls_back_to_heuristic_within_margin(c_major_phrase, c_major_context):
    heuristic = HeuristicResponder(Config())
    wrapped = FallbackResponder(_SlowResponder(2.0), heuristic, timeout_s=0.2)
    t0 = time.monotonic()
    out = wrapped.respond(c_major_phrase, c_major_context)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2 + 0.5  # returned promptly; did not block on the 2s primary
    assert out == heuristic.respond(c_major_phrase, c_major_context)


def test_no_timeout_behaves_as_passthrough(c_major_phrase, c_major_context):
    heuristic = HeuristicResponder(Config())
    primary = HeuristicResponder(Config(heuristic_mode="mirror"))
    wrapped = FallbackResponder(primary, heuristic)  # timeout_s=None -> direct passthrough
    assert wrapped.respond(c_major_phrase, c_major_context) == primary.respond(c_major_phrase, c_major_context)


def test_amt_factory_degrades_to_heuristic_without_deps(monkeypatch, c_major_phrase, c_major_context, caplog):
    # When the model deps are absent, AmtResponder construction raises -> build_responder must
    # log a warning and return a heuristic-equivalent, never crash. Simulate "deps absent" by
    # blocking the transformers import so this holds regardless of what is installed.
    import sys

    monkeypatch.setitem(sys.modules, "transformers", None)
    with caplog.at_level(logging.WARNING):
        r = build_responder(Config(responder="amt"))
    assert any("AMT engine unavailable" in rec.message for rec in caplog.records)
    out = r.respond(c_major_phrase, c_major_context)
    assert out == HeuristicResponder(Config()).respond(c_major_phrase, c_major_context)
