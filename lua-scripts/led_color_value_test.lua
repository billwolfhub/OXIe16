-- LED color/value independence test.
--
-- Encoder 1 (manual mode): turning it tracks a 0-127 value locally and shows
-- it as ring fill position (normal color). Pressing it toggles a "muted"
-- flag: ring snaps to full and switches color; press again to return to the
-- tracked value in the normal color.
--
-- Goal: confirm ring value and color can be set together, independently,
-- entirely from the device -- without the encoder-position desync hit
-- earlier trying to do this via SysEx sent from an Ableton-hosted script
-- (see docs/SESSIONS.md, 2026-07-18 mute-LED attempt).

--@assign id=1 abbr="Val" name="Test Value" desc="Manual value + LED test" l=0 h=127 manual=true g=1
--@assign id=2 abbr="Mut" name="Test Mute" desc="Toggle mute-red ring" p=true g=1

local NORMAL_COLOR = 0
local MUTE_COLOR = 1 -- guess; adjust once we see what this index actually looks like

local value = 0
local muted = false

local function redraw()
    if muted then
        leds.update(1, 16383, MUTE_COLOR)
        slots.update(1, "MUTE")
    else
        local amount = (value * 16383) // 127
        leds.update(1, amount, NORMAL_COLOR)
        slots.update(1, tostring(value))
    end
end

function page.onInit()
    page.setTitle("LED Test")
    -- Broad diagnostic: light every ring on the page full brightness, each
    -- with a different color index (0-15), immediately at startup, no
    -- assignment or interaction required. Tells us in one shot whether
    -- leds.update works at all, whether our index assumption was wrong, and
    -- which color values (if any) are actually visible.
    for i = 1, 16 do
        leds.update(i, 16383, i - 1)
    end
    slots.update(1, "INIT")
end

function controller.onEncoderTurn(enc)
    if enc.id ~= 1 then return end
    value = value + enc.increment
    if value < 0 then value = 0 end
    if value > 127 then value = 127 end
    midi.sendCC(0, 0, 1, value) -- optional: mirror out as CC1, visible on a MIDI monitor
    redraw()
end

function controller.onEncoderPress(enc)
    if enc.id ~= 2 then return end
    muted = not muted
    redraw()
end
