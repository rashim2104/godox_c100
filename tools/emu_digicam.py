#!/usr/bin/env python3
"""Run the built digicam cave (tools/patches/digicam_cave.s) in an ARM
emulator and check it against tools/digicam.py.

    uv run --with unicorn,numpy,pillow tools/emu_digicam.py PHOTO.jpg

Loads build/GP_CARDVR_UPGRADE.BIN and stubs the firmware calls the cave makes
(cache maintenance, pvPortMalloc, the RTC, the ISP's gamma and colour matrix
reloads, which record what the ISP context points at). Per mode (nor, CCD,
Y2K, a value that is not a mode, and CCD with the clock not set):
  1. runs snap (the per-photo entry): the ISP must get the mode's profile,
     and in CCD/Y2K the stamp buffer must be digicam.render of the clock;
  2. packs the photo (at its own size, as the factory's) into 32-row strips
     in the camera's YUV 4:2:0 layout, alternating strip A and B, and runs the
     strip hook on each; the result must be the photo with digicam.apply_stamp
     (or untouched, without a stamp), every pixel.
Reports snap's instructions per photo and the hook's per strip (~310 M
instructions/s on the camera).
"""
import os, struct, subprocess, sys
import numpy as np
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP
sys.path.insert(0, os.path.dirname(__file__))
import digicam as D
sys.argv[1:] = [a if a.startswith('-') else os.path.abspath(a) for a in sys.argv[1:]]
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FW = 'build/GP_CARDVR_UPGRADE.BIN'
APP = 0x10200
RESUME, RESUME187 = 0x1544c, 0x187c8
CACHE_INV, CACHE_CLEAN, MALLOC, GETTIME = 0x401ac, 0x401b8, 0x5374c, 0x52bd4
GAMMA_SET, CCM_SET = 0x981fc, 0x982a4
PHOTO, STRIP_BYTES, SOF = 0x1317ac, 0x13155c, 0xe2f50
CFG_MODE = 0x132160 + 0xf1
ISP_CTX, CTX = 0x12846c, 0xa00000
STRIP_A, HEAP, STACK = 0x400000, 0x800000, 0xf00000
ROWS = 32
CLOCK = (9, 7, 14, 5, 11, 2026, 4)  # sec min hour mday mon year wday


def symbols(obj):
    nm = next(p for p in ('/opt/homebrew/opt/llvm/bin/llvm-nm', '/opt/homebrew/opt/llvm@18/bin/llvm-nm')
              if os.path.exists(p))
    out = subprocess.run([nm, obj], capture_output=True, text=True, check=True).stdout
    return {p[2]: int(p[0], 16) for p in map(str.split, out.splitlines()) if len(p) == 3}


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
        elif addr in (RESUME, RESUME187):
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, on_code)
    return uc, calls


def run(uc, entry, r0=0, r1=0):
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_R0, r0)
    uc.reg_write(UC_ARM_REG_R1, r1)
    uc.emu_start(entry, 0xffffffff, count=100_000_000)
    pc = uc.reg_read(UC_ARM_REG_PC)
    pushed = 24 if pc == RESUME187 else 4                         # the replaced push / str
    assert uc.reg_read(UC_ARM_REG_SP) == STACK - pushed, 'stack'
    return pc


