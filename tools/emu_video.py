#!/usr/bin/env python3
"""Run the built video look (tools/patches/video_look.s) in an ARM emulator
and check it against tools/digicam.py.

    uv run --with unicorn,numpy,pillow tools/emu_video.py PHOTO.jpg

Loads build/GP_CARDVR_UPGRADE.BIN and stubs what the cave calls (cache
maintenance, pvPortMalloc, the RTC, the ISP's gamma and colour matrix
reloads). Per mode (nor, CCD, Y2K, a value that is not a mode, CCD with the
clock not set, and CCD with the buffer a photo already allocated):
  1. runs rec_start from the bl at 0x35e30: the ISP must get the mode's
     profile, in CCD/Y2K the stamp buffer must be digicam.render of the
     clock, and it must reach video_encode_record_start (0xfb28) with its
     registers, return address and stack arguments untouched;
  2. builds a video frame from the photo (at its own size) in the camera's
     YUV 4:2:0 layout and runs the frame hook (FUN_00018d14) on it, twice:
     as one whole-frame buffer (the stock sizes) and as 64-row strips with one
     timestamp per frame (the scaler's strips); each frame must be the photo
     with digicam.apply_stamp (or untouched without a stamp), every pixel,
     with the cache invalidated before and cleaned after the rows it writes.
Reports the hook's instructions per frame (~310 M instructions/s on the
camera).
"""
import os, struct, sys
import numpy as np
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP)
sys.path.insert(0, os.path.dirname(__file__))
import digicam as D
from emu_digicam import symbols
sys.argv[1:] = [a if a.startswith('-') else os.path.abspath(a) for a in sys.argv[1:]]
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FW = 'build/GP_CARDVR_UPGRADE.BIN'
APP = 0x10200
CALL_AT, REC_START, RESUME = 0x35e30, 0xfb28, 0x18d18
CACHE_INV, CACHE_CLEAN, MALLOC, GETTIME = 0x401ac, 0x401b8, 0x5374c, 0x52bd4
GAMMA_SET, CCM_SET = 0x981fc, 0x982a4
CFG_MODE = 0x132160 + 0xf1
ISP_CTX, CTX = 0x12846c, 0xa00000
VENC = 0x131490
FRAME, HEAP, OLDBUF, STACK = 0x400000, 0x800000, 0x880000, 0xf00000
STRIP = 64
CLOCK = (9, 7, 14, 5, 11, 2026, 4)  # sec min hour mday mon year wday
ARGS = (0x11111111, 0x22222222, 0x33333333, 0x44444444)
STACK_ARGS = (0x55555555, 0xffffffff)


def machine(clock_set):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(0, 0x1000000)
    uc.mem_write(0, open(FW, 'rb').read()[APP:APP + 0x200000])
    uc.mem_write(ISP_CTX, struct.pack('<I', CTX))
    calls = []

    def ret(r0=None):
        if r0 is not None:
            uc.reg_write(UC_ARM_REG_R0, r0 & 0xffffffff)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def on_code(uc, addr, size, _):
        if addr in (CACHE_INV, CACHE_CLEAN):
            calls.append(('inv' if addr == CACHE_INV else 'clean', uc.reg_read(UC_ARM_REG_R0),
                          uc.reg_read(UC_ARM_REG_R1)))
            ret()
        elif addr == MALLOC:
            calls.append(('malloc', uc.reg_read(UC_ARM_REG_R0), 0))
            ret(HEAP)
        elif addr == GETTIME:
            uc.mem_write(uc.reg_read(UC_ARM_REG_R0), struct.pack('<7i', *CLOCK))
            ret(0 if clock_set else -1)
        elif addr in (GAMMA_SET, CCM_SET):
            off = 0x177c if addr == GAMMA_SET else 0x1794
            calls.append(('gamma' if addr == GAMMA_SET else 'ccm',
                          struct.unpack('<I', uc.mem_read(CTX + off, 4))[0], 0))
            ret()
        elif addr in (REC_START, RESUME):
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, on_code)
    return uc, calls


