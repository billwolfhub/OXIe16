import re

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
OLED_LABELS_CMD = SYSEX_HEADER + (0x06, 0x03)

OLED_TITLE = "MIXER"  # max 16 chars
LABEL_LENGTH = 4  # chars per encoder label

RING_ACTIVE = (0, 127, 0)  # green
RING_MUTED = (127, 0, 0)  # red
RING_SEND = (0, 0, 127)  # blue: shown while a push is held (encoder controls Send A)
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


_NUMBER_PREFIX = re.compile(r"^\s*#?\d+\s*[-_.:)]\s*")


def abbreviate(name):
    """Track name -> label: drop a leading '1-' / '#12-' style prefix, then any
    leading spaces/punctuation, so '10-Kontakt 8' becomes 'Kontakt 8'."""
    return _NUMBER_PREFIX.sub("", name or "").lstrip(" #-_.:()[]")


def make_labels_sysex(title, labels):
    """title: up to 16 chars; labels: 16 strings, each cut/padded to 4 chars."""

    def pad(text, length):
        text = "".join(c if 32 <= ord(c) < 127 else "?" for c in (text or ""))
        return [ord(c) for c in text[:length].ljust(length)]

    raw = pad(title, 16)
    for label in (list(labels) + [""] * 16)[:16]:
        raw += pad(label, LABEL_LENGTH)
    return OLED_LABELS_CMD + pack_7bit(raw) + (0xF7,)


class ChangeListener(object):
    """Named callable so Live's C++ binding can identify it for removal."""

    def __init__(self, callback, *args):
        self._callback = callback
        self._args = args

    def __call__(self):
        self._callback(*self._args)


class PushListener(object):
    """Named callable for a ButtonElement's value listener (value 127 = press, 0 = release)."""

    def __init__(self, surface, index):
        self._surface = surface
        self._index = index

    def __call__(self, value):
        self._surface._on_push(self._index, value)


class E16(OptimizedControlSurface):
    def __init__(self, c_instance):
        super(E16, self).__init__(c_instance)
        self._listeners = {}
        self._held = [False] * NUM_TRACKS  # push currently down
        self._twisted = [False] * NUM_TRACKS  # send moved while the push was down
        self._push_listeners = []
        with self.component_guard():
            self._mixer = MixerComponent(NUM_TRACKS, 0)
            self._encoders = []
            self._buttons = []
            for track_index in range(NUM_TRACKS):
                cc_number = track_index + 1  # CC 1-16
                self._encoders.append(
                    EncoderElement(
                        MIDI_CC_TYPE,
                        MIDI_CHANNEL,
                        cc_number,
                        Live.MidiMap.MapMode.relative_smooth_two_compliment,
                        name=f"Encoder_{track_index + 1}",
                    )
                )
                note_number = track_index  # notes 0-15
                button = ButtonElement(
                    True,
                    MIDI_NOTE_TYPE,
                    MIDI_CHANNEL,
                    note_number,
                    name=f"Push_{track_index + 1}",
                )
                listener = PushListener(self, track_index)
                button.add_value_listener(listener)
                self._buttons.append(button)
                self._push_listeners.append(listener)

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
        for entry in self._listeners.values():
            for target, remove_name, listener in entry["regs"]:
                try:
                    getattr(target, remove_name)(listener)
                except Exception:
                    pass
        self._listeners = {}

    @staticmethod
    def _listen(regs, target, kind, listener):
        getattr(target, "add_%s_listener" % kind)(listener)
        regs.append((target, "remove_%s_listener" % kind, listener))

    def _refresh_all(self):
        with self.component_guard():
            self._detach_listeners()
            for index in range(NUM_TRACKS):
                self._held[index] = False
                self._twisted[index] = False
                track = self._mixer.channel_strip(index).track
                if track is None:
                    self._encoders[index].release_parameter()
                    continue
                volume = track.mixer_device.volume
                sends = track.mixer_device.sends
                send = sends[0] if len(sends) else None  # FX send 1 (Send A)
                regs = []
                self._listen(regs, volume, "value", ChangeListener(self._draw_ring, index))
                self._listen(regs, track, "mute", ChangeListener(self._draw_ring, index))
                self._listen(regs, track, "name", ChangeListener(self._draw_labels))
                if send is not None:
                    self._listen(regs, send, "value", ChangeListener(self._on_send_changed, index))
                self._listeners[index] = {
                    "track": track,
                    "volume": volume,
                    "send": send,
                    "regs": regs,
                }
                self._connect_encoder(index)
            self._draw_all()
            self._draw_labels()

    def _connect_encoder(self, index):
        """Encoder drives Send A while its push is held (if the track has one),
        otherwise volume. Uses Live's native relative mapping either way."""
        entry = self._listeners.get(index)
        if entry is None:
            self._encoders[index].release_parameter()
            return
        use_send = self._held[index] and entry["send"] is not None
        self._encoders[index].connect_to(entry["send"] if use_send else entry["volume"])

    def _on_send_changed(self, index):
        if self._held[index]:
            self._twisted[index] = True
        self._draw_ring(index)

    def _on_push(self, index, value):
        with self.component_guard():
            entry = self._listeners.get(index)
            if value:
                self._held[index] = True
                self._twisted[index] = False
            else:
                twisted = self._twisted[index]
                self._held[index] = False
                self._twisted[index] = False
                # A tap mutes; a twist (send moved while held) does not.
                if entry is not None and not twisted:
                    entry["track"].mute = not entry["track"].mute
            self._connect_encoder(index)
            self._draw_ring(index)

    def _ring_state(self, index):
        entry = self._listeners.get(index)
        if entry is None:
            return (index, RING_OFF, 0)
        track = entry["track"]
        if self._held[index] and entry["send"] is not None:
            param, color = entry["send"], RING_SEND
        else:
            param, color = entry["volume"], RING_MUTED if track.mute else RING_ACTIVE
        span = param.max - param.min
        fraction = (param.value - param.min) / span if span else 0.0
        amount = max(0, min(16383, int(fraction * 16383)))
        return (index, color, amount)

    def _draw_ring(self, index):
        self._send_midi(make_ring_sysex([self._ring_state(index)]))

    def _draw_all(self):
        for index in range(NUM_TRACKS):
            self._draw_ring(index)

    def _draw_labels(self):
        names = []
        for index in range(NUM_TRACKS):
            entry = self._listeners.get(index)
            names.append(abbreviate(entry["track"].name) if entry else "")
        self._send_midi(make_labels_sysex(OLED_TITLE, names))

    def disconnect(self):
        self._detach_listeners()
        for button, listener in zip(self._buttons, self._push_listeners):
            try:
                button.remove_value_listener(listener)
            except Exception:
                pass
        for encoder in self._encoders:
            encoder.release_parameter()
        if self.song().visible_tracks_has_listener(self._on_tracks_changed):
            self.song().remove_visible_tracks_listener(self._on_tracks_changed)
        self._send_midi(make_ring_sysex([(i, RING_OFF, 0) for i in range(NUM_TRACKS)]))
        self._send_midi(EXIT_REMOTE_MODE)
        self._encoders = []
        self._buttons = []
        self._push_listeners = []
        super(E16, self).disconnect()
