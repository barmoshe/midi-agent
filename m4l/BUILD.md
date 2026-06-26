# BUILD.md - assembling the MIDI Follow `.amxd` in Max

This is the on-your-machine half: turn `engine.js` + `device.js` into a Max for Live device and
test it in Ableton. The harmony is already done and proven (see README); here you build the Max
patch around it. Requires **Ableton Live Suite** or the **Max for Live** add-on.

Work in order. Do **Step 2 (the M1 gate) before wiring any logic** - it validates the one Ableton
fact the whole plan rests on.

---

## Step 0 - make Max find the JS files

`device.js` does `require('engine.js')`, so Max must see both files.

- Keep `engine.js` and `device.js` together in this `m4l/` folder.
- In Max (open it from any Max for Live device's Edit button): **Options -> File Preferences ->
  add this `m4l/` folder to the search path**. (Later, "Freeze Device" embeds both files into the
  `.amxd`, so the search-path step is only needed during development.)

## Fast path - paste the prebuilt device (recommended)

A complete wired patch ships as `MidiFollow.maxpat`. Instead of placing objects by hand (Steps
1-4), paste it:

1. Copy it to the clipboard:  `pbcopy < ~/midi-agent/m4l/MidiFollow.maxpat`
2. In Live, drop a **Max MIDI Effect** on a MIDI track and click **Edit** to open the Max editor.
3. In Max: **Edit -> Select All** then **Delete** (clear the default `midiin -> midiout`), then
   **Edit -> Paste** (Cmd-V). The whole device appears wired: `midiin -> midiparse -> prepend note
   -> v8 device.js -> midiformat -> midiout`, a `toggle -> metro 1n` bar clock, control message
   boxes (key / feel / 7ths / tempo / panic), and `print chord` for the readout.
4. Put an instrument after the device on the track. Click the **toggle** on (and/or press Live
   play). Play a solo - the chords follow you, and the Max window prints the chord it is playing.
5. **Freeze** (snowflake) and Save As `MidiFollow.amxd` to your User Library.

If the chord never changes, open the Max window (the console): if you see no `chord ...` prints,
the note input is not reaching the v8 (re-check the `midiparse` -> `prepend note` wire); if you see
prints but hear nothing, re-check `midiformat -> midiout` and that an instrument is after the
device. The manual steps below explain each piece.

## Step 1 - create the device

In Ableton, on a **MIDI track**, open the **Max for Live** category in the browser and drag **"Max
MIDI Effect"** onto the track. Click the device's **Edit** (pencil) button to open the Max editor.
A new MIDI-effect patch opens with `[midiin]` at the top and `[midiout]` at the bottom.

## Step 2 - THE M1 GATE: prove inline routing (do this first)

Before any logic, confirm a M4L MIDI effect can drive an instrument on the **same** track:

1. Leave `[midiin] -> [midiout]` connected (pure pass-through).
2. Add an instrument **after** this device on the same track (e.g. drag in a piano).
3. Play your controller into the track - you should hear the piano. Pass-through works.
4. Now prove **generation**: add a `[button]` and `[makenote 100 200] -> [midiout]`. Click the
   button - the piano should sound a note with **no input**. That confirms the device can generate
   notes inline into the downstream instrument on the same track.

If both work, the form factor is validated. Delete the test `button`/`makenote`. If they do not,
stop and tell me - everything else depends on this.

## Step 3 - wire the engine (the live comp)

Build this graph (object boxes in `[ ]`):

```
[midiin] -> [midiparse]
                 |  (note outlet: a 2-int "pitch velocity" list)
                 v
            [prepend note] -> [v8 device.js]   (inlet 0)
                                   |  outlet 0: "pitch velocity" (vel 0 = note off)
                                   |  outlet 1: "key <name>" / "chord <name>"
   (bar clock) ------------------> | (inlet 0, as a bang)
                                   v
                              [midiformat] -> [midiout]
```

- **Note in:** `[midiin] -> [midiparse]`; from `midiparse`'s **note** outlet -> `[prepend note]`
  -> left inlet of `[v8 device.js]`. (So the device receives `note <pitch> <velocity>`.)
- **MIDI out:** `[v8 device.js]` **outlet 0** -> `[midiformat]` -> `[midiout]`. The device emits
  `<pitch> <velocity>` lists (velocity 0 = note off); `midiformat` turns them into MIDI.
- **Bar clock (transport-synced):** add `[metro 1n]` (interval `1n` = one bar at 4/4). Open its
  inspector and set **Quantization = 1 bar** so it locks to Live's grid. Start it with a
  `[live.transport]` play state or a `[toggle]` you switch on. Its bang -> left inlet of
  `[v8 device.js]` (the device treats a bare `bang` as a bar tick). Match the metro interval to the
  Chord-rate control: `1n` for rate 1, `2n`... use `2 bars` for rate 2.
- **Tempo:** so within-bar note spacing matches the song, send the BPM to the device. Add
  `[live.observer]` watching the song **tempo** (path `live_set`, property `tempo`) ->
  `[prepend tempo]` -> `[v8 device.js]`. (Quick alternative while testing: a message box
  `tempo 120`.)

## Step 4 - UI controls + chord readout

Add these and route each into `[v8 device.js]` inlet 0 via a `[prepend <name>]`:

| Control | Object | Message to device |
|---|---|---|
| Key | `[live.menu]` items: `auto`, `C:major`, `A:minor`, `G:major`, ... | `key <item>` |
| Feel | `[live.menu]`: `pulse`, `pads` | `feel <item>` |
| Chord rate | `[live.menu]`: `1`, `2` (bars) | `rate <n>` (also set the metro interval to match) |
| 7ths | `[live.toggle]` | `sevenths <0/1>` |
| Velocity | `[live.numbox]` (1..127) | `velocity <n>` |
| Panic | `[live.button]` | `panic` |

Readout: `[v8 device.js]` **outlet 1** -> `[route key chord]` -> two `[live.comment]` (or
`[comment]`) boxes, so the panel shows the current key and the chord it is playing right now (e.g.
"Am" lights up as it follows you).

Tidy the visible UI (the presentation view) with the Key / Feel / Rate / 7ths / Velocity controls
and the chord readout.

## Step 5 - play-test, tune, freeze

1. Put an instrument after the device. Play a solo into the track and watch the chord readout
   follow you, comping in key, with no routing and no feedback.
2. Tune by feel (these are the most interaction-defining knobs, in `device.js`): `WINDOW_S` (how
   much recent playing drives the choice), `HALFLIFE` (recency decay), and the engine's
   `switchMargin` / `holdBonus` if it switches too eagerly or too sluggishly.
3. **Freeze**: in the Max editor, click **Freeze Device** (the snowflake) to embed `engine.js` +
   `device.js` into the device. Save as **`MidiFollow.amxd`** into your Ableton **User Library**.
   Now it is a single self-contained file - drag it onto any MIDI track before an instrument.

## Notes / gotchas

- **Feedback is structurally gone**: the device only reads its own track's input, so it cannot
  hear its own output. `device.js` also gates its own emitted notes from the analysis buffer as a
  backup - you do not need any of the PoC's two-track / All-Ins care.
- **v8 timing**: the v8 object runs in Max's low-priority thread, so note emission is scheduled via
  `Task` and should ride the transport metro, not a JS clock. Bar-level comping (1-2 s) absorbs the
  jitter. If timing drifts, confirm the metro is transport-quantized and the `tempo` observer is
  feeding the real BPM.
- **`require` after freeze**: once frozen, the `.amxd` carries `engine.js`; the search-path entry
  from Step 0 is only for development.
