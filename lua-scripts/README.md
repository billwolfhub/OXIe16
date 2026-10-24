# Lua LED test (obsolete)

`led_color_value_test.lua` tested the e16's on-device `leds.update()` call, which did not light the rings on the older firmware. It is kept as a repro for a bug report; the red/green rings are now drawn by `e16_ableton` using remote-mode SysEx, so this script is no longer needed. `leds.update()` has not been re-tested on current firmware.