def regs(uc):
    return tuple(uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))


def rec_start(uc):
    """The patched bl at 0x35e30, as FUN_00035dbc makes it; True if it reaches
    FUN_0000fb28 exactly as the stock bl would."""
    sp = STACK - 8
    uc.mem_write(sp, struct.pack('<2I', *STACK_ARGS))
    uc.reg_write(UC_ARM_REG_SP, sp)
    for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), ARGS):
        uc.reg_write(r, v)
    uc.emu_start(CALL_AT, 0xffffffff, count=100_000_000)
    return (uc.reg_read(UC_ARM_REG_PC) == REC_START and regs(uc) == ARGS
            and uc.reg_read(UC_ARM_REG_SP) == sp and uc.reg_read(UC_ARM_REG_LR) == CALL_AT + 4
            and struct.unpack('<2I', uc.mem_read(sp, 8)) == STACK_ARGS)


def hook(uc, vhook, buf, rows, ts):
    """FUN_00018d14(venc, ts) with buf (rows of the frame) in the encode struct;
    True if it resumes at 0x18d18 with the replaced ldr r3, [r0] done."""
    uc.mem_write(VENC + 8, struct.pack('<I', buf | 0x30000000))
    uc.mem_write(VENC + 0xd0, struct.pack('<I', rows))
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_R0, VENC)
    uc.reg_write(UC_ARM_REG_R1, ts)
    uc.emu_start(vhook, 0xffffffff, count=100_000_000)
    return (uc.reg_read(UC_ARM_REG_PC) == RESUME and uc.reg_read(UC_ARM_REG_SP) == STACK
            and regs(uc)[:2] == (VENC, ts) and regs(uc)[3] == 1)


