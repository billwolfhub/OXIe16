"""OXI e16 control surface for Ableton Live 12, "groups" variant.

A sibling of e16_ableton that adds group handling. Use one or the other, not
both (they would fight over the same MIDI port). For the first 16 visible
tracks (encoder N = track N):
  - turn an encoder        -> that track's volume
  - hold its push + turn   -> that track's Send A ("FX send 1"); ring goes blue
  - tap its push           -> toggle mute (on release)
  - hold a push ~0.5 s     -> if the track is a group, open/close it in Live
    without turning          (the group stays on its encoder and its tracks
                             take the next encoders; hold the group's own push
                             again to close it)
  - LED ring               -> level of the track. Colour: green = normal track,
                             purple = folded group, yellow = open group;
                             red = muted (always wins); blue = Send A while held
  - OLED                   -> the first 4 characters of each track's name; a
                             group is prefixed with "*" and keeps 3 characters
                             (e.g. *Dru)

How it talks to the e16: while connected, the script puts the device into SysEx
"remote mode". In that mode the e16 ignores whatever scene is loaded and sends
fixed MIDI (turns = relative CC 1-16, pushes = notes 0-15, channel 1), and the
host (this script) draws the rings and the OLED. Nothing is stored on the
device. Protocol notes are in docs/SESSIONS.md.

Live loads this through __init__.py, which reloads this module each time, so
setting the Control Surface slot to None and back picks up edits.
"""
import re

import Live
from _Framework.ControlSurface import OptimizedControlSurface
from _Framework.MixerComponent import MixerComponent
from _Framework.EncoderElement import EncoderElement
from _Framework.ButtonElement import ButtonElement
from _Framework.InputControlElement import MIDI_CC_TYPE, MIDI_NOTE_TYPE

NUM_TRACKS = 16  # the e16 has 16 encoders; they follow the first 16 visible tracks
MIDI_CHANNEL = 0  # e16 channel 1, 0-indexed

# Remote-mode SysEx messages (OXI's OXI REMOTE.xlsx, verified on real hardware
# with firmware from 2026-10). Every message is F0 00 21 5B 02 01 <cmd> ... F7.
SYSEX_HEADER = (0xF0, 0x00, 0x21, 0x5B, 0x02, 0x01)
ENTER_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x55, 0xF7)
EXIT_REMOTE_MODE = SYSEX_HEADER + (0x06, 0x00, 0xF7)
LED_RING_CMD = SYSEX_HEADER + (0x06, 0x04)  # payload + F7 appended by the builder
OLED_LABELS_CMD = SYSEX_HEADER + (0x06, 0x03)  # payload + F7 appended by the builder

OLED_TITLE = "MIXER"  # shown above the labels; max 16 chars
LABEL_LENGTH = 4  # the OLED shows 4 characters per encoder

# Ring colours are RGB, each 0-127 (SysEx data bytes are 7-bit).
RING_ACTIVE = (0, 127, 0)  # green: track is audible
RING_MUTED = (127, 0, 0)  # red: track is muted
RING_SEND = (0, 0, 127)  # blue: shown while a push is held (encoder controls Send A)
RING_GROUP_FOLDED = (80, 0, 127)  # purple: a group that is closed
RING_GROUP_OPEN = (127, 100, 0)  # yellow: a group that is open (its tracks follow it)
GROUP_MARK = "*"  # label prefix for a group
RING_OFF = (0, 0, 0)  # no track on this encoder

# Give the device a moment after ENTER before sending LED/OLED messages; an
# immediate draw may be dropped. (A short delay is what worked on hardware.)
STARTUP_DRAW_DELAY_TICKS = 5  # 1 tick = 100 ms

# How long a push must stay down, without a twist, to count as a "hold"
# (opens/closes a group).
HOLD_TICKS = 5  # 5 ticks = 0.5 s


def pack_7bit(data):
    """Pack raw bytes into MIDI-safe 7-bit form, the way the e16 expects.

    SysEx data bytes can't have the top bit set, so every group of up to 7 bytes
    is sent as one "prefix" byte holding those bytes' top bits (bit i = byte i)
    followed by the 7 bytes with their top bit cleared.
    """
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
    """Build one LED-ring message.

    rings: iterable of (encoder_index 0-15, (r, g, b), amount_14bit).
    amount is how much of the ring is lit, 0-16383. The trailing 0 in each
    7-byte record is the "bipolar" flag (0 = fill from the left, not centred).
    Each record is exactly 7 bytes, so it packs into one 8-byte group.
    """
    raw = []
    for index, (r, g, b), amount in rings:
        raw.extend((index, r, g, b, (amount >> 7) & 0x7F, amount & 0x7F, 0))
    return LED_RING_CMD + pack_7bit(raw) + (0xF7,)


