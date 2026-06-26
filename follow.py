"""follow.py - an AI accompanist that navigates the chord changes by listening to your solo.

You play a solo into Agent In; this analyzes which pitches you are emphasizing (recency- and
duration-weighted), scores every diatonic chord for how well it fits, adds a voice-leading
smoothness bias so the changes flow, and plays the best-matching chord (+ bass + groove) on
Agent Out. So the harmony FOLLOWS your playing, bar by bar, instead of looping a fixed
progression. The key is pinned with --key, or auto-detected from your first few seconds.

It listens AND plays, so route your solo to Agent In and an instrument to Agent Out (see the
README), and keep them separate. An echo-guard ignores its own comp notes bouncing back, so a
stray thru does not make it chase itself. Ctrl-C to stop.

The harmony logic (pitch_histogram / score_chord / best_degree) is pure and unit-tested; the
callback + clock are the real-time layer.
"""
from __future__ import annotations

import argparse
import atexit
import logging
import random
import signal
import threading
import time
from collections import defaultdict

from backing import build_triad, make_context, timeline_for_cycle, _clampv
from capture import NoteRecord
from config import Config
from ports import NOTE_OFF, NOTE_ON, Ports, parse_midi
from theory import estimate_key, parse_key_lock

log = logging.getLogger("midi_agent.follow")

BEATS_PER_BAR = 4


# --------------------------------------------------------------------------- #
# Pure harmony logic (unit-tested)                                            #
# --------------------------------------------------------------------------- #
def pitch_histogram(notes, now: float, *, window_s: float = 2.5, halflife: float = 1.2) -> dict:
    """Recency-weighted pitch-class histogram of recent (pitch, t) onsets. Newer notes count
    more (exponential decay); notes older than window_s are ignored."""
    hist: dict = defaultdict(float)
    for pitch, t in notes:
        age = now - t
        if age > window_s or age < 0:
            continue
        hist[pitch % 12] += 0.5 ** (age / halflife)
    return dict(hist)


def score_chord(hist: dict, chord_pcs: frozenset, root_pc: int, *, out_penalty: float = 0.5) -> float:
    """How well a chord fits the played pitches: root tones count most, other chord tones less,
    out-of-chord notes subtract."""
    s = 0.0
    for pc, w in hist.items():
        if pc == root_pc:
            s += w
        elif pc in chord_pcs:
            s += 0.8 * w
        else:
            s -= out_penalty * w
    return s


def best_degree(ctx, tonic_pitch: int, hist: dict, current_degree: int, *,
                hold_bonus: float = 0.2, switch_margin: float = 0.15) -> int:
    """Pick the diatonic scale degree (1..7) whose triad best fits `hist`, biased to hold the
    current chord (hysteresis) so it does not flip-flop. Only switches if a different chord wins
    by more than switch_margin."""
    scores = {}
    for d in range(1, 8):
        triad = build_triad(ctx, tonic_pitch, d)
        pcs = frozenset(p % 12 for p in triad)
        scores[d] = score_chord(hist, pcs, triad[0] % 12)
    if current_degree in scores:
        scores[current_degree] += hold_bonus
    best = max(scores, key=lambda d: scores[d])
    if current_degree and best != current_degree:
        if scores[best] - scores.get(current_degree, float("-inf")) < switch_margin:
            return current_degree
    return best


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def chord_name(ctx, tonic_pitch, degree, *, seventh=False) -> str:
    """A readable name for the chord on a scale degree, e.g. 'C', 'Am', 'G7'."""
    triad = build_triad(ctx, tonic_pitch, degree)
    root, third, fifth = triad[0], triad[1], triad[2]
    third_iv = (third - root) % 12
    fifth_iv = (fifth - root) % 12
    if third_iv == 4 and fifth_iv == 8:
        quality = "aug"
    elif third_iv == 3 and fifth_iv == 6:
        quality = "dim"
    elif third_iv == 3:
        quality = "m"
    else:
        quality = ""  # major (or close enough)
    name = _NOTE_NAMES[root % 12] + quality
    return name + ("7" if seventh else "")


def chord_bar_events(ctx, tonic_pitch, degree, *, style, vel, rng, beats=BEATS_PER_BAR,
                     seventh=False) -> list:
    """One bar of comp for a chosen chord as (onset_beat, dur, pitch, vel). Reuses build_triad."""
    triad = build_triad(ctx, tonic_pitch, degree)
    chord = list(triad) + ([ctx.degree_transpose(triad[0], 6)] if seventh else [])
    bass = max(0, triad[0] - 12)
    events = []
    if style == "pads":
        for p in chord:
            events.append((0.0, float(beats), p, _clampv(vel)))
        events.append((0.0, float(beats), bass, _clampv(vel + 10)))
    else:  # pulse
        for b in range(beats):
            accent = 12 if b == 0 else (-7 if b % 2 else 0)
            for p in chord:
                events.append((float(b), 0.9, p, _clampv(vel + accent + rng.randint(-3, 3))))
            if b % 2 == 0:
                events.append((float(b), 1.9, bass, _clampv(vel + 10)))
    return events