def pack(Y, UV):
    """Planes -> the camera's layout: per 2-row band, even row = luma + the
    first half of the chroma pairs, odd row = the second half + luma."""
    H, W = Y.shape
    uv = UV.reshape(H // 2, W)
    out = np.empty((H // 2, 2, W * 3 // 2), np.uint8)
    out[:, 0, :W], out[:, 0, W:] = Y[0::2], uv[:, :W // 2]
    out[:, 1, :W // 2], out[:, 1, W // 2:] = uv[:, W // 2:], Y[1::2]
    return out.tobytes()


def unpack(buf, H, W):
    b = np.frombuffer(buf, np.uint8).reshape(H // 2, 2, W * 3 // 2)
    Y = np.empty((H, W), np.uint8)
    Y[0::2], Y[1::2] = b[:, 0, :W], b[:, 1, W // 2:]
    UV = np.concatenate([b[:, 0, W:], b[:, 1, :W // 2]], axis=1).reshape(H // 2, W // 2, 2)
    return Y, UV


def main():
    ycc = np.asarray(Image.open(sys.argv[1]).convert('YCbCr'))
    H, W = ycc.shape[0] & ~1, ycc.shape[1] & ~3
    ycc = ycc[:H, :W]
    Y0 = ycc[..., 0].copy()
    UV0 = (ycc[..., 1:].astype(int).reshape(H // 2, 2, W // 2, 2, 2).sum(axis=(1, 3)) // 4).astype(np.uint8)
    frame = pack(Y0, UV0)
    stride = W * 3 // 2
    dsym, vsym = symbols('build/obj/digicam_cave.o'), symbols('build/obj/video_look.o')
    fw = open(FW, 'rb').read()
    word = lambda a: struct.unpack_from('<I', fw, APP + a)[0]
    profiles = [struct.unpack_from('<2I', fw, APP + dsym['PROFILES'] + 8 * k) for k in range(len(D.MODES))]
    assert profiles[0] == (0xd8050, 0xd6338)
    assert word(0x18d14) == 0xea000000 | ((vsym['vhook'] - 0x18d14 - 8) >> 2) & 0xffffff, 'frame hook jump'
    assert word(CALL_AT) == 0xeb000000 | ((vsym['rec_start'] - CALL_AT - 8) >> 2) & 0xffffff, 'record start jump'
    ref = D.render(CLOCK[5], CLOCK[4], CLOCK[3], CLOCK[2], CLOCK[1])
    wY, wU, wV = Y0.copy(), UV0[..., 0].copy(), UV0[..., 1].copy()
    D.apply_stamp(wY, wU, wV, ref)
    ok, most = True, 0
    for mode, clock_set, old in [(0, True, False), (1, True, False), (2, True, False), (7, True, False),
                                 (1, False, False), (1, True, True)]:
        k = mode if mode < len(D.MODES) else 0
        uc, calls = machine(clock_set)
        steps = [0]
        uc.hook_add(UC_HOOK_BLOCK, lambda uc_, a, size, _: steps.__setitem__(0, steps[0] + size // 4))
        uc.mem_write(CFG_MODE, bytes([mode]))
        uc.mem_write(dsym['VARS'] + 4, struct.pack('<I', OLDBUF if old else 0))
        uc.mem_write(VENC, struct.pack('<I', 1))
        uc.mem_write(VENC + 0x101, b'#')
        uc.mem_write(VENC + 0xdc, struct.pack('<2I', W, H))
        good = rec_start(uc)
        isp = [(n, v) for n, v, _ in calls if n in ('gamma', 'ccm')]
        good &= isp == [('gamma', profiles[k][0]), ('ccm', profiles[k][1])]
        stamped = k > 0 and clock_set
        mallocs = [c for c in calls if c[0] == 'malloc']
        good &= mallocs == ([('malloc', D.SW * D.SH, 0)] if k > 0 and not old else [])
        if stamped:
            good &= bytes(uc.mem_read(OLDBUF if old else HEAP, D.SW * D.SH)) == ref
        want = (wY, wU, wV) if stamped else (Y0, UV0[..., 0], UV0[..., 1])
        report = []
        for name, rows in (('frame', H), ('strips', STRIP)):
            for f in range(2):                          # two frames: the row count starts over
                uc.mem_write(FRAME, frame)
                calls.clear()
                steps[0] = 0
                ts = 1000 + 36 * f
                for y in range(0, H, rows):
                    good &= hook(uc, vsym['vhook'], FRAME + y * stride, rows, ts)
                per = steps[0]
                if name == 'frame':
                    most = max(most, per)
                Y, UV = unpack(bytes(uc.mem_read(FRAME, len(frame))), H, W)
                diff = int((Y != want[0]).sum() + (UV[..., 0] != want[1]).sum() + (UV[..., 1] != want[2]).sum())
                good &= diff == 0
                cache = [c[0] for c in calls]
                good &= cache == (['inv', 'clean'] * max(1, len(cache) // 2) if stamped else [])
                if stamped:                             # inv/clean cover the stamp's rows, same ranges
                    lo = min(c[1] for c in calls) - FRAME
                    hi = max(c[1] + c[2] for c in calls) - FRAME
                    _, y0 = D.stamp_origin(W, H)
                    good &= lo <= y0 * stride and hi >= (y0 + D.SH) * stride and hi - lo <= (D.SH + rows) * stride
                    good &= all(calls[i][1:] == calls[i + 1][1:] for i in range(0, len(calls), 2))
                report.append(f'{name} {f}: {diff} differing, {per / 1e3:.0f} k')
        changed = int((unpack(bytes(uc.mem_read(FRAME, len(frame))), H, W)[0] != Y0).sum())
        good &= (changed > 0) == stamped
        ok &= good
        print(f'mode {mode} ({D.MODES[k]}{", clock not set" if not clock_set else ""}'
              f'{", buffer from a photo" if old else ""}): ISP {isp == [("gamma", profiles[k][0]), ("ccm", profiles[k][1])]}, '
              f'stamp {"on" if stamped else "off"}, {changed} luma changed; {"; ".join(report)}'
              f'{"" if good else "  FAILED"}')
    print(f'{W}x{H}: up to {most / 1e3:.0f} k instructions per frame (~{most / 310e3:.2f} ms)')
    print('video test', 'PASSED' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
