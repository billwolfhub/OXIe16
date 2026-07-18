#!/usr/bin/env python3
"""Print raw MIDI messages from a connected device, for protocol verification.

Usage: python3 midi_probe.py
Then pick the OXI e16 port from the printed list and turn/press its controls.
"""
import sys
import mido


def choose_port():
    ports = mido.get_input_names()
    if not ports:
        print("No MIDI input ports found. Is the e16 connected via USB?")
        sys.exit(1)
    for i, name in enumerate(ports):
        print(f"[{i}] {name}")
    choice = input("Select port number: ")
    return ports[int(choice)]


def main():
    port_name = choose_port()
    print(f"Listening on: {port_name}\nPress Ctrl+C to stop.\n")
    with mido.open_input(port_name) as port:
        for msg in port:
            print(msg)


if __name__ == "__main__":
    main()