# Matches the track-number prefix the user puts on track names, e.g. "1-",
# "12-" or "#3 -". Requires a separator after the digits so a real name that
# starts with a number ("808 Kick") is left alone.
_NUMBER_PREFIX = re.compile(r"^\s*#?\d+\s*[-_.:)]\s*")


def abbreviate(name):
    """Track name -> label: drop a leading '1-' / '#12-' style prefix, then any
    leading spaces/punctuation, so '10-Kontakt 8' becomes 'Kontakt 8'."""
    return _NUMBER_PREFIX.sub("", name or "").lstrip(" #-_.:()[]")


def make_labels_sysex(title, labels):
    """Build the OLED labels message.

    title: up to 16 chars; labels: 16 strings, each cut/padded to 4 chars.
    The payload is a fixed 80 bytes (16 + 16 * 4), so missing labels are blank.
    """

    def pad(text, length):
        # The display only does printable ASCII; anything else becomes '?'.
        text = "".join(c if 32 <= ord(c) < 127 else "?" for c in (text or ""))
        return [ord(c) for c in text[:length].ljust(length)]

    raw = pad(title, 16)
    for label in (list(labels) + [""] * 16)[:16]:
        raw += pad(label, LABEL_LENGTH)
    return OLED_LABELS_CMD + pack_7bit(raw) + (0xF7,)


class ChangeListener(object):
    """Named callable so Live's C++ binding can identify it for removal.

    Removing a listener needs the same object that was added, so we keep these
    instances (see E16._listeners) instead of passing throwaway lambdas;
    _detach_listeners then removes exactly the ones we registered.
    """

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


class HoldCheck(object):
    """Scheduled HOLD_TICKS after a press; fires only if that same press is still down.

    A small object rather than schedule_message's own parameter argument, which
    treats a falsy parameter (encoder index 0) as "no parameter".
    """

    def __init__(self, surface, index, token):
        self._surface = surface
        self._index = index
        self._token = token

    def __call__(self):
        self._surface._on_hold(self._index, self._token)


