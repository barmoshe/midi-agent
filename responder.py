"""responder.py - the generation engines behind one interface.

Responder is the only seam a generation engine plugs through. HeuristicResponder is the
default, no-GPU, no-key engine: it answers the human's OWN material (transpose / mirror /
arpeggiate / harmonize, snapped to the detected key) so it reads as a reply, not a random
transform. FallbackResponder wraps any engine so an ImportError/exception drops to the
heuristic. AmtResponder (M5) and ClaudeResponder (M6) are documented, not built here.
See design.md section 4.
"""
from __future__ import annotations

import logging
import random
import threading
from abc import ABC, abstractmethod

from capture import MIN_DUR_S, NoteRecord

log = logging.getLogger("midi_agent.responder")


class Responder(ABC):
    @abstractmethod
    def respond(self, phrase: tuple, context) -> tuple:
        """Return an answering phrase (tuple of NoteRecord), anchored to start at t=0."""
        raise NotImplementedError


class MotifAnalyzer:
    """Small helpers to answer the human's own material."""

    @staticmethod
    def tail(phrase: tuple, n: int = 4) -> tuple:
        return phrase[-n:] if len(phrase) > n else phrase

    @staticmethod
    def center_pitch(phrase: tuple) -> int:
        if not phrase:
            return 60
        return round(sum(n.pitch for n in phrase) / len(phrase))


def humanize(notes: list, seed: int, *, enabled: bool = True) -> list:
    """Deterministic (seeded) micro-variation: small velocity + timing jitter, then re-anchor
    so the response still starts at t=0 (the handover instant). Bypassable. Same seed + input
    -> identical output; preserves start_s >= 0 and start_s < end_s."""
    if not enabled:
        return notes
    rng = random.Random(seed)
    jittered = []  # (pitch, vel, start, end, ch)
    for n in notes:
        vel = max(1, min(127, n.velocity + rng.randint(-4, 4)))
        dt = rng.uniform(-0.004, 0.004)
        s = n.start_s + dt
        e = n.end_s + dt
        if e <= s:
            e = s + MIN_DUR_S
        jittered.append((n.pitch, vel, s, e, n.channel))
    shift = min(j[2] for j in jittered)  # re-anchor earliest onset to 0
    out = []
    for pitch, vel, s, e, ch in jittered:
        s -= shift
        e -= shift
        if e <= s:
            e = s + MIN_DUR_S
        out.append(NoteRecord(pitch, vel, max(0.0, s), e, ch))
    return out


class HeuristicResponder(Responder):
    """Deterministic, music-theory-aware. The v1 product engine."""

    def __init__(self, config) -> None:
        self.cfg = config

    def respond(self, phrase: tuple, context) -> tuple:
        if not phrase:
            return ()
        t0 = phrase[0].start_s  # re-anchor to 0 defensively
        mode = self.cfg.heuristic_mode
        builder = {
            "restate_vary": self._restate_vary,
            "mirror": self._mirror,
            "arpeggiate": self._arpeggiate,
            "harmonize": self._harmonize,
        }.get(mode, self._restate_vary)
        notes = builder(phrase, context, t0)
        notes = humanize(notes, self.cfg.seed, enabled=self.cfg.humanize)
        return tuple(notes)

    # Each transform returns a list of NoteRecord with start_s offsets from 0, all in-key.
    def _restate_vary(self, phrase, context, t0) -> list:
        out = []
        for n in phrase:
            pitch = context.degree_transpose(n.pitch, 2)  # up a diatonic third
            out.append(self._note(pitch, n.velocity, n.start_s - t0, n.end_s - t0, n.channel))
        return out

    def _mirror(self, phrase, context, t0) -> list:
        center = MotifAnalyzer.center_pitch(phrase)
        out = []
        for n in phrase:
            pitch = context.snap(2 * center - n.pitch)  # invert around center, snap to key
            out.append(self._note(pitch, n.velocity, n.start_s - t0, n.end_s - t0, n.channel))
        return out

    def _arpeggiate(self, phrase, context, t0) -> list:
        # arpeggiate the implied chord (root/third/fifth scale-degrees) over the phrase grid
        root = context.snap(phrase[0].pitch)
        chord = [root, context.degree_transpose(root, 2), context.degree_transpose(root, 4)]
        out = []
        for i, n in enumerate(phrase):
            out.append(self._note(chord[i % 3], n.velocity, n.start_s - t0, n.end_s - t0, n.channel))
        return out

    def _harmonize(self, phrase, context, t0) -> list:
        # the call plus a diatonic third above each note (two-voice reply)
        out = []
        for n in phrase:
            base = context.snap(n.pitch)
            third = context.degree_transpose(n.pitch, 2)
            out.append(self._note(base, n.velocity, n.start_s - t0, n.end_s - t0, n.channel))
            out.append(self._note(third, max(1, n.velocity - 12), n.start_s - t0, n.end_s - t0, n.channel))
        return out

    @staticmethod
    def _note(pitch, velocity, start_s, end_s, channel) -> NoteRecord:
        start_s = max(0.0, start_s)
        if end_s <= start_s:
            end_s = start_s + MIN_DUR_S
        return NoteRecord(pitch, max(1, min(127, velocity)), start_s, end_s, channel)


class FallbackResponder(Responder):
    """Wrap any engine; on ImportError/exception/timeout, drop to the always-importable
    heuristic. An optional timeout_s runs the primary in a daemon thread and abandons it if
    it overruns, so the live loop returns the heuristic answer instead of blocking on a slow
    generate. Best-effort by design (M5.7): the orphaned thread keeps running to completion
    (Python cannot hard-kill it); a truly enforceable kill would need process isolation."""

    def __init__(self, primary: Responder, fallback: Responder, timeout_s: float | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.timeout_s = timeout_s

    def respond(self, phrase: tuple, context) -> tuple:
        try:
            if self.timeout_s and self.timeout_s > 0:
                return self._run_with_timeout(phrase, context)
            return self.primary.respond(phrase, context)
        except Exception as exc:  # noqa: BLE001 - any engine failure must keep the music going
            log.warning("primary responder failed (%s); using heuristic fallback", exc)
            return self.fallback.respond(phrase, context)

    def _run_with_timeout(self, phrase: tuple, context) -> tuple:
        box: dict = {}

        def _run() -> None:
            try:
                box["ok"] = self.primary.respond(phrase, context)
            except Exception as exc:  # noqa: BLE001 - surfaced to respond() for the fallback
                box["err"] = exc

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        th.join(self.timeout_s)
        if th.is_alive():
            raise TimeoutError(f"primary responder exceeded {self.timeout_s}s")
        if "err" in box:
            raise box["err"]
        return box.get("ok", ())


def build_responder(config) -> Responder:
    """Factory: always return a FallbackResponder wrapping the chosen engine, with the
    heuristic as the safety net. M5/M6 engines are guarded imports (not installed by default)."""
    heuristic = HeuristicResponder(config)
    if config.responder == "heuristic":
        return heuristic
    if config.responder == "amt":  # M5, optional local model
        try:
            from amt_engine import AmtResponder
            primary = AmtResponder(config)
        except Exception as exc:  # noqa: BLE001 - missing deps / model load -> heuristic
            log.warning("AMT engine unavailable (%s); using heuristic", exc)
            return heuristic
        return FallbackResponder(primary, heuristic, timeout_s=config.amt_timeout)
    if config.responder == "claude":  # pragma: no cover - M6, optional API engine
        from claude_engine import ClaudeResponder  # noqa: F401 - not built this milestone
        return FallbackResponder(ClaudeResponder(config), heuristic)
    return heuristic
