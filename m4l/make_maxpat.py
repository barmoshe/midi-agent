"""make_maxpat.py - generate MidiFollow.maxpat, a complete wired Max for Live device patch.

This is the "agent generates the device as patcher JSON" technique (knowledge/21): emit a valid
.maxpat the user pastes via Max's File -> New From Clipboard, or Open + Copy + paste into a Max
MIDI Effect shell. The graph is the BUILD.md wiring:

  midiin -> midiparse -(note)-> prepend note -> v8 device.js -> midiformat -> midiout
  toggle -> metro 1n -> v8 (bar tick);  message boxes (key/feel/sevenths/tempo/panic) -> v8;
  v8 outlet 1 -> print chord (readout in the Max console).

The v8 object loads device.js (which requires engine.js); both must be on Max's file search
path until you Freeze the device. Run:  ./venv/bin/python m4l/make_maxpat.py
"""
from __future__ import annotations

import json
import os

_boxes = []
_lines = []


def box(bid, text=None, *, x, y, w=140, h=22, cls="newobj", ins=1, outs=1, outtypes=None):
    b = {
        "id": bid, "maxclass": cls, "numinlets": ins, "numoutlets": outs,
        "outlettype": outtypes if outtypes is not None else [""] * outs,
        "patching_rect": [x, y, w, h], "fontsize": 12.0,
    }
    if text is not None:
        b["text"] = text
    _boxes.append({"box": b})
    return bid


def line(src, so, dst, di):
    _lines.append({"patchline": {"source": [src, so], "destination": [dst, di]}})


# --- MIDI signal path ---
midiin = box("obj-1", "midiin", x=40, y=40, w=60, outtypes=["int"])
midiparse = box("obj-2", "midiparse", x=40, y=90, w=80, outs=8, outtypes=[""] * 8)
prep = box("obj-3", "prepend note", x=40, y=140, w=100)
v8 = box("obj-4", "v8 device.js", x=40, y=200, w=120, ins=1, outs=2, outtypes=["", ""])
midifmt = box("obj-5", "midiformat", x=40, y=380, w=90, ins=8, outtypes=["int"])
midiout = box("obj-6", "midiout", x=40, y=430, w=70, outs=0, outtypes=[])

line(midiin, 0, midiparse, 0)
line(midiparse, 0, prep, 0)     # midiparse note outlet (pitch velocity) -> prepend note
line(prep, 0, v8, 0)
line(v8, 0, midifmt, 0)         # v8 outlet 0: [pitch velocity] (vel 0 = off) -> midiformat
line(midifmt, 0, midiout, 0)

# --- transport-synced bar clock ---
tog = box("obj-7", x=320, y=40, w=24, h=24, cls="toggle", ins=1, outs=1, outtypes=["int"])
metro = box("obj-8", "metro 1n", x=320, y=90, w=70, ins=2)
line(tog, 0, metro, 0)
line(metro, 0, v8, 0)           # a bare bang into v8 = a bar tick

# --- control message boxes -> v8 ---
ctrls = [
    ("obj-10", "key C:major"), ("obj-11", "key A:minor"), ("obj-12", "key auto"),
    ("obj-13", "feel pulse"), ("obj-14", "feel pads"),
    ("obj-15", "sevenths 1"), ("obj-16", "sevenths 0"),
    ("obj-17", "tempo 120"), ("obj-18", "panic"),
]
yy = 150
for bid, text in ctrls:
    box(bid, text, x=320, y=yy, w=110, cls="message", ins=2, outs=1)
    line(bid, 0, v8, 0)
    yy += 28

# --- chord readout (prints to the Max console) ---
pr = box("obj-9", "print chord", x=200, y=260, w=90, outs=0, outtypes=[])
line(v8, 1, pr, 0)              # v8 outlet 1: "key <name>" / "chord <name>"

note = box("obj-20",
           "MIDI Follow: toggle the metro ON (top), play a solo into the track, watch the Max "
           "console print the chord. Put an instrument AFTER this device. Freeze to ship.",
           x=320, y=410, w=360, h=60, cls="comment")

patch = {
    "patcher": {
        "fileversion": 1,
        "appversion": {"major": 8, "minor": 5, "revision": 0, "architecture": "x64", "modernui": 1},
        "classnamespace": "box",
        "rect": [80, 80, 760, 520],
        "boxes": _boxes,
        "lines": _lines,
    }
}

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MidiFollow.maxpat")
with open(out_path, "w") as f:
    json.dump(patch, f, indent=2)
print(f"wrote {len(_boxes)} boxes + {len(_lines)} lines -> {out_path}")
