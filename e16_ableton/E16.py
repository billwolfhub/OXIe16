import Live
from _Framework.ControlSurface import OptimizedControlSurface
from _Framework.MixerComponent import MixerComponent
from _Framework.EncoderElement import EncoderElement
from _Framework.ButtonElement import ButtonElement
from _Framework.InputControlElement import MIDI_CC_TYPE, MIDI_NOTE_TYPE

NUM_TRACKS = 16
MIDI_CHANNEL = 0  # e16 channel 1, 0-indexed

# Remote-mode SysEx protocol (Misc from OXI/OXI REMOTE.xlsx, verified against
# firmware 2026-10 with scripts/sysex_ring_test.py). In remote mode encoders
# report RELATIVE deltas (CW 1-8, CCW 127-120) and the host draws the rings.
SYSEX_HEADER = (0xF0, 0x00, 0x21, 0x5B, 0x02, 0x01)
ENTER_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x55, 0xF7)
EXIT_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x00, 0xF7)
LED_RING_CMD = SYSEX_HEADER + (0x06, 0x04)

RING_ACTIVE = (0, 127, 0)  # green
RING_MUTED = (127, 0, 0)  # red
RING_OFF = (0, 0, 0)

# Remote mode needs a moment after ENTER before it accepts LED messages.
STARTUP_DRAW_DELAY_TICKS = 5  # 1 tick = 100 ms


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


def make_ring_sysex(rings):
    """rings: iterable of (encoder_index 0-15, (r, g, b), amount_14bit)."""
    raw = []
    for index, (r, g, b), amount in rings:
        raw.extend((index, r, g, b, (amount >> 7) & 0x7F, amount & 0x7F, 0))
    return LED_RING_CMD + pack_7bit(raw) + (0xF7,)


class ChangeListener(object):
    """Named callable so Live's C++ binding can identify it for removal."""

    def __init__(self, surface, index):
        self._surface = surface
        self._index = index

    def __call__(self):
        self._surface._draw_ring(self._index)


class E16(OptimizedControlSurface):
    def __init__(self, c_instance):
        super(E16, self).__init__(c_instance)
        self._listeners = {}
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
                    Live.MidiMap.MapMode.relative_smooth_two_compliment,
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
                strip.set_mute_button(mute_button)
                self._mute_buttons.append(mute_button)

        self.song().add_visible_tracks_listener(self._on_tracks_changed)
        self._send_midi(ENTER_REMOTE_MODE)
        self.schedule_message(STARTUP_DRAW_DELAY_TICKS, self._refresh_all)

    def handle_sysex(self, midi_bytes):
        # The e16 acks ENTER REMOTE MODE with a SysEx; nothing to do with it.
        pass

    def _on_tracks_changed(self):
        # MixerComponent re-points its strips on the same event; wait a tick so
        # strip.track is up to date before we re-attach listeners.
        self.schedule_message(1, self._refresh_all)

    def _detach_listeners(self):
        for track, volume, volume_listener, mute_listener in self._listeners.values():
            try:
                volume.remove_value_listener(volume_listener)
                track.remove_mute_listener(mute_listener)
            except Exception:
                pass
        self._listeners = {}

    def _refresh_all(self):
        self._detach_listeners()
        for index in range(NUM_TRACKS):
            track = self._mixer.channel_strip(index).track
            if track is None:
                continue
            volume = track.mixer_device.volume
            volume_listener = ChangeListener(self, index)
            mute_listener = ChangeListener(self, index)
            volume.add_value_listener(volume_listener)
            track.add_mute_listener(mute_listener)
            self._listeners[index] = (track, volume, volume_listener, mute_listener)
        self._draw_all()

    def _ring_state(self, index):
        entry = self._listeners.get(index)
        if entry is None:
            return (index, RING_OFF, 0)
        track, volume, _, _ = entry
        span = volume.max - volume.min
        fraction = (volume.value - volume.min) / span if span else 0.0
        amount = max(0, min(16383, int(fraction * 16383)))
        return (index, RING_MUTED if track.mute else RING_ACTIVE, amount)

    def _draw_ring(self, index):
        self._send_midi(make_ring_sysex([self._ring_state(index)]))

    def _draw_all(self):
        for index in range(NUM_TRACKS):
            self._draw_ring(index)

    def disconnect(self):
        self._detach_listeners()
        if self.song().visible_tracks_has_listener(self._on_tracks_changed):
            self.song().remove_visible_tracks_listener(self._on_tracks_changed)
        self._send_midi(make_ring_sysex([(i, RING_OFF, 0) for i in range(NUM_TRACKS)]))
        self._send_midi(EXIT_REMOTE_MODE)
        self._encoders = []
        self._mute_buttons = []
        super(E16, self).disconnect()
