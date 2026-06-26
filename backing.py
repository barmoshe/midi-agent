"""backing.py - a continuous auto-accompaniment / backing-track generator.

Streams a looping, in-key chord + bass groove to the Agent Out virtual MIDI port so you can
solo over it in your DAW. Unlike agent.py (turn-taking call-and-response), this does NOT
listen or react - it just lays down a steady backing track in a key / tempo / feel you
choose, so there is no input routing and no feedback to worry about. Ctrl-C to stop.

Reuses ports.py (virtual port + send + cleanup) and theory.py (diatonic chord building). The
musical logic (build_triad / cycle_events / timeline_for_cycle) is pure and unit-tested;
play_loop is the thin real-time player. See README "Backing-track mode".
"""
from __future__ import annotations

import argparse
import atexit
import logging
import signal
import threading
import time

from config import Config
from ports import NOTE_OFF, NOTE_ON, Ports
from theory import MusicalContext, _scale_for, parse_key_lock

log = logging.getLogger("midi_agent.backing")

BEATS_PER_BAR = 4


def make_context(key: str) -> MusicalContext:
    """A full-confidence MusicalContext pinned to `key` (e.g. 'C:major', 'A:minor')."""
    root, mode = parse_key_lock(key)
    return MusicalContext(root=root, mode=mode, key_confidence=1.0,
                          ioi=None, tempo_confidence=0.0, scale=_scale_for(root, mode))


def build_triad(ctx: MusicalContext, tonic_pitch: int, degree: int) -> list[int]:
    """Diatonic triad on the given scale degree (1 = tonic). Stacks two diatonic thirds, so
    the chord quality (major / minor / diminished) follows the key automatically."""
    root = ctx.degree_transpose(tonic_pitch, degree - 1)
    return [root, ctx.degree_transpose(root, 2), ctx.degree_transpose(root, 4)]


def cycle_events(ctx, tonic_pitch, progression, *, style="pulse", bars_per_chord=1,
                 chord_vel=70, bass_vel=86) -> tuple[list, float]:
    """Build ONE progression cycle as (events, cycle_beats), where each event is
    (onset_beat, dur_beats, pitch, velocity). Pure - no I/O. The player loops this against an
    absolute clock. `progression` is a list of scale degrees, e.g. [1, 5, 6, 4] = I-V-vi-IV."""
    events: list[tuple[float, float, int, int]] = []
    beat = 0.0
    for degree in progression:
        triad = build_triad(ctx, tonic_pitch, degree)
        bass = max(0, triad[0] - 12)
        span = bars_per_chord * BEATS_PER_BAR
        if style == "pads":  # sustained chord + bass for the whole chord
            for p in triad:
                events.append((beat, span, p, chord_vel))
            events.append((beat, span, bass, bass_vel))
        elif style == "arp":  # one chord tone per beat over a held bass
            arp = [triad[0], triad[1], triad[2], triad[1]]
            for b in range(int(span)):
                events.append((beat + b, 0.9, arp[b % len(arp)], chord_vel))
            events.append((beat, span, bass, bass_vel))
        else:  # "pulse": chord on every beat, bass on beats 1 and 3
            for b in range(int(span)):
                for p in triad:
                    events.append((beat + b, 0.9, p, chord_vel))
                if b % 2 == 0:
                    events.append((beat + b, 1.9, bass, bass_vel))
        beat += span
    return events, beat


def timeline_for_cycle(events, cstart: float, spb: float) -> list[tuple[float, int, int, int]]:
    """Expand one cycle's events into a time-sorted list of (abs_time, kind, pitch, vel),
    kind 1 = note_on, 0 = note_off. note_off sorts before note_on at a tie so a held note
    re-strikes cleanly at the loop point instead of hanging. spb = seconds per beat."""
    tl = []
    for onset, dur, pitch, vel in events:
        tl.append((cstart + onset * spb, 1, pitch, vel))
        tl.append((cstart + (onset + dur) * spb, 0, pitch, 0))
    tl.sort(key=lambda e: (e[0], e[1]))
    return tl


def _sleep_until(t, now, sleep, stop) -> None:
    # small increments so Ctrl-C stays responsive even on a slow chord
    while not stop.is_set():
        dt = t - now()
        if dt <= 0:
            return
        sleep(min(dt, 0.05))


def play_loop(ports, events, cycle_beats, spb, *, sounding, stop,
              now=time.perf_counter, sleep=time.sleep) -> None:
    """Loop the cycle forever (until `stop`), scheduling every note to an ABSOLUTE time off a
    fixed base so timing never drifts. `sounding` tracks open pitches for panic cleanup."""
    base = now()
    cycle = 0
    while not stop.is_set():
        cstart = base + cycle * cycle_beats * spb
        for t, kind, pitch, vel in timeline_for_cycle(events, cstart, spb):
            _sleep_until(t, now, sleep, stop)
            if stop.is_set():
                return
            if kind == 1:
                ports.send([NOTE_ON, pitch, vel])
                sounding.add(pitch)
            else:
                ports.send([NOTE_OFF, pitch, 0])
                sounding.discard(pitch)
        cycle += 1


def panic(ports, sounding) -> None:
    """Silence everything: explicit note_offs for tracked notes, then CC123 on all channels."""
    for pitch in list(sounding):
        ports.send([NOTE_OFF, pitch, 0])
    sounding.clear()
    ports.all_notes_off()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backing",
                                description="Continuous auto backing-track generator - solo over it.")
    p.add_argument("--key", default="C:major", help='key, e.g. "C:major" or "A:minor"')
    p.add_argument("--bpm", type=float, default=100.0, help="tempo in beats per minute")
    p.add_argument("--style", default="pulse", choices=["pads", "pulse", "arp"], help="backing feel")
    p.add_argument("--progression", default="1,5,6,4",
                   help="comma-separated scale degrees, e.g. 1,5,6,4 = I-V-vi-IV")
    p.add_argument("--bars-per-chord", type=int, default=1)
    p.add_argument("--chord-vel", type=int, default=70)
    p.add_argument("--bass-vel", type=int, default=86)
    p.add_argument("--tonic-octave", type=int, default=3, help="octave of the chord tonic (3 ~ below middle C)")
    p.add_argument("--port-out-name", default="Agent Out")
    p.add_argument("--port-in-name", default="Agent In")
    return p


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    a = build_parser().parse_args(argv)
    ctx = make_context(a.key)
    progression = [int(x) for x in a.progression.split(",") if x.strip()]
    tonic_pitch = 12 * (a.tonic_octave + 1) + ctx.root  # MIDI: C4 = 60
    events, cycle_beats = cycle_events(ctx, tonic_pitch, progression, style=a.style,
                                       bars_per_chord=a.bars_per_chord,
                                       chord_vel=a.chord_vel, bass_vel=a.bass_vel)
    spb = 60.0 / a.bpm

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

    def on_signal(_signum, _frame):
        cleanup()
        raise SystemExit(0)

    atexit.register(cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, on_signal)
        except (ValueError, OSError):
            pass

    log.info("Backing track on %r: key=%s %s @ %g bpm, progression=%s. Solo over it. Ctrl-C to stop.",
             a.port_out_name, a.key, a.style, a.bpm, progression)
    try:
        play_loop(ports, events, cycle_beats, spb, sounding=sounding, stop=stop)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