def pack(Y, UV, y0):
    """Rows y0..y0+ROWS of the planes -> one strip: per 2-row band, even row =
    luma + the first half of the chroma pairs, odd row = the second half + luma."""
    W = Y.shape[1]
    out = bytearray()
    for b in range(ROWS // 2):
        uv = UV[y0 // 2 + b].reshape(-1)
        half = len(uv) // 2
        out += bytes(Y[y0 + 2 * b]) + bytes(uv[:half])
        out += bytes(uv[half:]) + bytes(Y[y0 + 2 * b + 1])
    assert len(out) == W * 3 // 2 * ROWS
    return bytes(out)


def unpack(buf, Y, UV, y0):
    W = Y.shape[1]
    third, stride = W // 2, W * 3 // 2
    for b in range(ROWS // 2):
        even = np.frombuffer(buf, np.uint8, stride, 2 * b * stride)
        odd = np.frombuffer(buf, np.uint8, stride, (2 * b + 1) * stride)
        Y[y0 + 2 * b], Y[y0 + 2 * b + 1] = even[:2 * third], odd[third:]
        UV[y0 // 2 + b] = np.concatenate([even[2 * third:], odd[:third]]).reshape(-1, 2)


def main():
    ycc = np.asarray(Image.open(sys.argv[1]).convert('YCbCr'))
    H, W = ycc.shape[0] // ROWS * ROWS, ycc.shape[1]
    ycc = ycc[:H]
    Y0 = ycc[..., 0].copy()
    UV0 = (ycc[..., 1:].astype(int).reshape(H // 2, 2, W // 2, 2, 2).sum(axis=(1, 3)) // 4).astype(np.uint8)
    sym = symbols('build/obj/digicam_cave.o')
    prof = sym['PROFILES']
    fw = open(FW, 'rb').read()
    profiles = [struct.unpack_from('<2I', fw, APP + prof + 8 * k) for k in range(len(D.MODES))]
    assert profiles[0] == (0xd8050, 0xd6338)
    ok, most = True, 0
    for mode, clock_set in [(0, True), (1, True), (2, True), (7, True), (1, False)]:
        k = mode if mode < len(D.MODES) else 0
        uc, calls = machine(clock_set)
        steps = [0]
        uc.hook_add(UC_HOOK_BLOCK, lambda uc_, a, size, _: steps.__setitem__(0, steps[0] + size // 4))
        uc.mem_write(CFG_MODE, bytes([mode]))
        hdr = bytearray(uc.mem_read(SOF, 16))
        hdr[7:11] = struct.pack('>HH', H, W)
        uc.mem_write(SOF, bytes(hdr))
        uc.mem_write(STRIP_BYTES, struct.pack('<I', W * ROWS * 3 // 2))
        uc.mem_write(PHOTO + 0x18, struct.pack('<I', STRIP_A))
        assert run(uc, sym['snap']) == RESUME187
        snap_steps = steps[0]
        isp = [(n, v) for n, v, _ in calls if n in ('gamma', 'ccm')]
        good = isp == [('gamma', profiles[k][0]), ('ccm', profiles[k][1])]
        stamped = k > 0 and clock_set
        if stamped:
            buf = bytes(uc.mem_read(HEAP, D.SW * D.SH))
            good &= buf == D.render(CLOCK[5], CLOCK[4], CLOCK[3])
        Y, UV = Y0.copy(), UV0.copy()
        bytes_ = W * ROWS * 3 // 2
        per = []
        for i, y0 in enumerate(range(0, H, ROWS)):
            at = STRIP_A + (i % 2) * bytes_
            uc.mem_write(at, pack(Y0, UV0, y0))
            calls.clear()
            steps[0] = 0
            assert run(uc, sym['hook'], r0=0x300000, r1=at) == RESUME
            per.append(steps[0])
            unpack(bytes(uc.mem_read(at, bytes_)), Y, UV, y0)
        most = max(most, max(per))
        wY, wU, wV = Y0.copy(), UV0[..., 0].copy(), UV0[..., 1].copy()
        if stamped:
            D.apply_stamp(wY, wU, wV, D.render(CLOCK[5], CLOCK[4], CLOCK[3]))
        dy = int((Y != wY).sum())
        duv = int((UV[..., 0] != wU).sum() + (UV[..., 1] != wV).sum())
        changed = int((Y != Y0).sum())
        good &= dy == 0 and duv == 0 and (changed > 0) == stamped
        ok &= good
        print(f'mode {mode} ({D.MODES[k]}{"" if clock_set else ", clock not set"}): ISP {isp == [("gamma", profiles[k][0]), ("ccm", profiles[k][1])]}, '
              f'stamp {"on" if stamped else "off"}, {changed} luma changed, differing from the reference: '
              f'{dy} luma, {duv} chroma, snap {snap_steps / 1e3:.0f} k instructions {"" if good else " FAILED"}')
    print(f'hook: up to {most / 1e3:.0f} k instructions per strip (~{most / 310e3:.2f} ms)')
    print('digicam test', 'PASSED' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
