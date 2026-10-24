# Notes: what we learned building this

Condensed from the build log (full history is in git: `git log -p -- docs/SESSIONS.md`).

## Design
`e16_ableton/` is an Ableton Live 12 Remote Script. It puts the e16 in SysEx **remote mode**, maps the 16 encoders to track volume (hold a push and turn for Send A), uses push taps for mute, and draws the rings and OLED itself. It was ported from a Remotify-generated Midi Fighter Twister script (`MFT script from remotify/`).

## e16 remote-mode protocol
- Header `F0 00 21 5B 02 01`. Enter `06 55`, exit `06 00` (the device acks entry with `06 53`).
- Ring: `06 04` + 7-bit-packed `[encoder 0-15, R, G, B, amount MSB, amount LSB, bipolar]`, RGB 0-127, amount 14-bit.
- OLED labels: `06 03` + 7-bit-packed 80 bytes (16-char title, then 16 labels of 4 chars).
- In remote mode turns are **relative** CC 1-16 on channel 1 (CW 1-8, CCW 127-120) and pushes are notes 0-15 on channel 1, **whatever scene is loaded**. Nothing needs installing on the e16.
- While connected the e16 stays in remote mode, so its scenes can't be switched. Setting the Control Surface slot to None releases it. Ideas not tried: a Shift (note 16) toggle, or entering remote mode when a scene sends a PC/bank message.

## Firmware
Needs a current e16 firmware (Oct 2026). On the older firmware ring colour was unusable, encoders 4 and 7 each echoed their row-neighbour's CC, and the "volume jump" seen then was really relative deltas read as absolute. The 4/7 echo is fixed now.

## Live 12.4 framework gotchas
- Subclass `OptimizedControlSurface`, not `ControlSurface` (plain gave `TypeError: object.__init__() ...` inside `MixerComponent`).
- `MixerComponent(num_tracks, num_returns)` takes no `with_eqs`/`with_filters`; `ButtonElement` has no `set_on_off_values`.
- Listeners passed to Live must be named callable objects so they can be removed.
- Point an encoder at a parameter with `encoder.connect_to(param)`; the push+twist feature re-points it at Send A while the push is held.
- Logs: `~/Library/Preferences/Ableton/Live <version>/Log.txt`.
- Helpful: the decompiled framework at github.com/gluon/AbletonLive12_MIDIRemoteScripts.

## Reloading while developing
`__init__.py` reloads `E16.py`, so setting the Control Surface slot to None and back picks up edits. Changes to `__init__.py` itself need a Live restart.

## On-device Lua (not used)
Lua can send CC and SysEx but only receive SysEx. On the older firmware `leds.update()` did nothing and `enc.increment` read 0 even with `manual=true`; edits to a script needed deleting and re-adding it in the OXI app to take effect. It has not been re-tested on current firmware.
