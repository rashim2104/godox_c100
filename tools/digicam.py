#!/usr/bin/env python3
"""The camera's modes (nor, CCD, Y2K): their ISP profiles, display codes and
the digicam date stamp. Generates digicam.inc for the caves and is the exact
reference the emulator check (emu_digicam.py) compares the firmware against.

    python3 tools/digicam.py asm                         # digicam.inc
    python3 tools/digicam.py preview IN.jpg OUT_PREFIX   # rough look on a nor photo

ISP profile = an RGB gamma table and a colour matrix, which snap
(digicam_cave.s) hands to the ISP before every photo (stock ones in nor).

Gamma (0xd8050, 0x90 bytes): 3 channels (R, G, B) x 32 8-bit knots, then 3 x
16 segment bytes (bits 0-4 the segment's first knot, bits 5-6 sh: 2^sh knots
over its 64 input codes; 10-bit in, implicit knot 0 = 0). A profile keeps the
stock segments and knot inputs and puts its 8-bit tone curve T_c after the
stock curve: knot_c = T_c(stock knot), so T_c works on display values.

CCM (0xd6338): 9 signed shorts, row-major, 0x80 = 1.0 (each row sums ~128).
A profile is S(sat) . stock, S keeping luma (BT.601 weights) per row.

Stamp: "DD MM 'YY" in slanted 7-segment digits with a two-ring glow, rendered
once per photo into an SW x SH coverage buffer (0..255), then blended into the
photo's bottom right by the strip hook: luma toward STAMP_Y (never darker),
each 2x2 block's chroma toward STAMP_U/V, by the coverage of its top-left pixel.
"""
import struct, sys

FW = 'build_backups/v001_original.bin'
APP = 0x10200
GAMMA_AT, CCM_AT = 0xd8050, 0xd6338
MODES = ['nor', 'CCD', 'Y2K']


def stock():
    d = open(FW, 'rb').read()
    g = d[APP + GAMMA_AT:APP + GAMMA_AT + 0x90]
    return g, struct.unpack('<9h', d[APP + CCM_AT:APP + CCM_AT + 18])


def clamp(x, lo=0, hi=255):
    return max(lo, min(hi, x))


def interp(points, x):
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def rgb_offset(dcb, dcr):
    """A (Cb, Cr) shift as (dR, dG, dB), BT.601 full range."""
    return 1.402 * dcr, -0.344 * dcb - 0.714 * dcr, 1.772 * dcb


# CCD: a 2005 compact, cool and punchy. Black point 10, white 236 (hard clip,
# no shoulder), an S-curve, a light cool cast fading out at black and white.
def ccd_tone(v):
    y = clamp((v - 10) / 226, 0, 1)
    y += 0.5 * y * (1 - y) * (2 * y - 1)
    return 255 * y


def ccd_cast(y):
    w = 4 * (y / 255) * (1 - y / 255)      # 0 at black and white, 1 at mid
    dr, dg, db = rgb_offset(2.0, -1.5)
    return dr * w, dg * w, db * w


# Y2K: faded and warm. Blacks lifted to 22, a soft shoulder to 240, a warm
# cast, warm-brown shadows and cream highlights.
Y2K_POINTS = [(0, 22), (16, 39), (32, 55), (64, 85), (96, 112), (128, 139), (160, 165),
              (192, 193), (216, 216), (232, 229), (255, 240)]


def y2k_tone(v):
    return interp(Y2K_POINTS, v)


def y2k_cast(y):
    dcb, dcr = -6, 4
    s = max(0, 1 - y / 128)                 # shadows: #3A3226 at 50%
    h = max(0, (y - 128) / 127)             # highlights: #FFE6B8 at 60%
    dcb += s * -4 * 0.5 + h * -10 * 0.6
    dcr += s * 3 * 0.5 + h * 6 * 0.6
    return rgb_offset(dcb, dcr)


PROFILES = {
    'CCD': dict(tone=ccd_tone, cast=ccd_cast, sat=(1.15, 1.15, 1.15)),
    'Y2K': dict(tone=y2k_tone, cast=y2k_cast, sat=(0.9, 0.85, 0.9)),
}


def curves(p):
    """T_c for c in R, G, B: 256-entry lists."""
    out = [[], [], []]
    for v in range(256):
        y = p['tone'](v)
        for c, d in enumerate(p['cast'](y)):
            out[c].append(clamp(y + d))
    return out


def gamma(p):
    g, _ = stock()
    t = curves(p)
    knots = bytearray()
    for c in range(3):
        last = 0
        for k in g[c * 32:c * 32 + 32]:
            last = max(last, round(t[c][k]))       # keep it monotonic
            knots.append(last)
    return bytes(knots) + g[96:]


def ccm(p):
    _, m = stock()
    L = (0.299, 0.587, 0.114)
    out = []
    for r in range(3):
        s = p['sat'][r]
        srow = [(1 - s) * L[k] + s * (k == r) for k in range(3)]
        for c in range(3):
            out.append(clamp(round(sum(srow[k] * m[k * 3 + c] for k in range(3))), -511, 511))
    return out


