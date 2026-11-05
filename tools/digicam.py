#!/usr/bin/env python3
"""The camera's modes (nor, CCD, Y2K, BW, NGT, SUN): their ISP profiles, display codes and
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

Stamp: "DD MM 'YY" (STAMP_ORDER, STAMP_TIME, STAMP_COLOR below: build-time
environment variables) in italic, anti-aliased 7-segment digits with a faint glow,
rendered once per photo into an SW x SH coverage buffer (0..255), then blended
into the photo's bottom right by the strip hook: luma by blend_y (the glow only
lightens, the core covers), each 2x2 block's chroma toward STAMP_U/V by its
mean coverage.
"""
import os, struct, sys

FW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build_backups/v001_original.bin')
APP = 0x10200
GAMMA_AT, CCM_AT = 0xd8050, 0xd6338
MODES = ['nor', 'CCD', 'Y2K', 'BW', 'NGT', 'SUN']


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


# BW: punchy black and white. No colour at all (the matrix's rows are the luma
# weights), black point 8, white 248, a strong S-curve, a faint warm paper
# tone in the mid-tones.
def bw_tone(v):
    y = clamp((v - 8) / 240, 0, 1)
    y += 0.7 * y * (1 - y) * (2 * y - 1)
    return 255 * y


def bw_cast(y):
    w = 4 * (y / 255) * (1 - y / 255)
    return tuple(d * w for d in rgb_offset(-1.0, 0.8))


# NGT: a cold night. Blacks crushed below 14, the mids pushed down (power
# 1.4), white held at 245, a teal-blue cast that fades in from black (so
# black stays black) and eases off in the highlights, saturation x0.8.
def ngt_tone(v):
    y = clamp((v - 14) / 236, 0, 1)
    return 245 * y ** 1.4


def ngt_cast(y):
    w = min(1, 3 * y / 255) * (1 - 0.5 * y / 255)
    return tuple(d * w for d in rgb_offset(9, -6))


# SUN: a disposable film camera in the sun. Lifted blacks (18), bright mids,
# a soft shoulder to 246, a golden cast (more yellow in the highlights, a
# touch of red in the shadows), saturation x1.1.
SUN_POINTS = [(0, 18), (32, 46), (64, 80), (96, 114), (128, 146), (160, 177), (192, 205),
              (224, 229), (255, 246)]


def sun_tone(v):
    return interp(SUN_POINTS, v)


def sun_cast(y):
    s = max(0, 1 - y / 128)
    h = max(0, (y - 128) / 127)
    return rgb_offset(-10 - 6 * h, 5 + 2 * s)


PROFILES = {
    'CCD': dict(tone=ccd_tone, cast=ccd_cast, sat=(1.15, 1.15, 1.15)),
    'Y2K': dict(tone=y2k_tone, cast=y2k_cast, sat=(0.9, 0.85, 0.9)),
    'BW': dict(tone=bw_tone, cast=bw_cast, sat=(0, 0, 0)),
    'NGT': dict(tone=ngt_tone, cast=ngt_cast, sat=(0.8, 0.8, 0.8)),
    'SUN': dict(tone=sun_tone, cast=sun_cast, sat=(1.1, 1.1, 1.1)),
}


# Beyond gamma and matrix, per mode (docs "More of the look"): the CDSP edge
# enhancer's amp gain (0 = stock .. 3), the YUV sharpen gain (stock 0x20), and
# flags: HbNr off, the YUV NR thresholds low (grain), lens shading off (the
# lens's own falloff: darker corners).
LOOK_HBNR_OFF, LOOK_NR_LOW, LOOK_LSC_OFF = 1, 2, 4
LOOKS = {
    'nor': (0, 0x20, 0),
    'CCD': (2, 0x40, LOOK_HBNR_OFF | LOOK_NR_LOW | LOOK_LSC_OFF),
    'Y2K': (1, 0x30, LOOK_LSC_OFF),
    'BW': (2, 0x40, LOOK_HBNR_OFF | LOOK_NR_LOW | LOOK_LSC_OFF),
    'NGT': (1, 0x20, LOOK_NR_LOW | LOOK_LSC_OFF),
    'SUN': (0, 0x20, LOOK_LSC_OFF),
}
NR_STOCK, LSC_STOCK = 0xd62e4, 0xd6a9c      # ctx+0x17a8 and ctx+0x17b0 at init
NR_STOCK_LEVEL0 = (1, 3, 5, 6)


