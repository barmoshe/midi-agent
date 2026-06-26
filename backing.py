"""backing.py - a continuous, evolving backing-track generator you solo over.

Streams a musical, in-key accompaniment to the Agent Out virtual MIDI port. By default it is
DYNAMIC: it walks through a bank of chord progressions, adds occasional 7th-chord color, plays
a walking bass that approaches the next chord, and humanizes velocity, so it keeps evolving
while always sounding like real accompaniment. It only plays (never listens), so there is no
input routing and no feedback. `--static` loops a single progression instead. Ctrl-C to stop.

This is a music-theory arranger, not a neural model: a raw symbolic-music model produces
aimless output for a backing track, so the good-sounding rule-based engine is the one we make
dynamic. The pure logic (build_triad / arrange_section / timeline_for_cycle) is unit-tested;
play_timeline is the thin real-time player.
"""
from __future__ import annotations

import argparse
import atexit
import logging
import random
import signal
import threading
import time

from config import Config
from ports import NOTE_OFF, NOTE_ON, Ports
from theory import MusicalContext, _scale_for, parse_key_lock

log = logging.getLogger("midi_agent.backing")

BEATS_PER_BAR = 4

# A bank of strong diatonic progressions (scale degrees, 1 = tonic). The dynamic arranger
# walks through these so the harmony evolves while staying coherent.
PROGRESSIONS = [
    [1, 5, 6, 4], [6, 4, 1, 5], [1, 4, 6, 5], [1, 6, 4, 5],
    [1, 4, 5, 5], [2, 5, 1, 6], [6, 5, 4, 5], [1, 5, 4, 4],
]


def make_context(key: str) -> MusicalContext:
    """A full-confidence MusicalContext pinned to `key` (e.g. 'C:major', 'A:minor')."""
    root, mode = parse_key_lock(key)
    return MusicalContext(root=root, mode=mode, key_confidence=1.0,
                          ioi=None, tempo_confidence=0.0, scale=_scale_for(root, mode))


def build_triad(ctx: MusicalContext, tonic_pitch: int, degree: int) -> list[int]:
    """Diatonic triad on the given scale degree (1 = tonic). Stacks two diatonic thirds, so the
    chord quality (major / minor / diminished) follows the key automatically."""
    root = ctx.degree_transpose(tonic_pitch, degree - 1)
    return [root, ctx.degree_transpose(root, 2), ctx.degree_transpose(root, 4)]


def _clampv(v) -> int:
    return max(1, min(127, int(v)))


def cycle_events(ctx, tonic_pitch, progression, *, style="pulse", bars_per_chord=1,
                 chord_vel=70, bass_vel=86) -> tuple[list, float]:
    """One progression cycle as (events, cycle_beats); each event is (onset_beat, dur_beats,
    pitch, velocity). The STATIC backing (and seed for ai_backing). Pure - no I/O."""
    events = []
    beat = 0.0
    for degree in progression:
        triad = build_triad(ctx, tonic_pitch, degree)
        bass = max(0, triad[0] - 12)
        span = bars_per_chord * BEATS_PER_BAR
        if style == "pads":
            for p in triad:
                events.append((beat, span, p, chord_vel))
            events.append((beat, span, bass, bass_vel))
        elif style == "arp":
            arp = [triad[0], triad[1], triad[2], triad[1]]
            for b in range(int(span)):
                events.append((beat + b, 0.9, arp[b % len(arp)], chord_vel))
            events.append((beat, span, bass, bass_vel))
        else:  # "pulse"
            for b in range(int(span)):
                for p in triad:
                    events.append((beat + b, 0.9, p, chord_vel))
                if b % 2 == 0:
                    events.append((beat + b, 1.9, bass, bass_vel))
        beat += span
    return events, beat


def arrange_section(ctx, tonic_pitch, progression, *, style="pulse", rng=None, vel=74) -> tuple[list, float]:
    """One evolving section (4 beats per chord) as (events, section_beats). Adds, on top of the
    plain triad groove: an occasional whole-section 7th color, accented/humanized velocities, and
    a walking bass that steps toward the next chord's root. Pure and deterministic given `rng`."""
    rng = rng or random.Random(0)
    use_seventh = rng.random() < 0.4  # color this whole section or not
    events = []
    beat = 0.0
    n = len(progression)
    for i, degree in enumerate(progression):
        triad = build_triad(ctx, tonic_pitch, degree)
        chord = list(triad)
        if use_seventh:
            chord.append(ctx.degree_transpose(triad[0], 6))  # diatonic 7th
        bass = max(0, triad[0] - 12)
        next_bass = max(0, build_triad(ctx, tonic_pitch, progression[(i + 1) % n])[0] - 12)
        approach = ctx.degree_transpose(next_bass, -1)  # a diatonic step below the next root

        if style == "pads":
            for p in chord:
                events.append((beat, 4.0, p, _clampv(vel)))
        elif style == "arp":
            seq = [chord[k % len(chord)] for k in range(4)]
            for b in range(4):
                events.append((beat + b, 0.9, seq[b], _clampv(vel + rng.randint(-3, 3))))
        else:  # "pulse": chord on each beat, accent the downbeat, humanize
            for b in range(4):
                accent = 12 if b == 0 else (-7 if b % 2 else 0)
                for p in chord:
                    events.append((beat + b, 0.9, p, _clampv(vel + accent + rng.randint(-3, 3))))

        # walking bass: root on 1 and 3, then step toward the next chord on beat 4
        events.append((beat, 1.9, bass, _clampv(vel + 12)))
        events.append((beat + 2, 0.9, bass, _clampv(vel + 4)))
        events.append((beat + 3, 0.9, approach, _clampv(vel + 2)))
        beat += BEATS_PER_BAR
    return events, beat


