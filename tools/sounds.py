#!/usr/bin/env python3
"""The camera's sounds, synthesized like a 2000s compact's (11025 Hz mono
16-bit PCM, each within its resource slot):

    python3 tools/sounds.py OUT_DIR    # shutter.wav, poweron.wav, click.wav

shutter: the fake shutter of a digicam, "ka-chak": a bright click, then a
duller one 70 ms later, each a decaying noise burst with a little resonance.
poweron: a rising three-note chime (E6, G#6, B6). click: a short tick for
the center button's mode change.
"""
import math, os, struct, sys, wave

RATE = 11025
SLOTS = {'shutter.wav': 0x1c00, 'poweron.wav': 0x4000, 'click.wav': 0x1800}   # CAMERA, POWERON_AUDIO, CLICK


def noise():
    x = 12345
    while True:
        x = (x * 1103515245 + 12345) & 0x7fffffff
        yield (x >> 8) / (1 << 22) - 1.0


def burst(n, at, length, decay, ring, gain, rnd):
    """A decaying noise burst at sample `at`, through a two-pole resonator at
    `ring` Hz (its body), added into n samples."""
    out = [0.0] * n
    r = math.exp(-2 * math.pi * 900 / RATE)                 # resonator bandwidth
    c = 2 * r * math.cos(2 * math.pi * ring / RATE)
    y1 = y2 = 0.0
    for i in range(at, min(n, at + length)):
        t = (i - at) / RATE
        x = next(rnd) * math.exp(-t / decay)
        y = x + c * y1 - r * r * y2
        y2, y1 = y1, y
        out[i] = gain * (0.6 * y * (1 - r) * 4 + 0.4 * x)
    return out


def shutter():
    n = int(0.22 * RATE)
    rnd = noise()
    a = burst(n, 0, int(0.03 * RATE), 0.004, 3400, 0.9, rnd)
    b = burst(n, int(0.07 * RATE), int(0.05 * RATE), 0.008, 1900, 0.7, rnd)
    return [p + q for p, q in zip(a, b)]


def chime():
    notes = [(1318.5, 0.0), (1661.2, 0.11), (1975.5, 0.22)]
    n = int(0.70 * RATE)
    out = [0.0] * n
    for f, start in notes:
        s = int(start * RATE)
        for i in range(s, n):
            t = (i - s) / RATE
            env = min(1.0, t / 0.004) * math.exp(-t / 0.16)
            out[i] += 0.32 * env * (math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t))
    return out


def click():
    n = int(0.03 * RATE)
    return [0.5 * math.exp(-i / RATE / 0.004) * math.sin(2 * math.pi * 2200 * i / RATE) for i in range(n)]


def write(path, samples, slot):
    peak = max(1e-9, max(abs(s) for s in samples))
    k = min(1.0, 0.95 / peak)
    data = b''.join(struct.pack('<h', int(max(-1, min(1, s * k)) * 32767)) for s in samples)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    assert os.path.getsize(path) <= slot, (path, os.path.getsize(path), slot)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    os.makedirs(sys.argv[1], exist_ok=True)
    for name, fn in (('shutter.wav', shutter), ('poweron.wav', chime), ('click.wav', click)):
        write(os.path.join(sys.argv[1], name), fn(), SLOTS[name])