def nr_table(low):
    """The YUV NR thresholds per gain level (36 shorts, 7 per level: three
    fixed, then the four thresholds); low: every threshold halved (min 1)."""
    fw = open(FW, 'rb').read()
    t = list(struct.unpack_from('<36H', fw, APP + NR_STOCK))
    if low:
        for lv in range(5):
            t[lv * 7 + 3:lv * 7 + 7] = [max(1, v // 2) for v in t[lv * 7 + 3:lv * 7 + 7]]
    return t


def look_calls(mode, profiles, lsc_before, level=0):
    """What isp_profile calls after the gamma and matrix for mode index `mode`
    (PROFILES at `profiles`), with ctx+0x17b0 at `lsc_before` and the gain
    tuner at `level` (ctx+0x1530, -1..3): (name, args)."""
    n = len(MODES)
    ampga, sharp, flags = LOOKS[MODES[mode]]
    lsc = profiles + 12 * n if flags & LOOK_LSC_OFF else LSC_STOCK
    nr = profiles + 12 * n + 8 if flags & LOOK_NR_LOW else NR_STOCK
    ints = (sharp, sharp - 3, sharp - 7, sharp - 10)
    row = 7 * max(0, min(4, level + 1)) + 3
    out = [('edge', (ampga,)), ('sharp', (ints[max(0, min(3, level))],)),
           ('hbnr', (0 if flags & LOOK_HBNR_OFF else 1,)),
           ('nr', tuple(nr_table(flags & LOOK_NR_LOW)[row:row + 4]))]
    if lsc != lsc_before:
        out.append(('lsc', (lsc,)))
    return out, dict(sharp_ints=ints, nr=nr, lsc=lsc)


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
# 7-segment cells, blank in photo and video mode. A code is one glyph per
# cell; W takes two cells, its left half 'W<' and right half 'W>'. ----
SEG7 = {'n': 'ceg', 'o': 'cdeg', 'r': 'eg', 'C': 'adef', 'd': 'bcdeg', 'Y': 'bcdfg', '2': 'abdeg',
        'K': 'acefg', 'b': 'cdefg', 'W<': 'cdef', 'W>': 'bcde', 'G': 'acdef', 't': 'defg',
        'S': 'acdfg', 'U': 'bcdef'}
LCD = {'nor': 'nor', 'CCD': 'CCd', 'Y2K': 'Y2K', 'BW': ['b', 'W<', 'W>'], 'NGT': 'nGt', 'SUN': 'SUn'}
# Segment -> (HT1621 address, COM) for each 7-segment cell, left to right:
# ISO 1-2, F 1-2, SS 1-3, found by running the firmware's digit routines
# (FUN_00049ea8, FUN_0004a4ec, FUN_0004a074, FUN_0004a374, FUN_0004a1f0) for
# 0..9 in tools/emu_seg.py. Each cell is wired differently. Addresses
# 0x0d..0x13 hold nothing but the SS cells' 21 segments.
CELLS = [
    {'a': (0x01, 0), 'b': (0x02, 1), 'c': (0x02, 2), 'd': (0x01, 2), 'e': (0x00, 2), 'f': (0x00, 1), 'g': (0x01, 1)},
    {'a': (0x04, 0), 'b': (0x05, 1), 'c': (0x05, 2), 'd': (0x04, 2), 'e': (0x03, 2), 'f': (0x03, 1), 'g': (0x04, 1)},
    {'a': (0x07, 0), 'b': (0x08, 0), 'c': (0x09, 1), 'd': (0x08, 2), 'e': (0x07, 2), 'f': (0x07, 1), 'g': (0x08, 1)},
    {'a': (0x0a, 0), 'b': (0x0b, 0), 'c': (0x0b, 1), 'd': (0x0b, 2), 'e': (0x0a, 2), 'f': (0x09, 0), 'g': (0x0a, 1)},
    {'a': (0x0d, 0), 'b': (0x0e, 0), 'c': (0x0f, 2), 'd': (0x0e, 2), 'e': (0x0d, 2), 'f': (0x0d, 1), 'g': (0x0e, 1)},
    {'a': (0x0f, 0), 'b': (0x10, 0), 'c': (0x11, 1), 'd': (0x11, 2), 'e': (0x10, 2), 'f': (0x0f, 1), 'g': (0x10, 1)},
    {'a': (0x12, 0), 'b': (0x13, 0), 'c': (0x13, 1), 'd': (0x13, 2), 'e': (0x12, 2), 'f': (0x11, 0), 'g': (0x12, 1)},
]
SS_CELLS = CELLS[4:]
# The boot splash, in place of the GODOX logo: "rASHIM" over all 7 cells (M
# over two: its left and right halves).
SPLASH = ['eg', 'abcefg', 'acdfg', 'bcefg', 'ef', 'abef', 'abcf']
NSPLASH = 0x14          # HT1621 addresses the cells use, 0x00..0x13
SS_FIRST, SS_COUNT = 0x0d, 7    # HT1621 addresses written


def lcd_segments(mode):
    return [SEG7[g] for g in LCD[mode]]


def splash_nibbles():
    """Nibbles for HT1621 addresses 0..NSPLASH-1 that light SPLASH."""
    nib = [0] * NSPLASH
    for cell, segs in zip(CELLS, SPLASH):
        for seg in segs:
            addr, com = cell[seg]
            nib[addr] |= 8 >> com
    return nib


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
# A digicam's date imprint: italic seven-segment digits with pointed ends and
# hairline gaps, anti-aliased, with a faint warm glow. Geometry in 1/16 px
# (Q); every step is integer maths the cave repeats exactly.
Q = 16
DH, DW, PAD = 46, 26, 4                     # digit height, width (px); the glow's room
TH = 48                                     # half the stroke (Q, 3 px)
SL = 48                                     # italic: x shift per unit of height, /256
R = 40                                      # glow reach beyond the edge (Q, 2.5 px)
GLOW = 88                                   # coverage at the edge's glow, < 128
# Per segment a..g, then the apostrophe: centre x, centre y, half length to
# the tip (Q), vertical. A segment is a hexagon: |across| <= TH and
# |along| + |across| <= half length.
SEGS = [(208, 48, 144, 0), (368, 208, 144, 1), (368, 528, 144, 1), (208, 688, 144, 0),
        (48, 528, 144, 1), (48, 208, 144, 1), (208, 368, 144, 0), (48, 96, 80, 1),
        (48, 208, 56, 1), (48, 528, 56, 1)]              # the colon's dots
DIGITS = [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f]
APOS, COLON = 0x80, 0x300
ADV_APOS, ADV_DIGIT, ADV_SPACE = 14, 32, 14

# Build-time options (environment variables, read by build.sh's `digicam.py
# asm` and by the emulator check alike):
#   STAMP_ORDER  dmy (default) "05 11 '26", ymd "'26 11 05", mdy "11 05 '26"
#   STAMP_TIME   0 (default), 1: the time after a gap, "05 11 '26  14:07"
#   STAMP_COLOR  orange (default), red, yellow, green: the LED's Y, U, V
F_MIN, F_HOUR, F_DAY, F_MON, F_YEAR = 4, 8, 12, 16, 20     # offsets into the RTC's int t[7]
G_APOS, G_COLON, F_END = 0x80, 0x81, 0xff
ORDERS = {'dmy': [F_DAY, F_MON, G_APOS, F_YEAR], 'ymd': [G_APOS, F_YEAR, F_MON, F_DAY],
          'mdy': [F_MON, F_DAY, G_APOS, F_YEAR]}
COLORS = {'orange': (170, 50, 202),         # a deep orange LED, ~RGB (255, 144, 32)
          'red': (110, 89, 231),            # ~RGB (255, 50, 40)
          'yellow': (210, 32, 160),         # ~RGB (255, 220, 40)
          'green': (178, 78, 44)}           # ~RGB (60, 255, 90)
STAMP_ORDER = os.environ.get('STAMP_ORDER', 'dmy')
STAMP_TIME = os.environ.get('STAMP_TIME', '0')
STAMP_COLOR = os.environ.get('STAMP_COLOR', 'orange')
if STAMP_ORDER not in ORDERS or STAMP_TIME not in ('0', '1') or STAMP_COLOR not in COLORS:
    sys.exit(f'digicam.py: STAMP_ORDER {"|".join(ORDERS)}, STAMP_TIME 0|1, STAMP_COLOR {"|".join(COLORS)}')


def fields():
    """The stamp's layout: (what, x's extra advance after it) per item; what =
    an RTC field (two digits, then x past them and a space), G_APOS or
    G_COLON. With the time: a gap, the hour, the colon centred between the
    hour and the minute, the minute."""
    out = [(f, ADV_APOS if f == G_APOS else 0) for f in ORDERS[STAMP_ORDER]]
    if STAMP_TIME == '1':
        out[-1] = (out[-1][0], out[-1][1] + ADV_SPACE)
        out += [(F_HOUR, -15), (G_COLON, 11), (F_MIN, 0)]      # colon at hour + 63 px, minute + 74
    return out
FIELDS = fields()


def layout():
    """(x, what) per item of FIELDS."""
    out, x = [], PAD
    for f, extra in FIELDS:
        out.append((x, f))
        x += (0 if f in (G_APOS, G_COLON) else 2 * ADV_DIGIT + ADV_SPACE) + extra
    return out


SW = layout()[-1][0] + 76                   # the last pair (58 px), the italic's lean, the glow, room
SH = DH + 2 * PAD
MARGIN = 40                                 # from the photo's right and bottom edges
STAMP_Y, STAMP_U, STAMP_V = COLORS[STAMP_COLOR]


def lut():
    """Coverage by signed distance d from a segment's edge (Q), at d + 8:
    the core's anti-aliased edge 255..128 over d in [-8, 8), then the glow
    GLOW..0 out to R."""
    t = []
    for i in range(16 + R + 1):
        d = i - 8
        t.append(128 + ((8 - d) * 127 >> 4) if d < 8 else GLOW * (R - d + 8) ** 2 // (R * R))
    return t
LUT = lut()
NLUT = len(LUT)


def coverage(seg, gx, x, y):
    cx, cy, hl, vert = seg
    ly = (y - PAD) * Q + 8
    sh = ((DH * Q - ly) * SL) >> 8
    du = abs((x - gx) * Q + 8 - sh - cx)
    dv = abs(ly - cy)
    d = max((du if vert else dv) - TH, ((du + dv - hl) * 181) >> 8)
    i = d + 8
    return 255 if i < 0 else LUT[i] if i < NLUT else 0


def glyphs(year, mon, day, hour=0, minute=0):
    """(x, segment mask) per glyph of the stamp, e.g. "DD MM 'YY"."""
    val = {F_DAY: day, F_MON: mon, F_YEAR: year % 100, F_HOUR: hour, F_MIN: minute}
    out = []
    for x, f in layout():
        if f in (G_APOS, G_COLON):
            out.append((x, APOS if f == G_APOS else COLON))
        else:
            out += [(x, DIGITS[val[f] // 10]), (x + ADV_DIGIT, DIGITS[val[f] % 10])]
    return out


def render(year, mon, day, hour=0, minute=0):
    """The coverage buffer (SW x SH bytes): the max over every lit segment,
    evaluated at every pixel."""
    buf = bytearray(SW * SH)
    for gx, mask in glyphs(year, mon, day, hour, minute):
        for k in range(len(SEGS)):
            if mask >> k & 1:
                for y in range(SH):
                    for x in range(SW):
                        c = coverage(SEGS[k], gx, x, y)
                        if c > buf[y * SW + x]:
                            buf[y * SW + x] = c
    return bytes(buf)


def render_boxed(year, mon, day, hour=0, minute=0):
    """render as the cave does it: each segment only over its box, row by row
    (must equal render)."""
    buf = bytearray(SW * SH)
    for gx, mask in glyphs(year, mon, day, hour, minute):
        for k in range(len(SEGS)):
            if not mask >> k & 1:
                continue
            cx, cy, hl, vert = SEGS[k]
            along, across = hl + 2 * R + 24, TH + R + 16
            ex, ey = (across, along) if vert else (along, across)
            for y in range(max(0, PAD - 1 + ((cy - ey) >> 4)), min(SH, PAD + 2 + ((cy + ey) >> 4))):
                sh = ((DH * Q - ((y - PAD) * Q + 8)) * SL) >> 8
                for x in range(max(0, gx - 1 + ((cx - ex + sh) >> 4)), min(SW, gx + 2 + ((cx + ex + sh) >> 4))):
                    c = coverage(SEGS[k], gx, x, y)
                    if c > buf[y * SW + x]:
                        buf[y * SW + x] = c
    return bytes(buf)


def stamp_origin(w, h):
    return (w - MARGIN - SW) & ~1, (h - MARGIN - SH) & ~1


def blend_y(y, c):
    """Glow (c < 128) only lightens, toward STAMP_Y by c/128; the core (c >=
    128) lights fully, then covers by (c - 128) * 2 / 256, also over brighter
    ground."""
    if c < 128:
        return y + (((STAMP_Y - y) * c) >> 7) if y < STAMP_Y else y
    if y < STAMP_Y:
        t = STAMP_Y - y
        y = STAMP_Y - t + ((11 * t) >> 4)
    return y + (((STAMP_Y - y) * ((c - 128) * 2)) >> 8)


def blend_c(u, t, c):
    return u + (((t - u) * c) >> 8)


def apply_stamp(Y, U, V, cov):
    """In place on full planes (Y: h x w, U/V: h/2 x w/2 numpy uint8 arrays);
    chroma by the mean coverage of each 2x2 block."""
    h, w = Y.shape
    x0, y0 = stamp_origin(w, h)
    for sy in range(SH):
        for sx in range(SW):
            c = cov[sy * SW + sx]
            if c:
                Y[y0 + sy, x0 + sx] = blend_y(int(Y[y0 + sy, x0 + sx]), c)
    for sy in range(0, SH, 2):
        for sx in range(0, SW, 2):
            o = sy * SW + sx
            c = (cov[o] + cov[o + 1] + cov[o + SW] + cov[o + SW + 1]) >> 2
            if c:
                by, bx = (y0 + sy) // 2, (x0 + sx) // 2
                U[by, bx] = blend_c(int(U[by, bx]), STAMP_U, c)
                V[by, bx] = blend_c(int(V[by, bx]), STAMP_V, c)


def asm():
    print(f'    .equ    NMODES, {len(MODES)}')
    for k, v in dict(SW=SW, SH=SH, DH=DH, PAD=PAD, TH=TH, SL=SL, R=R, NLUT=NLUT, MARGIN=MARGIN,
                     STAMP_Y=STAMP_Y, STAMP_U=STAMP_U, STAMP_V=STAMP_V, ADV_APOS=ADV_APOS,
                     ADV_DIGIT=ADV_DIGIT, ADV_SPACE=ADV_SPACE, APOS=APOS, COLON=COLON,
                     G_APOS=G_APOS, F_END=F_END).items():
        print(f'    .equ    {k}, {v}')
    print(f'    .equ    SS_FIRST, {SS_FIRST:#x}\n    .equ    SS_COUNT, {SS_COUNT}')
    print('    .macro  LCD_TAG_DATA                  @ per mode: HT1621 nibbles for the SS cells')
    for m in MODES:
        print('    .byte   ' + ', '.join(map(str, lcd_nibbles(lcd_segments(m)))) + f'   @ {m}')
    print('    .endm')
    print(f'    .equ    NSPLASH, {NSPLASH:#x}')
    print('    .macro  SPLASH_DATA                   @ boot splash: HT1621 nibbles for addresses 0..NSPLASH-1')
    print('    .byte   ' + ', '.join(map(str, splash_nibbles())))
    print('    .endm')
    print('    .macro  STAMP_DATA')
    print('    .align  1')
    print('SEGS:                                    @ per segment a..g, then the apostrophe: cx, cy, half length, vertical (Q)')
    for sg in SEGS:
        print('    .short  ' + ', '.join(map(str, sg)))
    print('LUT:                                     @ coverage by distance from the edge + 8 (Q)')
    for k in range(0, NLUT, 16):
        print('    .byte   ' + ', '.join(map(str, LUT[k:k + 16])))
    print('DIGITS:\n    .byte   ' + ', '.join(f'{d:#04x}' for d in DIGITS))
    print(f'FIELDS:                                 @ {STAMP_ORDER}, time {STAMP_TIME}: per item what, x\'s extra advance')
    print('    .byte   ' + ', '.join(f'{f:#04x}, {e & 0xff}' for f, e in FIELDS + [(F_END, 0)]))
    print('    .endm')
    print('    .macro  PROFILE_DATA')
    print('    .align  2')
    print('PROFILES:                               @ per mode: gamma, colour matrix (nor: the stock ones)')
    print('    .word   0xd8050, 0xd6338')
    for name in PROFILES:
        print(f'    .word   GAMMA_{name} - base, CCM_{name} - base')
    print('LOOKS:                                  @ per mode: edge amp gain, sharpen gain, flags, 0')
    for m in MODES:
        print('    .byte   ' + ', '.join(map(str, LOOKS[m] + (0,))) + f'   @ {m}')
    print('LSC_ZERO:                               @ lens shading strengths 0: no correction')
    print('    .short  0, 0, 0, 0')
    print('NR_LOW:                                 @ the YUV NR thresholds, all 1')
    print('    .short  ' + ', '.join(map(str, nr_table(True))))
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
    names = sys.argv[4:] or PROFILES
    for name in names:
        p = PROFILES[name]
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
    assert list(PROFILES) == MODES[1:]
    assert list(LOOKS) == MODES and LOOKS['nor'] == (0, 0x20, 0)
    assert all(0 <= e <= 3 and 10 <= g <= 0x7f for e, g, _ in LOOKS.values())
    assert nr_table(False)[3:7] == list(NR_STOCK_LEVEL0) and len(nr_table(True)) == 36
    assert len(set(SEG7.values())) == len(SEG7)        # emu_seg reads glyphs back
    assert all(len(LCD[m]) == len(SS_CELLS) for m in MODES)
    t = curves(PROFILES['CCD'])
    assert t[1][5] == 0 and t[1][240] == 255          # crushed blacks, hard clip
    t = curves(PROFILES['Y2K'])
    assert 20 <= t[1][0] <= 24 and t[1][255] <= 242   # lifted blacks, soft white
    assert t[0][128] > t[2][128]                      # warm
    rows = ccm(PROFILES['BW'])
    assert rows[0:3] == rows[3:6] == rows[6:9]        # no colour
    t = curves(PROFILES['BW'])
    assert t[1][8] == 0 and t[1][248] == 255 and t[1][64] < 50 and t[1][192] > 205   # punchy
    assert 0 <= t[0][128] - t[2][128] <= 4                                         # near neutral
    t = curves(PROFILES['NGT'])
    assert all(t[c][14] == 0 for c in range(3)) and t[1][128] < 112 and t[1][255] <= 246
    assert t[2][128] > t[0][128] + 6                  # cold
    t = curves(PROFILES['SUN'])
    assert 16 <= t[1][0] <= 20 and t[1][255] <= 248 and t[1][128] > 140
    assert t[0][128] > t[2][128] + 15 and t[1][200] > t[2][200]   # golden
    b = render(2026, 11, 5, 14, 7)
    assert b == render_boxed(2026, 11, 5, 14, 7)
    for date in [(2088, 12, 28, 23, 59), (2000, 1, 1, 0, 0), (2099, 8, 30, 10, 48)]:
        assert render(*date) == render_boxed(*date), date
    assert all(-128 <= e < 128 for _, e in FIELDS)
    assert SW * SH % 4 == 0 and SW % 2 == 0 and SH % 2 == 0          # snap clears in words; blocks
    assert max(LUT) <= 255 and LUT[0] == 255 and LUT[15] >= 128 > LUT[16] == GLOW and LUT[-1] == 0
    for date in [(2088, 12, 28, 23, 58), (2000, 1, 1, 0, 0)]:
        c = render(*date)
        assert not any(c[y * SW + SW - 1] or c[y * SW] for y in range(SH))       # fits, with room
        assert not any(c[:SW]) and not any(c[-SW:])

if __name__ == '__main__':
    check()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'asm':
        asm()
    elif cmd == 'preview':
        preview(sys.argv[2], sys.argv[3])
    elif cmd == 'stamp':
        from PIL import Image
        Image.frombytes('L', (SW, SH), render(2026, 11, 5, 14, 7)).resize((SW * 4, SH * 4)).save(sys.argv[2])
    else:
        sys.exit(__doc__)
