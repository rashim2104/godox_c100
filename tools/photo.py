#!/usr/bin/env python3
"""Photo size and JPEG quality build options (tools/build.sh).

    SIZE169=WxH SIZE32=WxH SIZE43=WxH SIZE11=WxH   per aspect setting, e.g. SIZE43=1280x960
    JPEG_Q=1..98                                    the encoder's IJG quality, photos only

Unset = the factory's: 1920x1080, 1616x1080, 1440x1080, 1024x1024, and Q 98 /
90 / 80 by the camera's quality setting (CFG + 0xb; 90 on our cameras).

    photo.py asm                    size.inc for size_cave.s (exits 1 on a bad size)
    photo.py patches A169 A32 A43 A11   ADDR:OLD:NEW for the jump table slots (stub addresses)
    photo.py quality                ADDR:OLD:NEW for JPEG_Q (nothing when unset)

A size is scaled from the largest crop of its own shape inside the setting's
stock crop, so the bracket still frames the photo. No upscales: W <= crop W.
"""
import os, sys

STOCK_CROPS = {'169': (1920, 1080), '32': (1616, 1080), '43': (1440, 1080), '11': (1024, 1024)}
SLOTS = {'169': (0, 1), '32': (2,), '43': (3, 11, 12), '11': (4,)}  # photo jump table @0xf3d0
TABLE = 0xf3d0
FACTORY = {0: 0xf79c, 1: 0xf79c, 2: 0xf7b0, 3: 0xf7c4, 4: 0xf6d4, 11: 0xf760, 12: 0xf774}
MIN_W, MIN_H = 320, 240        # the date stamp is 46 px tall
# FUN_00011724: mov r3, #Q per quality setting (2 -> 80, 0 -> 98, else 90)
Q_MOVS = {0x11770: 90, 0x11790: 80, 0x117a0: 98}


def crop_for(aspect, w, h):
    """Largest crop of w:h's shape inside the setting's stock crop (W to 16, H to 4)."""
    cw, ch = STOCK_CROPS[aspect]
    if w * ch >= h * cw:
        return cw, (2 * cw * h + 4 * w) // (8 * w) * 4
    return (2 * ch * w + 16 * h) // (32 * h) * 16, ch


def size_errors(aspect, w, h):
    errors = []
    if w % 16:
        errors.append('a width that is a multiple of 16')
    if h % 4:
        errors.append('a height that is a multiple of 4')
    if w < MIN_W or h < MIN_H:
        errors.append(f'at least {MIN_W}x{MIN_H}')
    cw, ch = crop_for(aspect, w, h)
    if w > cw or h > ch:
        errors.append(f'at most the crop {cw}x{ch} (larger is an upscale)')
    return errors


def config(env=os.environ):
    """{aspect: ((crop w, h), (out w, h))} for the SIZE* that are set."""
    out = {}
    for k in STOCK_CROPS:
        v = env.get('SIZE' + k)
        if not v:
            continue
        try:
            w, h = map(int, v.lower().split('x'))
        except ValueError:
            sys.exit(f'SIZE{k}={v}: want WxH, e.g. 1280x960')
        if errs := size_errors(k, w, h):
            sys.exit(f'SIZE{k}={v}: needs ' + ', '.join(errs))
        out[k] = (crop_for(k, w, h), (w, h))
    return out


def jpeg_q(env=os.environ):
    v = env.get('JPEG_Q')
    if not v:
        return None
    if not v.isdigit() or not 1 <= int(v) <= 98:
        sys.exit(f'JPEG_Q={v}: want 1..98 (98 is the factory maximum; 100 makes all-ones tables)')
    return int(v)


def word(x):
    return x.to_bytes(4, 'little').hex()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    cfg = config()
    if cmd == 'asm':
        for k, (crop, outsz) in cfg.items():
            print(f'    .equ    P{k}_W, {outsz[0]}\n    .equ    P{k}_H, {outsz[1]}\n'
                  f'    .equ    P{k}_CW, {crop[0]}\n    .equ    P{k}_CH, {crop[1]}')
        for k, crop in STOCK_CROPS.items():          # unset: the stock size (its stub is unused)
            if k not in cfg:
                print(f'    .equ    P{k}_W, {crop[0]}\n    .equ    P{k}_H, {crop[1]}\n'
                      f'    .equ    P{k}_CW, {crop[0]}\n    .equ    P{k}_CH, {crop[1]}')
    elif cmd == 'patches':
        stubs = dict(zip(STOCK_CROPS, (int(a, 0) for a in sys.argv[2:6])))
        print(' '.join(f'{TABLE + 4 * s:#x}:{word(FACTORY[s])}:{word(stubs[k])}'
                       for k in cfg for s in SLOTS[k]))
    elif cmd == 'quality':
        q = jpeg_q()
        if q is not None:
            print(' '.join(f'{a:#x}:{old:02x}30a0e3:{q:02x}30a0e3' for a, old in Q_MOVS.items()))
    else:
        sys.exit(__doc__)


assert crop_for('43', 1280, 960) == (1440, 1080) and crop_for('169', 1280, 720) == (1920, 1080)
assert crop_for('32', 640, 428) == (1616, 1080) and crop_for('11', 528, 528) == (1024, 1024)

if __name__ == '__main__':
    main()