# --------------------------------------------------------------------------- #
# Real-time accompanist                                                        #
# --------------------------------------------------------------------------- #
class RollingNotes:
    """Thread-safe rolling buffer of recent (pitch, onset_time) the soloist played."""

    def __init__(self, keep_s: float = 8.0) -> None:
        self.keep_s = keep_s
        self._lock = threading.Lock()
        self._notes: list = []

    def add(self, pitch: int, t: float) -> None:
        with self._lock:
            self._notes.append((pitch, t))

    def recent(self, now: float, window_s: float) -> list:
        with self._lock:
            self._notes = [n for n in self._notes if now - n[1] <= self.keep_s]
            return [n for n in self._notes if now - n[1] <= window_s]


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="follow",
                                description="AI accompanist that follows your solo's harmony.")
    p.add_argument("--key", default=None, help='pin the key, e.g. "C:major"; omit to auto-detect')
    p.add_argument("--bpm", type=float, default=100.0)
    p.add_argument("--style", default="pulse", choices=["pads", "pulse"])
    p.add_argument("--chord-beats", type=int, default=4, help="beats per chord (2 = follows faster)")
    p.add_argument("--window-s", type=float, default=2.5, help="how much recent playing drives the chord")
    p.add_argument("--seventh", action="store_true", help="use 7th chords")
    p.add_argument("--vel", type=int, default=74)
    p.add_argument("--tonic-octave", type=int, default=3)
    p.add_argument("--port-out-name", default="Agent Out")
    p.add_argument("--port-in-name", default="Agent In")
    a = p.parse_args(argv)

    key_locked = a.key is not None
    root, mode = parse_key_lock(a.key) if key_locked else (0, "major")
    ctx = make_context(f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][root]}:{mode}")
    tonic_pitch = 12 * (a.tonic_octave + 1) + ctx.root

    rolling = RollingNotes()
    sent_recent: dict = {}
    spb = 60.0 / a.bpm
    rng = random.Random(0)

    def on_midi(event, _data=None):
        msg, _delta = event
        ev = parse_midi(list(msg))
        if ev is None or ev["type"] != "note_on":
            return
        now = time.perf_counter()
        last = sent_recent.get(ev["pitch"])
        if last is not None and now - last < 0.15:  # echo-guard: ignore our own comp bouncing back
            return
        rolling.add(ev["pitch"], now)

    ports = Ports.open(Config(port_out_name=a.port_out_name, port_in_name=a.port_in_name))
    ports.set_callback(on_midi)
    sounding: set[int] = set()
    stop = threading.Event()
    cleaned = threading.Event()

    def cleanup():
        if cleaned.is_set():
            return
        cleaned.set()
        stop.set()
        try:
            for pitch in list(sounding):
                ports.send([NOTE_OFF, pitch, 0])
            ports.all_notes_off()
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

    log.info("Following your solo on %r -> comping on %r: key=%s @ %g bpm. Play a solo into "
             "Agent In; the chords follow you. Ctrl-C to stop.",
             a.port_in_name, a.port_out_name, a.key or "auto", a.bpm)

    base = time.perf_counter()
    bar = 0
    degree = 1
    nonlocal_state = {"locked": key_locked, "tonic": tonic_pitch, "ctx": ctx}
    try:
        while not stop.is_set():
            now = time.perf_counter()
            # auto-detect the key once, from the first few seconds of playing
            if not nonlocal_state["locked"]:
                recent = rolling.recent(now, window_s=6.0)
                if len(recent) >= 8:
                    notes = [NoteRecord(pc, 80, t, t + 0.3) for pc, t in recent]
                    r, m, conf = estimate_key(notes)
                    if conf >= 0.6:
                        nctx = make_context(f"{['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'][r]}:{m}")
                        nonlocal_state["ctx"] = nctx
                        nonlocal_state["tonic"] = 12 * (a.tonic_octave + 1) + nctx.root
                        nonlocal_state["locked"] = True
                        log.info("detected key: %s", f"{r}:{m}")
            cctx, ctonic = nonlocal_state["ctx"], nonlocal_state["tonic"]

            hist = pitch_histogram(rolling.recent(now, window_s=a.window_s + 0.5), now,
                                   window_s=a.window_s)
            prev_degree = degree
            if hist:
                degree = best_degree(cctx, ctonic, hist, degree)
            if degree != prev_degree or bar == 0:
                log.info("chord: %s", chord_name(cctx, ctonic, degree, seventh=a.seventh))
            events = chord_bar_events(cctx, ctonic, degree, style=a.style, vel=a.vel, rng=rng,
                                      beats=a.chord_beats, seventh=a.seventh)
            bar_start = base + bar * a.chord_beats * spb
            for t, kind, pitch, vel in timeline_for_cycle(events, bar_start, spb):
                while not stop.is_set():
                    dt = t - time.perf_counter()
                    if dt <= 0:
                        break
                    time.sleep(min(dt, 0.04))
                if stop.is_set():
                    break
                if kind == 1:
                    ports.send([NOTE_ON, pitch, vel]); sounding.add(pitch); sent_recent[pitch] = time.perf_counter()
                else:
                    ports.send([NOTE_OFF, pitch, 0]); sounding.discard(pitch)
            bar += 1
    finally:
        cleanup()


if __name__ == "__main__":
    main()