# ---- The display: the mode's code on the shutter-speed (SS) readout's three
# 7-segment cells, blank in photo and video mode. ----
SEG7 = {'n': 'ceg', 'o': 'cdeg', 'r': 'eg', 'C': 'adef', 'd': 'bcdeg', 'Y': 'bcdfg', '2': 'abdeg',
        'K': 'acefg'}
LCD = {'nor': 'nor', 'CCD': 'CCd', 'Y2K': 'Y2K'}
# Segment -> (HT1621 address, COM) for each SS cell, left to right, found by
# running the firmware's SS digit routines (FUN_0004a374, FUN_0004a1f0,
# FUN_0004a074) for 0..9 in tools/emu_seg.py. Each cell is wired differently.
# Addresses 0x0d..0x13 hold nothing but these 21 segments.
SS_CELLS = [
    {'a': (0x0d, 0), 'b': (0x0e, 0), 'c': (0x0f, 2), 'd': (0x0e, 2), 'e': (0x0d, 2), 'f': (0x0d, 1), 'g': (0x0e, 1)},
    {'a': (0x0f, 0), 'b': (0x10, 0), 'c': (0x11, 1), 'd': (0x11, 2), 'e': (0x10, 2), 'f': (0x0f, 1), 'g': (0x10, 1)},
    {'a': (0x12, 0), 'b': (0x13, 0), 'c': (0x13, 1), 'd': (0x13, 2), 'e': (0x12, 2), 'f': (0x11, 0), 'g': (0x12, 1)},
]
SS_FIRST, SS_COUNT = 0x0d, 7    # HT1621 addresses written


def lcd_segments(mode):
    return [SEG7[g] for g in LCD[mode]]


def lcd_nibbles(segments):
    """Nibbles for HT1621 addresses 0x0d..0x13 that light `segments` (one
    string of a..g per SS cell) (COM0 = nibble bit 8, COM1 = 4, COM2 = 2)."""
    nib = [0] * SS_COUNT
    for cell, segs in zip(SS_CELLS, segments):
        for seg in segs:
            addr, com = cell[seg]
            nib[addr - SS_FIRST] |= 8 >> com
    return nib


# ---- The stamp ----
DH, DW, PAD = 34, 18, 4                     # digit height, width; the glow's room
SEGS = [(2, 0, 16, 4), (14, 2, 18, 16), (14, 18, 18, 32), (2, 30, 16, 34),   # a b c d
        (0, 18, 4, 32), (0, 2, 4, 16), (2, 15, 16, 19), (0, 0, 4, 10)]       # e f g, and '
DIGITS = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f]
APOS = 0x80
RINGS = [(3, 56), (1, 128), (0, 255)]       # (grow by, coverage): glow, glow, core
ADV_APOS, ADV_DIGIT, ADV_SPACE = 12, 26, 16
SW = (PAD + ADV_APOS + 3 * (2 * ADV_DIGIT + ADV_SPACE) - ADV_SPACE - 8 + 5 + PAD + 1) // 2 * 2
SH = DH + 2 * PAD
MARGIN = 40                                 # from the photo's right and bottom edges
STAMP_Y, STAMP_U, STAMP_V = 176, 60, 196    # a hot orange LED (#FF8C1A, a bit brighter)


def slant(y):
    """x shift of buffer row y: 0 at the digits' bottom, 5 at their top."""
    yy = clamp(y - PAD, 0, DH - 1)
    return ((DH - 1 - yy) * 43) >> 8