class E16(OptimizedControlSurface):
    # OptimizedControlSurface, not plain ControlSurface: on Live 12.4 the plain
    # class fails inside MixerComponent's constructor with a TypeError.

    def __init__(self, c_instance):
        super(E16, self).__init__(c_instance)
        # index -> {"track", "volume", "send", "regs"} for each encoder that
        # currently has a track; "regs" lets us remove that track's listeners.
        self._listeners = {}
        self._down = [False] * NUM_TRACKS  # push currently down
        self._twisted = [False] * NUM_TRACKS  # send moved while the push was down
        self._consumed = [False] * NUM_TRACKS  # this press already opened/closed a group
        self._press_token = [0] * NUM_TRACKS  # identifies the current press for HoldCheck
        self._push_listeners = []
        # Elements and components must be created inside component_guard() so
        # the framework registers them and rebuilds Live's MIDI map afterwards.
        with self.component_guard():
            # MixerComponent is used only to track which Live track sits on
            # each channel strip (it follows adds/removes/reorders/folds for
            # us). We don't bind its controls: volume, send and mute are handled
            # below so push+twist and tap-vs-hold can work.
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
                        # Remote mode sends relative deltas as two's complement
                        # (1-8 clockwise, 127-120 counter-clockwise).
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
        # Wait for the device to settle before the first draw (see constant).
        self.schedule_message(STARTUP_DRAW_DELAY_TICKS, self._refresh_all)

    def handle_sysex(self, midi_bytes):
        # The e16 acks ENTER REMOTE MODE with a SysEx; nothing to do with it.
        # (Overriding this also stops the framework logging it as "unknown".)
        pass

    def _on_tracks_changed(self):
        # MixerComponent re-points its strips on the same event; wait a tick so
        # strip.track is up to date before we re-attach listeners.
        self.schedule_message(1, self._refresh_all)

    def _detach_listeners(self):
        """Remove every listener we added to Live's tracks and parameters."""
        for entry in self._listeners.values():
            for target, remove_name, listener in entry["regs"]:
                try:
                    getattr(target, remove_name)(listener)
                except Exception:
                    # The track may already have been deleted from the set.
                    pass
        self._listeners = {}

    @staticmethod
    def _listen(regs, target, kind, listener):
        """Add a "<kind>" listener and remember how to remove it later.

        Live names these methods add_<kind>_listener / remove_<kind>_listener,
        e.g. kind="mute" -> track.add_mute_listener(...).
        """
        getattr(target, "add_%s_listener" % kind)(listener)
        regs.append((target, "remove_%s_listener" % kind, listener))

    def _refresh_all(self):
        """(Re)attach everything to whichever tracks are on the 16 strips now.

        Runs at startup and whenever the visible track list changes (including
        when a group is opened or closed). The push state (_down/_twisted/
        _consumed) is deliberately left alone: the hold that opened a group is
        still down while this runs, and its release must not then mute anything.
        """
        with self.component_guard():
            self._detach_listeners()
            for index in range(NUM_TRACKS):
                track = self._mixer.channel_strip(index).track
                if track is None:
                    # Fewer than 16 tracks: leave this encoder inert and dark.
                    self._encoders[index].release_parameter()
                    continue
                volume = track.mixer_device.volume
                sends = track.mixer_device.sends
                send = sends[0] if len(sends) else None  # FX send 1 (Send A)
                regs = []
                # Redraw the ring when the level or mute state changes from
                # anywhere (hardware, mouse, automation), and the OLED on rename.
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
        use_send = self._down[index] and entry["send"] is not None
        self._encoders[index].connect_to(entry["send"] if use_send else entry["volume"])

    def _on_send_changed(self, index):
        # Moving the send while the push is down is a "twist": remember it so
        # the hold doesn't open a group and the release doesn't mute.
        if self._down[index]:
            self._twisted[index] = True
        self._draw_ring(index)

    def _on_push(self, index, value):
        with self.component_guard():
            if value:
                # Press: encoder now drives Send A, and we start timing a hold.
                self._down[index] = True
                self._twisted[index] = False
                self._consumed[index] = False
                self._press_token[index] += 1
                self.schedule_message(HOLD_TICKS, HoldCheck(self, index, self._press_token[index]))
            else:
                was_down = self._down[index]
                self._down[index] = False
                entry = self._listeners.get(index)
                # A tap mutes. A twist (send moved) or a hold that already
                # opened/closed a group does not. Muting waits for release so
                # we can tell these apart.
                if (
                    was_down
                    and not self._twisted[index]
                    and not self._consumed[index]
                    and entry is not None
                ):
                    entry["track"].mute = not entry["track"].mute
                self._twisted[index] = False
                self._consumed[index] = False
            self._connect_encoder(index)
            self._draw_ring(index)

    def _on_hold(self, index, token):
        # Ignore if the push was released (or pressed again) since this was
        # scheduled, or if it turned into a twist.
        if not self._down[index] or token != self._press_token[index] or self._twisted[index]:
            return
        entry = self._listeners.get(index)
        if entry is None or not entry["track"].is_foldable:
            return  # holding a normal track does nothing; its release still mutes
        track = entry["track"]
        with self.component_guard():
            track.fold_state = 0 if track.fold_state else 1  # 1 = folded
        self._consumed[index] = True
        # Live should fire the visible-tracks listener itself; this guarantees a
        # re-bind even if it doesn't.
        self.schedule_message(2, self._refresh_all)

    def _ring_state(self, index):
        """(encoder, colour, fill) for one ring, from the current Live state."""
        entry = self._listeners.get(index)
        if entry is None:
            return (index, RING_OFF, 0)
        if self._down[index] and entry["send"] is not None:
            # Show what the encoder is actually controlling right now.
            param, color = entry["send"], RING_SEND
        else:
            param = entry["volume"]
            track = entry["track"]
            if track.mute:
                color = RING_MUTED  # muted always wins, whatever kind of track
            elif track.is_foldable:
                color = RING_GROUP_FOLDED if track.fold_state else RING_GROUP_OPEN
            else:
                color = RING_ACTIVE
        # Fill is the parameter's position within its own range, scaled to the
        # ring's 14-bit amount (so it follows the fader, not a dB value).
        span = param.max - param.min
        fraction = (param.value - param.min) / span if span else 0.0
        amount = max(0, min(16383, int(fraction * 16383)))
        return (index, color, amount)

    def _draw_ring(self, index):
        self._send_midi(make_ring_sysex([self._ring_state(index)]))

    def _draw_all(self):
        # One message per ring rather than one big one, to stay well under any
        # SysEx size limit on the device.
        for index in range(NUM_TRACKS):
            self._draw_ring(index)

    @staticmethod
    def _label_for(track):
        name = abbreviate(track.name)
        if track.is_foldable:
            # Group: mark it; open vs folded is shown by the ring colour. Leaves
            # LABEL_LENGTH - 1 characters for the name.
            return GROUP_MARK + name[: LABEL_LENGTH - 1]
        return name

    def _draw_labels(self):
        names = []
        for index in range(NUM_TRACKS):
            entry = self._listeners.get(index)
            names.append(self._label_for(entry["track"]) if entry else "")
        self._send_midi(make_labels_sysex(OLED_TITLE, names))

    def disconnect(self):
        # Called when the slot is set to None or Live closes. Release the e16
        # (rings off, leave remote mode) so its own scenes work again.
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
