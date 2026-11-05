#!/usr/bin/env python3
"""The digicam modes' ISP profiles (CCD, Y2K): an RGB gamma table and a colour
matrix each, which lut_fill (photo_cave.s) hands to the camera's ISP before
every photo (stock ones in every other mode).

    python3 tools/digicam.py asm              # digicam.inc: GAMMA_*, CCM_*
    python3 tools/digicam.py preview IN.jpg OUT_PREFIX   # rough look on a normal-mode photo

Gamma (0xd8050, 0x90 bytes): 3 channels (R, G, B) x 32 8-bit knots, then 3 x
16 segment bytes (bits 0-4 the segment's first knot, bits 5-6 sh: 2^sh knots
over its 64 input codes; 10-bit in, implicit knot 0 = 0). A profile keeps the
stock segments and knot inputs and puts its 8-bit tone curve T_c after the
stock curve: knot_c = T_c(stock knot). So T_c works on display values, as
the looks are specified (see the research notes in docs/c100-firmware.md).

CCM (0xd6338): 9 signed shorts, row-major, 0x80 = 1.0 (each row sums ~128).
A profile is S(sat) . stock, S keeping luma (BT.601 weights) per row.
"""
import struct, sys

FW = 'build_backups/v001_original.bin'
APP = 0x10200
GAMMA_AT, CCM_AT = 0xd8050, 0xd6338


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
# no shoulder), an S-curve, a cool cast fading out at black and white.
def ccd_tone(v):
    y = clamp((v - 10) / 226, 0, 1)
    y += 0.5 * y * (1 - y) * (2 * y - 1)
    return 255 * y


def ccd_cast(y):
    w = 4 * (y / 255) * (1 - y / 255)      # 0 at black and white, 1 at mid
    dr, dg, db = rgb_offset(3.8, -3.3)
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
    'CCD': dict(tone=ccd_tone, cast=ccd_cast, sat=(1.15, 1.15, 1.25)),
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


def asm():
    for name, p in PROFILES.items():
        g = gamma(p)
        print(f'    .align  2\nGAMMA_{name}:                           @ {name}: RGB gamma (0x90 bytes)')
        for i in range(0, len(g), 16):
            print('    .byte   ' + ', '.join(f'{b:#04x}' for b in g[i:i + 16]))
        print(f'    .align  2\nCCM_{name}:                             @ {name}: colour matrix, 0x80 = 1.0')
        print('    .short  ' + ', '.join(map(str, ccm(p))))


def preview(src, prefix):
    """Rough: T_c and the saturation on the normal photo's display values
    (the camera does the matrix before its gamma)."""
    from PIL import Image
    im = Image.open(src).convert('RGB')
    for name, p in PROFILES.items():
        t = curves(p)
        L = (0.299, 0.587, 0.114)
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


if __name__ == '__main__':
    check()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'asm':
        asm()
    elif cmd == 'preview':
        preview(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
