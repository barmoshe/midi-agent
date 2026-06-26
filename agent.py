"""agent.py - the turn-taking state machine, wiring, CLI, and guaranteed cleanup.

LISTEN -> HANDOVER -> RESPOND -> LISTEN. The rtmidi callback (native thread) only stamps
time + updates the buffer and, during RESPOND, flags a real (non-echo) human reclaim. The
poll thread owns silence handover. The main thread runs the machine and the scheduler.
Cleanup (explicit note_offs + CC123 on all channels, then close ports) is guaranteed on any
exit via atexit + SIGINT/SIGTERM + try/finally. See design.md 2.1, 3, 5.2.
"""
from __future__ import annotations

import atexit
import logging
import signal
import threading
import time

from capture import PhraseBuffer
from config import Config, parse_args
from handover import HandoverDetector, PollLoop
from ports import CC, Ports, parse_midi
from responder import build_responder
from scheduler import Scheduler
from theory import build_context

log = logging.getLogger("midi_agent")

LISTEN, HANDOVER, RESPOND = "LISTEN", "HANDOVER", "RESPOND"


def panic_cleanup(send, sounding) -> None:
    """Silence everything: explicit note_offs for every tracked sounding note, then CC123
    (all-notes-off) on all 16 channels (some synths ignore CC123, hence the explicit offs)."""
    for (pitch, channel) in list(sounding):
        send([0x80 | channel, pitch, 0])
    sounding.clear()
    for ch in range(16):
        send([CC | ch, 123, 0])


class Agent:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.buffer = PhraseBuffer()
        self.detector = HandoverDetector(config, self.buffer)
        self.responder = build_responder(config)
        self.ports: Ports | None = None
        self.scheduler: Scheduler | None = None
        self.poll: PollLoop | None = None
        self.state = LISTEN
        self._reclaim = threading.Event()
        self._prev_context = None
        self._cleaned = False

    # --- callback (native rtmidi thread): light work only ---
    def on_midi(self, event, data=None) -> None:
        message, _delta = event
        ev = parse_midi(list(message))
        if ev is None:
            return
        now = time.perf_counter()
        if ev["type"] == "note_on":
            self.buffer.note_on(ev["pitch"], ev["velocity"], ev["channel"], now)
            self._maybe_reclaim(ev, now)
        elif ev["type"] == "note_off":
            self.buffer.note_off(ev["pitch"], ev["channel"], now)
        elif ev["type"] == "control_change":
            self.buffer.touch(now)
            self.detector.on_control_change(ev["control"], ev["value"])
            if self.state == RESPOND and ev["control"] == self.cfg.trigger_cc and ev["value"] >= 64:
                self._reclaim.set()

    def _maybe_reclaim(self, ev, now) -> None:
        # During RESPOND, a human note that is NOT the DAW's thru of our own output = reclaim.
        if self.state == RESPOND and self.scheduler is not None:
            if not self.scheduler.is_echo(ev["pitch"], ev["channel"], now):
                self._reclaim.set()

    # --- main thread: the machine ---
    def _handover(self, reason: str) -> None:
        self.state = HANDOVER
        log.info("handover (%s)", reason)
        phrase = self.buffer.snapshot(time.perf_counter())
        self.buffer.reset()
        self.detector.reset()
        if not phrase:
            self.state = LISTEN
            return
        context = build_context(phrase, prev=self._prev_context, key_lock=self.cfg.key_lock,
                                key_floor=self.cfg.key_floor, tempo_floor=self.cfg.tempo_floor)
        self._prev_context = context
        response = self.responder.respond(phrase, context)

        self.state = RESPOND
        self._reclaim.clear()
        self.scheduler.play(response, reclaim=self._reclaim.is_set)
        self.state = LISTEN

    def run(self) -> None:
        self.ports = Ports.open(self.cfg)
        self.scheduler = Scheduler(self.ports.send, echo_window_ms=self.cfg.echo_window_ms)
        self.ports.set_callback(self.on_midi)
        self.poll = PollLoop(self.detector, self._handover, poll_ms=self.cfg.poll_ms)

        self._install_signal_handlers()
        atexit.register(self.cleanup)
        log.info("Live MIDI Agent running. Play into %r; reply on %r. Ctrl-C to stop.",
                 self.cfg.port_in_name, self.cfg.port_out_name)
        try:
            self.poll.start()
            while True:
                time.sleep(0.1)
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            if self.poll is not None:
                self.poll.stop()
            if self.scheduler is not None:
                self.scheduler.all_notes_off()
        finally:
            if self.ports is not None:
                self.ports.close()
        log.info("clean shutdown")

    def _install_signal_handlers(self) -> None:
        def handler(signum, _frame):
            log.info("signal %s; shutting down", signum)
            self.cleanup()
            raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # not on the main thread, e.g. under a test runner
                pass


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    Agent(parse_args(argv)).run()


if __name__ == "__main__":
    main()
