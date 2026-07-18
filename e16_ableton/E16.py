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
