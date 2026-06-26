"""ai_backing.py - a dynamic, AI-generated backing track you solo over.

Streams a continuously evolving accompaniment to the Agent Out virtual port using the local
AMT model (install requirements-model.txt). It starts INSTANTLY with a few in-key chords (the
rule-based seed) while the model warms up, then the AMT model takes over and keeps generating
fresh material, feeding its own recent output back in so the groove evolves instead of looping.

Every note is snapped to your key so your solo always fits, and the register is capped by
default so the AI stays under your lead. If the model deps are missing (or a generation
fails / falls behind) it covers the gap with the rule-based progression, so the music never
stops. It only plays - never listens - so there is no input routing and no feedback. Ctrl-C
to stop.

Architecture: a generator thread produces chunks ahead of the playhead into a time-ordered
buffer; the main thread streams that buffer to MIDI. The pure mapping (place_chunk) is unit
-tested; the real-time threads + model are the integration layer (see ai_backing_smoke).
"""
from __future__ import annotations

import argparse
import atexit
import heapq
import logging
import signal
import threading
import time

from backing import cycle_events, make_context
from capture import MIN_DUR_S, NoteRecord
from config import Config
from ports import NOTE_OFF, NOTE_ON, Ports
from theory import MusicalContext

log = logging.getLogger("midi_agent.ai_backing")

BEATS_PER_BAR = 4


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)                                                   #
# --------------------------------------------------------------------------- #
def cap_register(ctx: MusicalContext, pitch: int, register_cap: int) -> int:
    """Drop `pitch` by whole octaves until it is at or below register_cap, then snap to key."""
    while pitch > register_cap:
        pitch -= 12
    return ctx.snap(max(0, pitch))


def place_chunk(new_notes, cursor_s: float, wall_base: float, ctx: MusicalContext, *,
                register_cap: int, vel_scale: float):
    """Map a chunk of NEW notes (onsets re-based to 0) onto the continuous model timeline at
    `cursor_s`, snapping pitches to key, capping the register, and scaling velocity. Returns
    (scheduled, timeline_notes): scheduled = list of (wall_on, wall_off, pitch, vel) absolute
    wall times; timeline_notes = the placed NoteRecords in continuous model time (for history).
    Pure - no clock, no I/O."""
    scheduled = []
    timeline_notes = []
    for n in new_notes:
        pitch = cap_register(ctx, n.pitch, register_cap)
        vel = max(1, min(127, int(round(n.velocity * vel_scale))))
        model_on = cursor_s + n.start_s
        model_off = cursor_s + max(n.end_s, n.start_s + MIN_DUR_S)
        scheduled.append((wall_base + model_on, wall_base + model_off, pitch, vel))
        timeline_notes.append(NoteRecord(pitch, n.velocity, model_on, model_off, 0))
    return scheduled, timeline_notes


def seed_notes(ctx, tonic_pitch, progression, *, style, bpm, cycles):
    """Rule-based seed/fallback: `cycles` of the chord progression as NoteRecords in seconds,
    starting at model-time 0. Reuses backing.cycle_events. Returns (notes, total_seconds)."""
    events, cycle_beats = cycle_events(ctx, tonic_pitch, progression, style=style)
    spb = 60.0 / bpm
    notes = []
    for c in range(cycles):
        base = c * cycle_beats * spb
        for onset, dur, pitch, vel in events:
            s = base + onset * spb
            e = base + (onset + dur) * spb
            notes.append(NoteRecord(pitch, vel, s, e if e > s else s + MIN_DUR_S, 0))
    return notes, cycles * cycle_beats * spb


# --------------------------------------------------------------------------- #
# Real-time buffer + threads                                                   #
# --------------------------------------------------------------------------- #
class TimedBuffer:
    """Thread-safe time-ordered MIDI event buffer. Generator pushes notes; player pops due."""

    def __init__(self) -> None:
        self._heap: list = []
        self._lock = threading.Lock()
        self._seq = 0
        self.produced_until = 0.0  # latest wall time scheduled so far

    def push(self, wall_on, wall_off, pitch, vel) -> None:
        with self._lock:
            heapq.heappush(self._heap, (wall_on, self._seq, 1, pitch, vel)); self._seq += 1
            heapq.heappush(self._heap, (wall_off, self._seq, 0, pitch, 0)); self._seq += 1
            self.produced_until = max(self.produced_until, wall_off)

    def pop_due(self, now: float) -> list:
        out = []
        with self._lock:
            while self._heap and self._heap[0][0] <= now:
                out.append(heapq.heappop(self._heap))
        return out


def _generate_loop(stream, buffer, ctx, tonic_pitch, progression, wall_base, stop, *,
                   chunk_s, history_s, lookahead_s, register_cap, vel_scale, style, bpm,
                   seed_timeline):
    timeline = list(seed_timeline)                       # continuous model-time history
    cursor = max((n.end_s for n in timeline), default=0.0)
    while not stop.is_set():
        # stay roughly lookahead_s ahead of the playhead, then idle
        if buffer.produced_until - time.perf_counter() > lookahead_s:
            stop.wait(0.2)
            continue
        window = _rebase([n for n in timeline if n.start_s >= cursor - history_s])
        new = []
        if stream is not None and stream.ready:
            try:
                new = stream.continue_from(window, chunk_s)
            except Exception as exc:  # noqa: BLE001 - keep the music going
                log.warning("AMT generate failed (%s); covering with the progression", exc)
        if not new:  # no model, model fell silent, or it failed -> rule-based cover
            cover, _ = seed_notes(ctx, tonic_pitch, progression, style=style, bpm=bpm, cycles=1)
            new = cover
        scheduled, placed = place_chunk(new, cursor, wall_base, ctx,
                                        register_cap=register_cap, vel_scale=vel_scale)
        for wall_on, wall_off, pitch, vel in scheduled:
            buffer.push(wall_on, wall_off, pitch, vel)
        timeline.extend(placed)
        span = max((n.end_s - cursor for n in placed), default=chunk_s)
        cursor += max(span, chunk_s)
        timeline = [n for n in timeline if n.start_s >= cursor - history_s - 1.0]


