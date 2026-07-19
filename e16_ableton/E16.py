import Live
from _Framework.ControlSurface import OptimizedControlSurface
from _Framework.MixerComponent import MixerComponent
from _Framework.EncoderElement import EncoderElement
from _Framework.ButtonElement import ButtonElement
from _Framework.InputControlElement import MIDI_CC_TYPE, MIDI_NOTE_TYPE

NUM_TRACKS = 16
MIDI_CHANNEL = 0  # e16 channel 1, 0-indexed

# SysEx remote-mode protocol (Misc from OXI/OXI REMOTE.xlsx), proven working via
# reference-scripts/oxi_e16_device_mapper/__init__.py against this exact hardware.
SYSEX_HEADER = (0xF0, 0x00, 0x21, 0x5B, 0x02, 0x01)
ENTER_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x55, 0xF7)
EXIT_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x00, 0xF7)
LED_RING_CMD = SYSEX_HEADER + (0x06, 0x04)

MUTE_COLOR = (127, 0, 0)  # red
UNMUTE_COLOR = (0, 0, 0)  # off


def pack_7bit(data):
    result = []
    data = list(data)
    while data:
        chunk = data[:7]
        data = data[7:]
        prefix = 0
        for i, byte in enumerate(chunk):
            if byte & 0x80:
                prefix |= 1 << i
        result.append(prefix)
        result.extend(b & 0x7F for b in chunk)
    return tuple(result)


def make_led_ring_sysex(encoder_index, amount_14bit, bipolar, r, g, b):
    msb = (amount_14bit >> 7) & 0x7F
    lsb = amount_14bit & 0x7F
    raw = (encoder_index, r, g, b, msb, lsb, 0x01 if bipolar else 0x00)
    return LED_RING_CMD + pack_7bit(raw) + (0xF7,)


class MuteListener(object):
    """Named callable so Live's C++ binding can identify it for removal."""

    def __init__(self, surface, index):
        self._surface = surface
        self._index = index

    def __call__(self):
        self._surface._update_mute_led(self._index)


class E16(OptimizedControlSurface):
    def __init__(self, c_instance):
        super(E16, self).__init__(c_instance)
        self._mute_listeners = {}
        with self.component_guard():
            self._mixer = MixerComponent(NUM_TRACKS, 0)
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
                # ButtonElement defaults to velocity 127 (on) / 0 (off) via its
                # built-in turn_on()/turn_off(); no explicit on/off values needed.
                strip.set_mute_button(mute_button)
                self._mute_buttons.append(mute_button)

        self._send_midi(ENTER_REMOTE_MODE)
        self._setup_mute_led_listeners()

    def _setup_mute_led_listeners(self):
        # Experimental: SysEx ring-color feedback for mute state (red = muted,
        # off = unmuted). Attached once at startup against whichever track each
        # channel strip currently holds; does not follow later track
        # reordering/add/remove within the session.
        for index in range(NUM_TRACKS):
            strip = self._mixer.channel_strip(index)
            track = strip.track
            if track is None:
                continue
            listener = MuteListener(self, index)
            track.add_mute_listener(listener)
            self._mute_listeners[index] = (track, listener)
            self._update_mute_led(index)

    def _update_mute_led(self, index):
        strip = self._mixer.channel_strip(index)
        track = strip.track
        if track is None:
            return
        r, g, b = MUTE_COLOR if track.mute else UNMUTE_COLOR
        amount = 16383 if track.mute else 0
        self._send_midi(make_led_ring_sysex(index, amount, False, r, g, b))

    def disconnect(self):
        for index, (track, listener) in self._mute_listeners.items():
            try:
                track.remove_mute_listener(listener)
            except Exception:
                pass
        self._mute_listeners = {}
        self._send_midi(EXIT_REMOTE_MODE)
        self._encoders = []
        self._mute_buttons = []
        super(E16, self).disconnect()
