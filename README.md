# OXIe16

An Ableton Live 12 Remote Script for the [OXI e16](https://oxiinstruments.com/) MIDI controller: 16 encoders map to Track Volume, and their push buttons toggle Track Mute, for the first 16 tracks in the current Live set. Each encoder's LED ring shows the track's real volume and is **green when the track is active, red when muted**. The OLED shows each track's name (first 4 characters, with a leading `1-` style number stripped). **Tap a push to mute/unmute; hold a push and turn to control that track's FX send 1** (ring turns blue). It updates whenever volume or mute changes, from the hardware, the mouse, or automation.

This is a hand-written port of an equivalent [Remotify](https://remotify.io/)-generated script for a Midi Fighter Twister, rebuilt for the e16 rather than with any generator tool. The script puts the e16 into its SysEx *remote mode* while connected: encoders then report relative deltas and the script draws the rings itself (see `Misc from OXI/OXI REMOTE.xlsx`). This needs a recent e16 firmware; with the older firmware, ring colour was not usable.

## What's in this repo

- `e16_ableton/` — the actual Ableton Remote Script (`__init__.py` + `E16.py`)
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — the design doc and implementation plan
- `docs/SESSIONS.md` — a running log of the whole build, including a fairly deep debugging saga (worth reading if you hit a similar `_Framework` error)
- `MFT script from remotify/` — the original Midi Fighter Twister script this was ported from
- `Misc from OXI/OXI REMOTE.xlsx` — OXI's documented MIDI/SysEx protocol reference for the e16 (and OXI ONE / ONE MKII)

## Prerequisites

- Ableton Live 12 (built and tested against 12.4.3)
- An OXI e16, connected via USB

## 1. The e16 needs no setup

The script switches the e16 into its SysEx *remote mode* when Live loads it, and the e16 then sends fixed MIDI regardless of which scene is loaded: turns as relative CC 1-16, pushes as notes 0-15, both on channel 1. Nothing is written to the device, and no scene or Lua script has to be installed on it. (Tested with an unrelated scene, `DUBLETON`, loaded on the e16 before starting Live.)

## 2. Install the script (the only thing to install)

Symlink this repo's `e16_ableton/` folder into Ableton's Remote Scripts directory:

```bash
mkdir -p ~/Music/Ableton/User\ Library/Remote\ Scripts
ln -sfn "$(pwd)/e16_ableton" ~/Music/Ableton/User\ Library/Remote\ Scripts/e16_ableton
```

(Run that from this repo's root. Using a symlink means future edits here take effect on the next reload, no copying needed.)

Then in Ableton Live:
1. Fully quit and reopen Live (Remote Scripts are only scanned on launch).
2. **Settings → Link, Tempo & MIDI**.
3. In a Control Surface slot, select **e16_ableton**.
4. Set both **Input** and **Output** to the e16's MIDI port (shows up as something like `OXI E16 (Port 1)`).
5. Confirm the **Remote** checkbox is enabled for that port in both the Input Ports and Output Ports tables further down the same settings page.

If something goes wrong, check Live's `Log.txt` (`~/Library/Preferences/Ableton/Live <version>/Log.txt`) for a Python traceback — search for `E16` or `e16_ableton`.

**When iterating on `E16.py`**: a full quit-and-reopen of Live is needed to reliably pick up code changes. Deselecting and reselecting `e16_ableton` in the Control Surface dropdown can *look* like a reload (fresh "Initializing..." log lines, no errors) while actually still running the previous version — confirmed the hard way across several rounds of live debugging. If a fix doesn't seem to take effect, restart Live fully before assuming the fix is wrong.

## Known issues

- **Fixed in current firmware:** older e16 firmware had a bug where turning encoder 4 or 7 also fired its row-neighbour's CC (3 and 8 respectively). All 16 encoders now behave independently on current firmware.
- **The e16 is locked in remote mode while the script is connected**, so you can't switch to another e16 scene or setup until you set the Control Surface slot to **None** (which makes it leave remote mode) and reselect `e16_ableton` when you want it back. A Shift-button toggle or a scene-entry trigger is being considered.
- If Live crashes and the script is disconnected uncleanly, the e16 may stay in remote mode until power-cycled.