def _rebase(notes):
    if not notes:
        return []
    t0 = min(n.start_s for n in notes)
    return [NoteRecord(n.pitch, n.velocity, max(0.0, n.start_s - t0), n.end_s - t0, n.channel)
            for n in notes]


def _play(buffer, ports, sounding, stop) -> None:
    while not stop.is_set():
        for _wall, _seq, kind, pitch, vel in buffer.pop_due(time.perf_counter()):
            if kind == 1:
                ports.send([NOTE_ON, pitch, vel]); sounding.add(pitch)
            else:
                ports.send([NOTE_OFF, pitch, 0]); sounding.discard(pitch)
        time.sleep(0.004)


def panic(ports, sounding) -> None:
    for pitch in list(sounding):
        ports.send([NOTE_OFF, pitch, 0])
    sounding.clear()
    ports.all_notes_off()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-backing",
                                description="Dynamic AI-generated backing track (AMT) - solo over it.")
    p.add_argument("--key", default="C:major")
    p.add_argument("--bpm", type=float, default=100.0, help="tempo of the seed/cover chords")
    p.add_argument("--style", default="pulse", choices=["pads", "pulse", "arp"])
    p.add_argument("--progression", default="1,5,6,4")
    p.add_argument("--tonic-octave", type=int, default=3)
    p.add_argument("--register-cap", type=int, default=72, help="snap AMT notes at/below this MIDI pitch (72=C5)")
    p.add_argument("--backing-vel", type=float, default=0.8, help="velocity scale so backing sits under the solo")
    p.add_argument("--chunk-secs", type=float, default=6.0, help="seconds of music generated per AMT call")
    p.add_argument("--history-secs", type=float, default=8.0, help="seconds of recent output fed back to the model")
    p.add_argument("--lookahead-secs", type=float, default=14.0, help="how far ahead of the playhead to buffer")
    p.add_argument("--seed-cycles", type=int, default=2, help="rule-based intro cycles while the model warms up")
    # default cpu: MPS is fast when warm but has a ~30s+ first-call Metal compile every run,
    # which is bad for a backing track's startup; cpu is slower but predictable. Use mps/cuda
    # if you do not mind the one-time warmup (or warm it up first).
    p.add_argument("--amt-device", default="cpu", choices=["auto", "cpu", "cuda", "mps"])
    p.add_argument("--amt-top-p", type=float, default=0.98)
    p.add_argument("--port-out-name", default="Agent Out")
    p.add_argument("--port-in-name", default="Agent In")
    return p


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    a = build_parser().parse_args(argv)
    ctx = make_context(a.key)
    progression = [int(x) for x in a.progression.split(",") if x.strip()]
    tonic_pitch = 12 * (a.tonic_octave + 1) + ctx.root

    # Try the model; on missing deps / load failure, run rule-based covers only (still musical).
    stream = None
    try:
        from amt_engine import AmtStream
        stream = AmtStream(Config(amt_device=a.amt_device, amt_top_p=a.amt_top_p))
        log.info("AMT model loaded - the backing will evolve.")
    except Exception as exc:  # noqa: BLE001
        log.warning("AMT unavailable (%s); using the rule-based progression instead "
                    "(install requirements-model.txt for the AI version).", exc)

    ports = Ports.open(Config(port_out_name=a.port_out_name, port_in_name=a.port_in_name))
    sounding: set[int] = set()
    stop = threading.Event()
    cleaned = threading.Event()

    def cleanup() -> None:
        if cleaned.is_set():
            return
        cleaned.set()
        stop.set()
        try:
            panic(ports, sounding)
        finally:
            ports.close()
        log.info("stopped")

    def on_signal(_s, _f):
        cleanup()
        raise SystemExit(0)

    atexit.register(cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass

    # Schedule the instant in-key seed now; it also becomes the model's initial history.
    wall_base = time.perf_counter()
    seed, seed_len = seed_notes(ctx, tonic_pitch, progression, style=a.style, bpm=a.bpm,
                                cycles=a.seed_cycles)
    seed_sched, seed_timeline = place_chunk(seed, 0.0, wall_base, ctx,
                                            register_cap=a.register_cap, vel_scale=a.backing_vel)
    buffer = TimedBuffer()
    for wall_on, wall_off, pitch, vel in seed_sched:
        buffer.push(wall_on, wall_off, pitch, vel)

    gen = threading.Thread(target=_generate_loop, name="ai-backing-gen", daemon=True, kwargs=dict(
        stream=stream, buffer=buffer, ctx=ctx, tonic_pitch=tonic_pitch, progression=progression,
        wall_base=wall_base, stop=stop, chunk_s=a.chunk_secs, history_s=a.history_secs,
        lookahead_s=a.lookahead_secs, register_cap=a.register_cap, vel_scale=a.backing_vel,
        style=a.style, bpm=a.bpm, seed_timeline=seed_timeline))
    gen.start()

    log.info("AI backing on %r: key=%s @ %g bpm, register<=%d. Plays a chord intro, then the "
             "model evolves it. Solo over it. Ctrl-C to stop.", a.port_out_name, a.key, a.bpm, a.register_cap)
    try:
        _play(buffer, ports, sounding, stop)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