def pick_next_progression(rng, current):
    """A different progression than `current`, for section-to-section evolution."""
    choices = [p for p in PROGRESSIONS if p != current] or PROGRESSIONS
    return rng.choice(choices)


def timeline_for_cycle(events, cstart: float, spb: float) -> list[tuple[float, int, int, int]]:
    """Expand events into a time-sorted list of (abs_time, kind, pitch, vel); kind 1 = note_on,
    0 = note_off (off sorts before on at a tie so held notes re-strike cleanly). spb = sec/beat."""
    tl = []
    for onset, dur, pitch, vel in events:
        tl.append((cstart + onset * spb, 1, pitch, vel))
        tl.append((cstart + (onset + dur) * spb, 0, pitch, 0))
    tl.sort(key=lambda e: (e[0], e[1]))
    return tl


def play_timeline(ports, timeline, sounding, stop, *, now=time.perf_counter, sleep=time.sleep) -> None:
    """Play one section's absolute-time timeline, then return (the caller schedules the next
    section contiguously off a fixed base, so timing never drifts)."""
    for t, kind, pitch, vel in timeline:
        while not stop.is_set():
            dt = t - now()
            if dt <= 0:
                break
            sleep(min(dt, 0.05))
        if stop.is_set():
            return
        if kind == 1:
            ports.send([NOTE_ON, pitch, vel]); sounding.add(pitch)
        else:
            ports.send([NOTE_OFF, pitch, 0]); sounding.discard(pitch)


def panic(ports, sounding) -> None:
    """Silence everything: explicit note_offs for tracked notes, then CC123 on all channels."""
    for pitch in list(sounding):
        ports.send([NOTE_OFF, pitch, 0])
    sounding.clear()
    ports.all_notes_off()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backing",
                                description="Evolving auto backing-track generator - solo over it.")
    p.add_argument("--key", default="C:major", help='key, e.g. "C:major" or "A:minor"')
    p.add_argument("--bpm", type=float, default=100.0, help="tempo in beats per minute")
    p.add_argument("--style", default="pulse", choices=["pads", "pulse", "arp"], help="backing feel")
    p.add_argument("--progression", default="1,5,6,4",
                   help="starting progression (scale degrees); also the fixed loop under --static")
    p.add_argument("--static", action="store_true", help="loop one progression instead of evolving")
    p.add_argument("--seed", type=int, default=0, help="varies the evolution / humanization")
    p.add_argument("--vel", type=int, default=74, help="base velocity")
    p.add_argument("--tonic-octave", type=int, default=3, help="octave of the chord tonic (3 ~ below middle C)")
    p.add_argument("--port-out-name", default="Agent Out")
    p.add_argument("--port-in-name", default="Agent In")
    return p


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    a = build_parser().parse_args(argv)
    ctx = make_context(a.key)
    prog = [int(x) for x in a.progression.split(",") if x.strip()]
    tonic_pitch = 12 * (a.tonic_octave + 1) + ctx.root  # MIDI: C4 = 60
    spb = 60.0 / a.bpm
    rng = random.Random(a.seed)

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

    mode = "static loop" if a.static else "evolving"
    log.info("Backing track on %r: key=%s %s @ %g bpm (%s). Solo over it. Ctrl-C to stop.",
             a.port_out_name, a.key, a.style, a.bpm, mode)
    base = time.perf_counter()
    offset = 0.0
    try:
        while not stop.is_set():
            if a.static:
                events, sec_beats = cycle_events(ctx, tonic_pitch, prog, style=a.style, chord_vel=a.vel)
            else:
                events, sec_beats = arrange_section(ctx, tonic_pitch, prog, style=a.style, rng=rng, vel=a.vel)
            play_timeline(ports, timeline_for_cycle(events, base + offset, spb), sounding, stop)
            offset += sec_beats * spb
            if not a.static:
                prog = pick_next_progression(rng, prog)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
