#!/usr/bin/env python3
"""Standalone test of the e16's remote-mode LED ring SysEx (no Ableton needed).

Protocol from Misc from OXI/OXI REMOTE.xlsx (E16 sheet):
  header  F0 00 21 5B 02 01
  enter   06 55           exit  06 00
  ring    06 04 + 7-bit-packed [encoder 0-15, R, G, B, amount MSB, amount LSB, bipolar]
          amount is 14-bit (0..16383), R/G/B are 0..127

Step 1: enter remote mode, light rings 1-4 red/green at full and half.
Step 2: keep remote mode active and print incoming CC/Note for 15s, so you can
        turn encoder 1 and check the values still change smoothly (the old
        volume-jump bug).
Step 3: exit remote mode.

Usage: python3 scripts/sysex_ring_test.py
"""
import time
import mido

HEADER = [0x00, 0x21, 0x5B, 0x02, 0x01]  # between F0 and F7; mido adds the framing
RED = (127, 0, 0)
GREEN = (0, 127, 0)


def pack_7bit(data):
    out = []
    data = list(data)
    while data:
        chunk, data = data[:7], data[7:]
        prefix = 0
        for i, b in enumerate(chunk):
            if b & 0x80:
                prefix |= 1 << i
        out.append(prefix)
        out.extend(b & 0x7F for b in chunk)
    return out


def ring(out, encoder, rgb, amount, bipolar=False):
    raw = [encoder, rgb[0], rgb[1], rgb[2], (amount >> 7) & 0x7F, amount & 0x7F, 1 if bipolar else 0]
    out.send(mido.Message("sysex", data=HEADER + [0x06, 0x04] + pack_7bit(raw)))


def find(names, needle):
    for n in names:
        if needle in n:
            return n
    raise SystemExit("No port containing %r in %s" % (needle, names))


def main():
    in_name = find(mido.get_input_names(), "OXI E16 Port 1")
    out_name = find(mido.get_output_names(), "OXI E16 Port 1")
    print("in: %s   out: %s" % (in_name, out_name))
    with mido.open_input(in_name) as inp, mido.open_output(out_name) as out:
        out.send(mido.Message("sysex", data=HEADER + [0x06, 0x55]))
        print("Sent ENTER REMOTE MODE; waiting up to 2s for ack...")
        end = time.time() + 2
        acked = False
        while time.time() < end:
            for m in inp.iter_pending():
                if m.type == "sysex" and list(m.data[-3:-1]) == [0x06, 0x53] or (
                    m.type == "sysex" and 0x53 in m.data
                ):
                    acked = True
                    print("  ack:", list(m.data))
            time.sleep(0.01)
        print("  ack received" if acked else "  no ack seen (continuing anyway)")

        ring(out, 0, RED, 16383)
        ring(out, 1, GREEN, 16383)
        ring(out, 2, RED, 8192)
        ring(out, 3, GREEN, 8192)
        print("\nSTEP 1: encoders 1-4 should show: 1=red full, 2=green full, 3=red half, 4=green half.")
        input("Tell me what you see, then press Enter to continue...")

        print("\nSTEP 2: remote mode still active. Turn encoder 1 slowly for 15s;")
        print("        values below should move smoothly (not jump between 0 and 127).")
        end = time.time() + 15
        while time.time() < end:
            for m in inp.iter_pending():
                print(" ", m)
            time.sleep(0.005)

        for i in range(16):
            ring(out, i, (0, 0, 0), 0)
        out.send(mido.Message("sysex", data=HEADER + [0x06, 0x00]))
        print("\nSent EXIT REMOTE MODE. Done.")


if __name__ == "__main__":
    main()
