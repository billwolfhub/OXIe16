# OXI e16 Ableton Live 12 Mixer Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install an Ableton Live 12 Remote Script for the OXI e16 that maps encoders 1–16 to Track Volume and encoder-push buttons 1–16 to Track Mute, for the first 16 tracks, with LED feedback — a hand-written port of the equivalent Midi Fighter Twister script.

**Architecture:** A single small Python package (`e16_ableton/`) using Ableton's `_Framework` (`ControlSurface`, `MixerComponent`, `EncoderElement`, `ButtonElement`), installed via symlink into Ableton's User Library Remote Scripts folder. Before writing any Ableton-specific code, a standalone `mido`-based probe script verifies the e16's actual raw MIDI output matches the documented protocol (channel, CC numbers, note numbers) — this is the biggest risk in the whole project, so it's tested first and in isolation.

**Tech Stack:** Python 3 (Ableton Live 12's embedded interpreter for the script itself; system Python 3 + `mido`/`python-rtmidi` for the standalone probe).

**Design doc:** `docs/superpowers/specs/2026-07-09-e16-ableton-mixer-script-design.md`

---

### Task 1: Raw MIDI hardware probe

**Files:**
- Create: `scripts/midi_probe.py`

- [x] **Step 1: Write the probe script**

```python
#!/usr/bin/env python3
"""Print raw MIDI messages from a connected device, for protocol verification.

Usage: python3 midi_probe.py
Then pick the OXI e16 port from the printed list and turn/press its controls.
"""
import sys
import mido


def choose_port():
    ports = mido.get_input_names()
    if not ports:
        print("No MIDI input ports found. Is the e16 connected via USB?")
        sys.exit(1)
    for i, name in enumerate(ports):
        print(f"[{i}] {name}")
    choice = input("Select port number: ")
    return ports[int(choice)]


def main():
    port_name = choose_port()
    print(f"Listening on: {port_name}\nPress Ctrl+C to stop.\n")
    with mido.open_input(port_name) as port:
        for msg in port:
            print(msg)


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Install dependencies**

Run: `pip3 install mido python-rtmidi`
Expected: both packages install without error.

- [x] **Step 3: Run the probe against whatever scene is currently active**

Run: `python3 scripts/midi_probe.py`

With the e16 connected via USB, select its port from the list, then:
1. Turn encoder 1 clockwise a few clicks.
2. Turn encoder 1 counter-clockwise a few clicks.
3. Press and release the encoder 1 push button.
4. Press and release the physical Shift button.

Expected, per the documented protocol:
- Clockwise turn: `control_change channel=0 control=1 value=<1-8>`
- Counter-clockwise turn: `control_change channel=0 control=1 value=<0x78-0x7F, i.e. 120-127>`
- Push button: `note_on channel=0 note=0 velocity=<nonzero>` then `note_off channel=0 note=0 velocity=0`
- Shift button: `note_on channel=0 note=16 ...` then `note_off channel=0 note=16 ...`

The e16 stores its encoder/button MIDI behavior in an on-device **scene** (configured via the OXI desktop app, same mechanism the reference Bitwig script's README documents via its bundled `Bitwig.oxie16` scene file). Whatever scene is currently loaded on the hardware determines what this probe actually sees — it is not guaranteed to match the documented default.

- [x] **Step 4: If the output doesn't match, configure and save a scene**

**Actual findings (superseding the "expected" values above):**
- The scene loaded on the hardware at the start of this session (unnamed/default) had encoders 1–16 already in absolute CC mode, but on **CC 32–47** (encoder *n* → CC 31+n), not CC 1–16. Values ramp smoothly across 0–127 (absolute), not the small relative deltas the spreadsheet's factory-default table describes.
- That original scene had **no push-button mapping at all** — clicks produced no MIDI message on any of the 3 ports.
- Built a new scene named **"Ableton Tst"** in the OXI desktop app to fix this:
  - Turns: left untouched — already defaulted to CC 1–16, absolute ("CC Abs"), channel 1, matching spec exactly.
  - Pushes: had to explicitly set, per encoder: Type = Note, Note number = (encoder index − 1) i.e. 0–15, **Velocity = 127** (was defaulting to 0, which is why nothing sent — velocity-0 Note On is a no-op), **Output = the explicit USB option** (was defaulting to `ALL`, which per the reference Bitwig script's README can route to the physical TRS ports instead of USB, bypassing the computer), **Channel = fixed 1** (was defaulting to a dynamic `Page`-linked value instead of a fixed channel).
  - Shift was **not configured** — out of scope, this project's mapping doesn't use it (confirmed with the user).
- Re-probed after the fixes: confirmed clean `note_on`/`note_off channel=0 note=<0-15> velocity=127/0` pairs for all 16 pushes, and reconfirmed CC 1–16 absolute turns on this scene.
- Persistence confirmed: scene set, dragged onto an On Device slot, and the e16 rebooted — "Ableton Tst" is now the persisted on-device scene.

- [x] **Step 5: Commit**

```bash
cd "/Users/williamwolf/Documents/OXI e16"
git add scripts/midi_probe.py
git commit -m "Add raw MIDI probe script for e16 protocol verification"
```

Note: if a scene was created/edited in Step 4, it lives on the device and in the OXI desktop app's own project file, not in this git repo. If the OXI app saves a scene file to disk (as seen with the Bitwig repo's `Bitwig.oxie16`), export it and add it here too — worth checking where the OXI app stores those files.

---

### Task 2: Package skeleton and entry point

**Files:**
- Create: `e16_ableton/__init__.py`

- [x] **Step 1: Write the entry point**

```python
from .E16 import E16


def create_instance(c_instance):
    return E16(c_instance)
```

- [x] **Step 2: Commit**

```bash
cd "/Users/williamwolf/Documents/OXI e16"
git add e16_ableton/__init__.py
git commit -m "Add e16_ableton package entry point"
```

Done: commit `54f87bf`. Reviewed (spec ✅, quality ✅ approve) via Subagent-Driven Development.

(This will fail to import until Task 3 creates `E16.py` — that's expected and fine at this stage; Ableton isn't loading it yet.)

---

### Task 3: Mixer control surface implementation

**Files:**
- Create: `e16_ableton/E16.py`

- [x] **Step 1: Write the control surface**

```python
import Live
from _Framework.ControlSurface import ControlSurface
from _Framework.MixerComponent import MixerComponent
from _Framework.EncoderElement import EncoderElement
from _Framework.ButtonElement import ButtonElement
from _Framework.InputControlElement import MIDI_CC_TYPE, MIDI_NOTE_TYPE

NUM_TRACKS = 16
MIDI_CHANNEL = 0  # e16 channel 1, 0-indexed


class E16(ControlSurface):
    def __init__(self, c_instance):
        super(E16, self).__init__(c_instance)
        with self.component_guard():
            self._mixer = MixerComponent(
                NUM_TRACKS, 0, with_eqs=False, with_filters=False
            )
            self._encoders = []
            self._mute_buttons = []
            for track_index in range(NUM_TRACKS):
                strip = self._mixer.channel_strip(track_index)

                cc_number = track_index + 1  # CC 1-16
                encoder = EncoderElement(
                    MIDI_CC_TYPE,
                    MIDI_CHANNEL,
                    cc_number,
                    Live.MidiMap.MapMode.absolute,
                    name=f"Volume_Encoder_{track_index + 1}",
                )
                strip.set_volume_control(encoder)
                self._encoders.append(encoder)

                note_number = track_index  # notes 0-15
                mute_button = ButtonElement(
                    True,
                    MIDI_NOTE_TYPE,
                    MIDI_CHANNEL,
                    note_number,
                    name=f"Mute_Button_{track_index + 1}",
                )
                # NOTE: it's unconfirmed whether the e16 firmware does anything
                # visible with this feedback in plain (non-SysEx) mode — see
                # Task 5, verification step 4.
                mute_button.set_on_off_values(127, 0)
                strip.set_mute_button(mute_button)
                self._mute_buttons.append(mute_button)

    def disconnect(self):
        self._encoders = []
        self._mute_buttons = []
        super(E16, self).disconnect()
```

- [x] **Step 2: Commit**

```bash
cd "/Users/williamwolf/Documents/OXI e16"
git add e16_ableton/E16.py
git commit -m "Implement e16 mixer control surface (volume + mute, 16 tracks)"
```

Done: commit `75b5b75`. Reviewed (spec ✅, quality ✅ approve — two low-severity, non-blocking nits noted: vestigial no-op list-clearing in `disconnect()`, magic numbers `127`/`0` for on/off values. Not fixed, don't affect behavior).

---

### Task 4: Install into Ableton and verify it loads

**Files:** none (filesystem/install step only)

- [x] **Step 1: Symlink the package into Ableton's Remote Scripts folder**

```bash
mkdir -p ~/Music/Ableton/User\ Library/Remote\ Scripts
ln -sfn "/Users/williamwolf/Documents/OXI e16/e16_ableton" ~/Music/Ableton/User\ Library/Remote\ Scripts/e16_ableton
ls -la ~/Music/Ableton/User\ Library/Remote\ Scripts/
```

Expected: `e16_ableton` appears in the listing as a symlink pointing back into the OXI e16 project folder. This means edits to the file in the git repo take effect immediately (after a script reload in Live), no copying needed.

- [x] **Step 2: Assign the controller in Live 12**

Done — slot 4: Control Surface `e16_ableton`, Input/Output `OXI E16 (Port 1)`, Remote checkbox on for both directions. User has two Ableton installs (a Beta and 12.4.3 Suite) — confirmed 12.4.3 Suite is the one in use; ignore the Beta.

- [x] **Step 3: Check Live's log for load errors**

Found and fixed two real load errors (not anticipated by the plan, both required reading the actual installed `_Framework` bytecode/source since community docs didn't match this Live version):

1. `TypeError: object.__init__() takes exactly one argument` inside `MixerComponent`'s `super().__init__()` chain. Root cause never fully pinned down via static analysis despite extensive bytecode-level investigation (see `docs/SESSIONS.md` for the full trace); fixed empirically by extending `OptimizedControlSurface` instead of plain `ControlSurface` — matching what `MIDI_Mix.py`, a script confirmed actively working on this exact Live install, does. Also removed unsupported `with_eqs=`/`with_filters=` kwargs from the `MixerComponent(...)` call along the way.
2. `AttributeError: 'ButtonElement' object has no attribute 'set_on_off_values'` — that method doesn't exist in this Framework version. Removed the call entirely; `ButtonElement`'s built-in `turn_on()`/`turn_off()` already default to velocity 127/0, which is what we wanted anyway.

Final result: clean load, no errors.

---

### Task 5: Manual functional verification

**Files:** none — this is a checklist run against the real setup from Task 4.

- [x] **Step 1: Volume, hardware → Ableton**

Working, with one known hardware/firmware caveat: encoders 4 and 7 each spuriously also fire their row-neighbor's CC (encoder 4 → also fires whatever CC encoder 3 is assigned; encoder 7 → also fires encoder 8's). Confirmed via extensive isolated probe testing to be tied to encoder *position*, not the assigned CC number (remapping CC numbers didn't break the pairing), and confirmed one-directional (turning 3 or 8 alone is clean). All other 14 encoders are clean. This is an OXI firmware bug, not fixable from Ableton's side — MIDI messages from a real turn of encoder 3 vs. the phantom echo from turning encoder 4 are indistinguishable at the protocol level. User has accepted this as a known quirk for now; worth reporting to OXI support with this repro.

- [x] **Step 2: Volume, Ableton → hardware**

Working — confirmed adequate by user.

- [x] **Step 3: Mute, hardware → Ableton**

Working — confirmed adequate by user.

- [x] **Step 4: Mute, Ableton → hardware (LED feedback)**

Resolved: no visible LED change, as anticipated. Confirmed root cause — the e16's plain Note-based push messages carry no color/RGB information at all (only a velocity number), so there's no mechanism for this to work outside the SysEx "remote mode" protocol (`Misc from OXI/OXI REMOTE.xlsx`), which is explicitly out of v1 scope. Not a bug. Real RGB LED control (e.g. red-for-mute) would be a separate, scoped phase-2 feature involving a SysEx enter/exit handshake and 7-bit-packed LED/ring messages — discussed with user, deferred for now.

- [x] **Step 5: Fewer-than-16-tracks edge case**

Not separately tested with an explicit small Live set, but user reports everything else works adequately and no errors have appeared in Live's log across the whole session; `MixerComponent`'s handling of absent channel strips is standard, well-established `_Framework` behavior. Low risk; can revisit if it ever actually comes up.

- [x] **Step 6: Commit any fixes made during verification**

Multiple fix commits made during this task (see git log): `1decc38` (remove unsupported MixerComponent kwargs), `8e6b4d1` (OptimizedControlSurface), `4b72725` (remove nonexistent set_on_off_values call).
