"""theory.py - musical coherence: duration-weighted key estimation, tempo, scale snapping.

MusicalContext is computed from a frozen phrase at handover and consumed by every
responder. Key uses a duration-weighted pitch-class histogram correlated against the
Krumhansl-Schmuckler profiles; both key and tempo carry a confidence floor that falls
back to the last-known context (or a --key lock) rather than answering out of key.
See design.md section 6.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# Krumhansl-Schmuckler key profiles (tonal hierarchy weights).
KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)  # natural minor

_NOTE_NAMES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
               "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def estimate_key(notes) -> tuple[int, str, float]:
    """Return (root_pitch_class, mode, confidence in 0..1). Duration-weighted."""
    hist = [0.0] * 12
    for n in notes:
        hist[n.pitch % 12] += (n.end_s - n.start_s)
    if sum(hist) == 0:
        return (0, "major", 0.0)
    best = None  # (root, mode, corr)
    for root in range(12):
        rot = [hist[(root + i) % 12] for i in range(12)]
        for mode, profile in (("major", KS_MAJOR), ("minor", KS_MINOR)):
            c = _pearson(rot, profile)
            if best is None or c > best[2]:
                best = (root, mode, c)
    root, mode, corr = best
    return (root, mode, max(0.0, corr))


def estimate_tempo(notes) -> tuple[float | None, float]:
    """Return (median inter-onset interval in seconds, confidence). Honest 'smart echo':
    this is a rough pulse, not beat induction. Confidence drops on irregular IOIs."""
    onsets = sorted(n.start_s for n in notes)
    iois = [b - a for a, b in zip(onsets, onsets[1:]) if b - a > 1e-4]
    if len(iois) < 2:
        return (None, 0.0)
    med = median(iois)
    if med <= 0:
        return (None, 0.0)
    # confidence = 1 - normalized mean absolute deviation (regularity)
    mad = sum(abs(x - med) for x in iois) / len(iois)
    conf = max(0.0, 1.0 - mad / med)
    return (med, conf)


@dataclass(frozen=True)
class MusicalContext:
    root: int
    mode: str
    key_confidence: float
    ioi: float | None
    tempo_confidence: float
    scale: frozenset  # pitch classes in the key

    def in_key(self, pitch: int) -> bool:
        return pitch % 12 in self.scale

    def snap(self, pitch: int) -> int:
        """Nearest in-key pitch (search outward), clamped 0..127."""
        if pitch % 12 in self.scale:
            return _clamp(pitch)
        for d in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6):
            if (pitch + d) % 12 in self.scale:
                return _clamp(pitch + d)
        return _clamp(pitch)

    def degree_transpose(self, pitch: int, steps: int) -> int:
        """Move `steps` scale-degrees up (+) or down (-) from the nearest in-key pitch.
        A diatonic third = 2 steps."""
        cur = self.snap(pitch)
        if steps == 0:
            return cur
        direction = 1 if steps > 0 else -1
        remaining = abs(steps)
        while remaining > 0:
            cur += direction
            guard = 0
            while cur % 12 not in self.scale and 0 <= cur <= 127 and guard < 12:
                cur += direction
                guard += 1
            remaining -= 1
            if not 0 <= cur <= 127:
                break
        return _clamp(cur)


def _clamp(pitch: int) -> int:
    return max(0, min(127, pitch))


def _scale_for(root: int, mode: str) -> frozenset:
    steps = MAJOR_STEPS if mode == "major" else MINOR_STEPS
    return frozenset((root + s) % 12 for s in steps)


def parse_key_lock(spec: str) -> tuple[int, str]:
    """Parse 'C:major' / 'A:minor' / 'F#:major' -> (root_pc, mode)."""
    name, _, mode = spec.partition(":")
    root = _NOTE_NAMES.get(name.strip().upper())
    if root is None:
        raise ValueError(f"unknown key root: {name}")
    mode = (mode.strip().lower() or "major")
    if mode not in ("major", "minor"):
        raise ValueError(f"unknown mode: {mode}")
    return root, mode


def build_context(notes, prev: "MusicalContext | None" = None,
                  key_lock: str | None = None,
                  key_floor: float = 0.5, tempo_floor: float = 0.4) -> MusicalContext:
    """Build the context, applying the confidence-floor fallbacks (design 6)."""
    root, mode, kconf = estimate_key(notes)
    if key_lock:
        root, mode = parse_key_lock(key_lock)
        kconf = 1.0
    elif kconf < key_floor and prev is not None:
        root, mode, kconf = prev.root, prev.mode, prev.key_confidence

    ioi, tconf = estimate_tempo(notes)
    if tconf < tempo_floor and prev is not None and prev.ioi is not None:
        ioi = prev.ioi

    return MusicalContext(root=root, mode=mode, key_confidence=kconf,
                          ioi=ioi, tempo_confidence=tconf, scale=_scale_for(root, mode))
