# OXIe16

An Ableton Live 12 Remote Script for the [OXI e16](https://oxiinstruments.com/) MIDI controller: 16 encoders map to Track Volume, and their push buttons toggle Track Mute, for the first 16 tracks in the current Live set. Feedback works both ways — moving a fader or muting a track in Live updates the hardware.

This is a hand-written port of an equivalent [Remotify](https://remotify.io/)-generated script for a Midi Fighter Twister, rebuilt against the e16's own plain MIDI CC/Note behavior rather than any generator tool.

## What's in this repo

- `e16_ableton/` — the actual Ableton Remote Script (`__init__.py` + `E16.py`)
- `scripts/midi_probe.py` — a standalone diagnostic tool for inspecting raw MIDI from the e16
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — the design doc and implementation plan
- `docs/SESSIONS.md` — a running log of the whole build, including a fairly deep debugging saga (worth reading if you hit a similar `_Framework` error)
- `MFT script from remotify/` — the original Midi Fighter Twister script this was ported from
- `Misc from OXI/OXI REMOTE.xlsx` — OXI's documented MIDI/SysEx protocol reference for the e16 (and OXI ONE / ONE MKII)

## Prerequisites

- Ableton Live 12 (built and tested against 12.4.3)
- An OXI e16, connected via USB
- The [OXI desktop app](https://oxiinstruments.com/), to configure the e16's on-device scene

## 1. Configure the e16's scene

The e16 stores its encoder/button MIDI behavior in an on-device **scene**, configured via the OXI desktop app. This script expects:

**Encoders 1–16 (Turn):**
| Field | Value |
|---|---|
| Type | CC (Control Change) |
| Mode | Absolute (`CC Abs`) |
| Channel | 1 |
| CC number | 1 for encoder 1, 2 for encoder 2, … 16 for encoder 16 |

**Encoder pushes 1–16 (Push):**
| Field | Value |
|---|---|
| Type | Note |
| Channel | 1 |
| Note number | 0 for encoder 1's push, 1 for encoder 2's, … 15 for encoder 16's |
| Velocity | **127** (the app may default this to 0, which is a no-op — a Note On with velocity 0 doesn't register) |
| Output | An explicit **USB** output, not `ALL` — with `ALL`, messages can get routed to the physical TRS ports instead of over USB, silently never reaching your computer |
| Channel | A **fixed** value (`1`), not the dynamic `Page`-linked default |
| Accel Mode | Momentary / press-only (Note On on press, Note Off on release — not toggle) |

Many e16 scenes already default the Turn side to CC 1–16 absolute — check before rebuilding it. The Push side commonly needs all four of the above fixed manually; none of them are the app's defaults.

Once configured:
1. Name the scene (e.g. "Ableton Tst") and **Save**.
2. Click **Set**, then drag the scene onto a slot in the **On Device** list — Save alone only writes to your computer, not the hardware.
3. Reboot the e16 to clear its cache.

You can verify the scene is sending what's expected with `scripts/midi_probe.py` (see below) before moving on.

## 2. Install the script

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

## Diagnostic tool

`scripts/midi_probe.py` prints raw MIDI messages from a connected device — useful for confirming the e16's scene is actually sending what you configured, independent of Ableton.

```bash
pip3 install mido python-rtmidi
python3 scripts/midi_probe.py
```

Pick the e16's port from the printed list, then turn/press its controls and watch the output.

## Known issues

- **Encoders 4 and 7 have a firmware bug**: turning either one also spuriously fires its row-neighbor's CC (encoder 4 → also fires encoder 3's CC; encoder 7 → also fires encoder 8's). Confirmed via extensive isolated testing to be tied to encoder position, not the assigned CC number, and confirmed not fixable from the Ableton side — a real turn of the neighboring encoder and the phantom echo are indistinguishable at the MIDI protocol level. Every other encoder (including the equivalent positions in rows 3–4) is clean. Worth reporting to OXI support.
- **No LED color feedback for mute.** The e16's plain Note messages carry no color information — real RGB LED control (e.g. lighting a button red when muted) requires the e16's separate SysEx "remote mode" protocol (documented in `Misc from OXI/OXI REMOTE.xlsx`), which this script doesn't implement. Volume still gets ring-position feedback for free, since the e16 updates its own LED ring when it receives a CC message on the corresponding number.
