"""amt_engine.py - the optional local AMT (Anticipatory Music Transformer) engine (M5).

The "smart", no-API-key engine: a pretrained symbolic-music transformer answers the
human's phrase, plugged through the same Responder seam as the heuristic. The model deps
(transformers, torch, anticipation) live in requirements-model.txt and are NOT installed
by default, so the heavy imports are GUARDED inside AmtResponder: importing this module
never fails, but constructing AmtResponder without the deps raises a catchable ImportError
(which build_responder turns into a heuristic fallback).

The NoteRecord <-> temp .mid bridge below is model-free (mido only) and unit-tested on its
own. respond() runs the call-and-response round-trip behind injectable seams
(_encode / _generate / _decode) so the whole path is testable offline with no model
installed. See design.md section 4.4 and plan.md M5.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading  # noqa: F401 - kept for parity with the agent's thread model / future use
from pathlib import Path

import mido

from capture import MIN_DUR_S, NoteRecord
from responder import Responder, humanize

# Silence the anticipation library's internal tqdm progress bars (they spam the terminal
# during live playback). Set TQDM_DISABLE=0 in the environment to bring them back.
os.environ.setdefault("TQDM_DISABLE", "1")

log = logging.getLogger("midi_agent.amt")

# Fixed grid for the temp-.mid bridge. Agent times are absolute seconds; pinning the tempo
# makes the seconds<->ticks conversion deterministic and reversible.
_TPB = 480
_TEMPO = 500_000  # microseconds per beat = 120 bpm
_WINDOW_EPS = 1e-3  # tolerance when filtering generated notes to the response window


# --------------------------------------------------------------------------- #
# Model-free NoteRecord <-> temp .mid bridge (M5.3)                            #
# --------------------------------------------------------------------------- #
def phrase_to_tempmid(phrase) -> Path:
    """Write a phrase (NoteRecords, absolute seconds) to a temp .mid and return its path.
    Caller owns deletion. mido only - no model dependency."""
    mid = mido.MidiFile(ticks_per_beat=_TPB)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=_TEMPO, time=0))
    # (abs_tick, order, msg): a note_off (order 0) sorts before a note_on (order 1) at a tie.
    events = []
    for n in phrase:
        on = int(round(mido.second2tick(n.start_s, _TPB, _TEMPO)))
        off = int(round(mido.second2tick(n.end_s, _TPB, _TEMPO)))
        if off <= on:
            off = on + 1
        events.append((on, 1, mido.Message("note_on", note=n.pitch, velocity=n.velocity, channel=n.channel)))
        events.append((off, 0, mido.Message("note_off", note=n.pitch, velocity=0, channel=n.channel)))
    events.sort(key=lambda e: (e[0], e[1]))
    prev = 0
    for abs_tick, _, msg in events:
        msg.time = abs_tick - prev
        prev = abs_tick
        track.append(msg)
    path = Path(_new_temp(".mid"))
    mid.save(str(path))
    return path


def tempmid_to_notes(path, rebase: bool = True) -> list:
    """Read a .mid back into time-sorted NoteRecords (absolute seconds). rebase=True shifts
    the earliest onset to 0 (the bridge contract); rebase=False keeps model-absolute times
    (used to filter the response window). mido only."""
    open_notes: dict[tuple[int, int], tuple[float, int]] = {}
    out: list[NoteRecord] = []
    abs_s = 0.0
    for msg in mido.MidiFile(str(path)):
        abs_s += msg.time  # mido yields .time already in seconds
        if msg.type == "note_on" and msg.velocity > 0:
            open_notes[(msg.note, msg.channel)] = (abs_s, msg.velocity)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.note, msg.channel)
            if key in open_notes:
                start, vel = open_notes.pop(key)
                end = abs_s if abs_s > start else start + MIN_DUR_S
                out.append(NoteRecord(msg.note, vel, start, end, msg.channel))
    out.sort(key=lambda n: (n.start_s, n.pitch))
    return rebase_to_zero(out) if rebase else out


def rebase_to_zero(notes) -> list:
    """Shift so the earliest onset is 0, preserving relative timing; dangling-free."""
    if not notes:
        return []
    t0 = min(n.start_s for n in notes)
    out = []
    for n in notes:
        s = max(0.0, n.start_s - t0)
        e = n.end_s - t0
        if e <= s:
            e = s + MIN_DUR_S
        out.append(NoteRecord(n.pitch, n.velocity, s, e, n.channel))
    return out


def _new_temp(suffix: str) -> str:
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="midi_agent_amt_")
    os.close(fd)
    return name


def _safe_unlink(path) -> None:
    try:
        os.unlink(str(path))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# The engine (M5.4 / M5.5 / M5.8)                                             #
# --------------------------------------------------------------------------- #
class AmtResponder(Responder):
    """Local Anticipatory Music Transformer engine. The guarded import + lazy model load
    happen in __init__, so constructing this without the model deps raises ImportError
    (build_responder catches it and falls back to the heuristic). respond() runs the
    section-4.4 round-trip through injectable seams so it is fully testable offline."""

    MODEL_DEFAULT = "stanford-crfm/music-medium-800k"

    def __init__(self, config, *, _deferred_load: bool = False) -> None:
        self.cfg = config
        self._model = None
        self._midi_to_events = None
        self._events_to_midi = None
        self._generate = None
        if not _deferred_load:  # _deferred_load=True is the offline-test seam
            self._load()

    def _load(self) -> None:
        try:
            from transformers import AutoModelForCausalLM
            from anticipation.convert import events_to_midi, midi_to_events
            from anticipation.sample import generate
        except ImportError as exc:
            raise ImportError(
                "AMT engine needs requirements-model.txt (transformers, torch, anticipation): "
                f"{exc}"
            ) from exc
        self._midi_to_events = midi_to_events
        self._events_to_midi = events_to_midi
        self._generate = generate
        device = _select_device(self.cfg.amt_device)
        model = AutoModelForCausalLM.from_pretrained(self.cfg.amt_model)
        if device != "cpu":
            try:
                model = model.to(device)
            except Exception as exc:  # noqa: BLE001 - device move is best-effort; stay on cpu
                log.warning("could not move AMT model to %s (%s); staying on cpu", device, exc)
                device = "cpu"
        self._model = model
        log.info("AMT model loaded: %s on %s", self.cfg.amt_model, device)

    # --- Responder interface ---
    def respond(self, phrase: tuple, context) -> tuple:
        if not phrase:
            return ()
        t_end = max(n.end_s for n in phrase)
        resp_len = self._response_seconds(context)
        history = self._encode(phrase)
        events = self._generate(
            self._model,
            start_time=t_end,
            end_time=t_end + resp_len,
            inputs=history,
            top_p=self.cfg.amt_top_p,
        )
        raw = self._decode(events)
        # Call-and-response (M5.8): keep only what the model added AFTER the phrase, then
        # re-base so the reply starts at the handover instant (t=0). If the model put
        # nothing after t_end, fall back to whatever it produced rather than going silent.
        window = [n for n in raw if n.start_s >= t_end - _WINDOW_EPS]
        notes = rebase_to_zero(window or raw)
        return tuple(self._post(notes, context))

    # --- injectable seams (mocked in offline tests) ---
    def _encode(self, phrase) -> list:
        path = phrase_to_tempmid(phrase)
        try:
            return self._midi_to_events(str(path))
        finally:
            _safe_unlink(path)

    def _decode(self, events) -> list:
        midi = self._events_to_midi(events)
        path = Path(_new_temp(".mid"))
        try:
            midi.save(str(path))
            return tempmid_to_notes(path, rebase=False)
        finally:
            _safe_unlink(path)

    def _post(self, notes, context) -> list:
        # Shared post-passes (M5.5): scale-snap stray model pitches into the detected key,
        # then the same humanize() the heuristic uses. Reuses the existing helpers.
        if self.cfg.amt_snap and context is not None:
            notes = [
                NoteRecord(context.snap(n.pitch), n.velocity, n.start_s, n.end_s, n.channel)
                for n in notes
            ]
        return humanize(notes, self.cfg.seed, enabled=self.cfg.humanize)

    def _response_seconds(self, context) -> float:
        beats = 4 * max(1, self.cfg.amt_response_bars)
        spb = context.ioi if (context is not None and context.ioi) else 0.5
        return max(0.5, beats * spb)

    # Prefill-during-listen optimization (design 4.4): a documented NO-OP stretch hook, not
    # v1. Prefilling the model with the human's phrase DURING their turn would remove the
    # 1-2s post-handover prefill; deliberately left unimplemented.


class AmtStream:
    """Continuous AMT generation for a streaming, evolving accompaniment. Wraps the same
    guarded model load as AmtResponder. `continue_from(history, length_s)` feeds the recent
    history back into the model and returns the next `length_s` seconds of NEW notes, re-based
    so the new material starts at 0. Reuses AmtResponder's encode/generate/decode seams, so it
    is testable offline by injecting them (and raises ImportError without the deps)."""

    def __init__(self, config, *, _deferred_load: bool = False) -> None:
        self._amt = AmtResponder(config, _deferred_load=_deferred_load)
        self.cfg = config

    @property
    def ready(self) -> bool:
        return self._amt._model is not None

    def continue_from(self, history, length_s: float) -> list:
        hist = list(history)
        h_end = max((n.end_s for n in hist), default=0.0)
        events_in = self._amt._encode(tuple(hist)) if hist else []
        events = self._amt._generate(
            self._amt._model, start_time=h_end, end_time=h_end + length_s,
            inputs=events_in, top_p=self.cfg.amt_top_p,
        )
        raw = self._amt._decode(events)
        out = []
        for n in raw:
            if n.start_s < h_end - _WINDOW_EPS:  # keep only the newly generated tail
                continue
            s = max(0.0, n.start_s - h_end)
            e = n.end_s - h_end
            if e <= s:
                e = s + MIN_DUR_S
            out.append(NoteRecord(n.pitch, n.velocity, s, e, n.channel))
        return out


def _select_device(pref: str) -> str:
    """Resolve --amt-device: 'auto' picks cuda -> mps -> cpu; otherwise honor the literal."""
    if pref and pref != "auto":
        return pref
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001 - torch absent or probe failed -> cpu
        pass
    return "cpu"