def render(year, mon, day):
    buf = bytearray(SW * SH)

    def fill(x0, y0, x1, y1, v):
        for y in range(max(0, y0), min(SH, y1)):
            s = slant(y)
            for x in range(max(0, x0 + s), min(SW, x1 + s)):
                buf[y * SW + x] = max(buf[y * SW + x], v)

    def glyph(x, mask):
        for seg in range(8):
            if mask >> seg & 1:
                x0, y0, x1, y1 = SEGS[seg]
                for e, v in RINGS:
                    fill(x + x0 - e, PAD + y0 - e, x + x1 + e, PAD + y1 + e, v)

    x = PAD
    for n in (day, mon, None, year % 100):
        if n is None:
            glyph(x, APOS)
            x += ADV_APOS
            continue
        glyph(x, DIGITS[n // 10])
        x += ADV_DIGIT
        glyph(x, DIGITS[n % 10])
        x += ADV_DIGIT + ADV_SPACE
    return bytes(buf)


def stamp_origin(w, h):
    return (w - MARGIN - SW) & ~1, (h - MARGIN - SH) & ~1


def blend_y(y, c):
    return STAMP_Y - (((STAMP_Y - y) * (256 - c)) >> 8) if y < STAMP_Y else y


def blend_c(u, t, c):
    return u + (((t - u) * c) >> 8)


def apply_stamp(Y, U, V, cov):
    """In place on full planes (Y: h x w, U/V: h/2 x w/2 numpy uint8 arrays)."""
    h, w = Y.shape
    x0, y0 = stamp_origin(w, h)
    for sy in range(SH):
        for sx in range(SW):
            c = cov[sy * SW + sx]
            if not c:
                continue
            Y[y0 + sy, x0 + sx] = blend_y(int(Y[y0 + sy, x0 + sx]), c)
            if sy % 2 == 0 and sx % 2 == 0:
                by, bx = (y0 + sy) // 2, (x0 + sx) // 2
                U[by, bx] = blend_c(int(U[by, bx]), STAMP_U, c)
                V[by, bx] = blend_c(int(V[by, bx]), STAMP_V, c)


def asm():
    print(f'    .equ    NMODES, {len(MODES)}')
    for k, v in dict(SW=SW, SH=SH, DH=DH, PAD=PAD, MARGIN=MARGIN, STAMP_Y=STAMP_Y, STAMP_U=STAMP_U,
                     STAMP_V=STAMP_V, ADV_APOS=ADV_APOS, ADV_DIGIT=ADV_DIGIT, ADV_SPACE=ADV_SPACE,
                     APOS=APOS).items():
        print(f'    .equ    {k}, {v}')
    print(f'    .equ    SS_FIRST, {SS_FIRST:#x}\n    .equ    SS_COUNT, {SS_COUNT}')
    print('    .macro  LCD_TAG_DATA                  @ per mode: HT1621 nibbles for the SS cells')
    for m in MODES:
        print('    .byte   ' + ', '.join(map(str, lcd_nibbles(lcd_segments(m)))) + f'   @ {m}')
    print('    .endm')
    print('    .macro  STAMP_DATA')
    print('SEGS:                                    @ x0, y0, x1, y1 per segment a..g, then the apostrophe')
    for s in SEGS:
        print('    .byte   ' + ', '.join(map(str, s)))
    print('RINGS:                                   @ grow by, coverage')
    for e, v in RINGS:
        print(f'    .byte   {e}, {v}')
    print('DIGITS:\n    .byte   ' + ', '.join(f'{d:#04x}' for d in DIGITS))
    print('    .align  2')
    for name, p in PROFILES.items():
        g = gamma(p)
        print(f'GAMMA_{name}:                           @ {name}: RGB gamma (0x90 bytes)')
        for i in range(0, len(g), 16):
            print('    .byte   ' + ', '.join(f'{b:#04x}' for b in g[i:i + 16]))
        print(f'CCM_{name}:                             @ {name}: colour matrix, 0x80 = 1.0')
        print('    .short  ' + ', '.join(map(str, ccm(p))))
        print('    .align  2')
    print('    .endm')


def preview(src, prefix):
    """Rough: T_c and the saturation on the normal photo's display values
    (the camera does the matrix before its gamma)."""
    from PIL import Image
    im = Image.open(src).convert('RGB')
    L = (0.299, 0.587, 0.114)
    for name, p in PROFILES.items():
        t = curves(p)
        px = im.load()
        out = Image.new('RGB', im.size)
        o = out.load()
        for y in range(im.size[1]):
            for x in range(im.size[0]):
                rgb = px[x, y]
                lum = sum(a * b for a, b in zip(L, rgb))
                rgb = [clamp(round(lum + p['sat'][c] * (rgb[c] - lum))) for c in range(3)]
                o[x, y] = tuple(round(t[c][rgb[c]]) for c in range(3))
        out.save(f'{prefix}_{name}.jpg', quality=92)


def check():
    g, m = stock()
    for name, p in PROFILES.items():
        gm = gamma(p)
        assert len(gm) == 0x90 and gm[96:] == g[96:], name
        for c in range(3):
            k = gm[c * 32:c * 32 + 25]
            assert all(a <= b for a, b in zip(k, k[1:])), (name, c)
        rows = ccm(p)
        for r in range(3):
            assert abs(sum(rows[r * 3:r * 3 + 3]) - sum(m[r * 3:r * 3 + 3])) <= 2, (name, r)
    t = curves(PROFILES['CCD'])
    assert t[1][5] == 0 and t[1][240] == 255          # crushed blacks, hard clip
    t = curves(PROFILES['Y2K'])
    assert 20 <= t[1][0] <= 24 and t[1][255] <= 242   # lifted blacks, soft white
    assert t[0][128] > t[2][128]                      # warm
    assert all(slant(y) == (DH - 1 - clamp(y - PAD, 0, DH - 1)) // 6 for y in range(SH))
    b = render(2026, 11, 5)
    assert SW * SH % 4 == 0 and SW % 2 == 0          # snap clears it in words; X0 even
    last = max(x for x in range(SW) for y in range(SH) if b[y * SW + x])
    assert last < SW - 1, last                                         # fits
    assert b[(PAD + 1) * SW + PAD + 4 * ADV_DIGIT + 2 * ADV_SPACE + 6] == 255   # the apostrophe is lit


if __name__ == '__main__':
    check()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'asm':
        asm()
    elif cmd == 'preview':
        preview(sys.argv[2], sys.argv[3])
    elif cmd == 'stamp':
        from PIL import Image
        Image.frombytes('L', (SW, SH), render(2026, 11, 5)).resize((SW * 4, SH * 4)).save(sys.argv[2])
    else:
        sys.exit(__doc__)
