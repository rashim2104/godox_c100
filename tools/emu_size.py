#!/usr/bin/env python3
"""Check the built photo sizes and JPEG quality (tools/photo.py) in the emulator.

    SIZE43=1280x960 JPEG_Q=80 python3 tools/emu_size.py

Takes the same SIZE*/JPEG_Q as the build of build/GP_CARDVR_UPGRADE.BIN.
  1. Tables: video's (0xf0a0) is the default build's; the photo table's
     (0xf3d0) NORMAL slots (6, 7, 8, 10, 13) are the factory's aspect 0-4
     handlers; every other slot is the factory's, or for a set aspect its stub.
  2. Sizes: per aspect, enters the dispatch at 0xf3c8 with r6 = the slot and
     r4 = a garbage-filled size struct and runs to the photo path: a stub
     must reach 0xf188 with T = the output, C = S = photo.crop_for, mode 1,
     r6/r7 = T, r3/r2 = S; a factory handler must reach 0xf0f8 with its size.
  3. Quality: per quality setting (CFG + 0xb = 0, 1, 2) runs FUN_00011724
     (the photo encoder's init) and FUN_00015b38 (its Q tables, through the
     firmware's own IJG scaling FUN_0007f1b4; the encoder register loads are
     stubbed and recorded): Q must be JPEG_Q (or 98/90/80), and the template's
     DQT and the encoder's tables must be the IJG tables at that Q.
"""
import os, struct, sys
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_R4, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_LR,
                               UC_ARM_REG_PC, UC_ARM_REG_SP)
sys.path.insert(0, os.path.dirname(__file__))
import photo as P
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FW, ORIG = 'build/GP_CARDVR_UPGRADE.BIN', 'c100_v1.1.6_20260929/GP_CARDVR_UPGRADE.BIN'
APP = 0x10200
VTABLE, PTABLE, DISPATCH, PHOTO_PATH, STOCK_PATH = 0xf0a0, 0xf3d0, 0xf3c8, 0xf188, 0xf0f8
ENC_INIT, ENC_Q, LOAD_Y, LOAD_C = 0x11724, 0x15b38, 0x73bb0, 0x73c44
CFG, TPL, SIZE_PTR = 0x132160, 0xe2f50, 0xe11ec
NORMAL = {6: 0xf79c, 7: 0xf79c, 8: 0xf7b0, 10: 0xf7c4, 13: 0xf6d4}
VNORMAL = {6: 0xf5f8, 7: 0xf5f8, 8: 0xf6a8, 10: 0xf688, 13: 0xf698}
STOCK_SIZE = {0xf79c: (1920, 1080), 0xf7b0: (1616, 1080), 0xf7c4: (1440, 1080), 0xf6d4: (1024, 1024),
              0xf760: (3648, 2736), 0xf774: (3264, 2448)}
STRUCT, STACK, EXIT = 0xa00000, 0xf00000, 0xfff000
ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27,
          20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58,
          59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63]
STD_Y = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
         14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
         49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
STD_C = [17, 18, 24, 47] + [99] * 4 + [18, 21, 26, 66] + [99] * 4 + [24, 26, 56] + [99] * 5 + \
        [47, 66] + [99] * 38


def ijg(table, q):
    s = 5000 // q if q < 50 else 200 - 2 * q
    return [min(255, max(1, (v * s + 50) // 100)) for v in table]


def table(addr):
    return [struct.unpack_from('<I', FW_BYTES, APP + addr + 4 * i)[0] for i in range(16)]


def machine():
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(0, 0x1000000)
    uc.mem_write(0, FW_BYTES[APP:APP + 0x200000])
    uc.reg_write(UC_ARM_REG_SP, STACK)
    return uc


def run_to(uc, start, stops, count=2000):
    hit = {}

    def code(uc, addr, size, _):
        if addr in stops:
            hit['at'] = addr
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, code)
    uc.emu_start(start, 0, count=count)
    return hit.get('at')


def check_tables(cfg):
    orig = [struct.unpack_from('<I', open(ORIG, 'rb').read(), APP + VTABLE + 4 * i)[0] for i in range(16)]
    want_v = [VNORMAL.get(i, a) for i, a in enumerate(orig)]
    assert table(VTABLE) == want_v, 'video size table changed'
    pt = table(PTABLE)
    stub_slots = {s for k in cfg for s in P.SLOTS[k]}
    for i, a in enumerate(pt):
        if i in NORMAL:
            assert a == NORMAL[i], f'NORMAL slot {i}: {a:#x}'
        elif i in stub_slots:
            assert 0xbb340 <= a < 0xbb3f8, f'slot {i}: {a:#x} is not a size stub'
        else:
            assert a == P.FACTORY.get(i, struct.unpack_from('<I', open(ORIG, 'rb').read(),
                                                            APP + PTABLE + 4 * i)[0]), f'slot {i}: {a:#x}'
    print(f'ok: tables (video stock, NORMAL slots factory, stubs in {sorted(stub_slots) or "none"})')
    return pt


def check_sizes(cfg, pt):
    for k, slots in P.SLOTS.items():
        for s in slots:
            uc = machine()
            uc.mem_write(STRUCT, bytes([0xa5]) * 0x40)
            uc.reg_write(UC_ARM_REG_R4, STRUCT)
            uc.reg_write(UC_ARM_REG_R6, s)
            at = run_to(uc, DISPATCH, {PHOTO_PATH, STOCK_PATH})
            h = lambda o: struct.unpack_from('<H', uc.mem_read(STRUCT + o, 2))[0]
            T, C, S = (h(14), h(16)), (h(10), h(12)), (h(6), h(8))
            if k in cfg:
                (cw, ch), (w, hh) = cfg[k]
                regs = tuple(uc.reg_read(r) for r in (UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R3, UC_ARM_REG_R2))
                assert at == PHOTO_PATH, f'slot {s}: stopped at {at}'
                assert T == (w, hh) and C == S == (cw, ch), f'slot {s}: T{T} C{C} S{S}'
                assert uc.mem_read(STRUCT + 4, 1)[0] == 1 and regs == (w, hh, cw, ch), f'slot {s}: {regs}'
                print(f'ok: slot {s:2} ({k}) -> {w}x{hh} from crop {cw}x{ch}')
            else:
                assert at == STOCK_PATH, f'slot {s}: stopped at {at}'
                width = uc.reg_read(UC_ARM_REG_R3) & 0xffff
                assert (width, h(16)) == STOCK_SIZE[pt[s]], f'slot {s}: {width}x{h(16)}'
                print(f'ok: slot {s:2} ({k}) factory {width}x{h(16)}')


def check_quality():
    want = P.jpeg_q()
    for setting, factory in ((0, 98), (1, 90), (2, 80)):
        q = factory if want is None else want
        uc = machine()
        uc.mem_write(CFG + 0xb, bytes([setting]))
        uc.mem_write(SIZE_PTR, struct.pack('<I', STRUCT + 0x100))
        loads = {}

        def code(uc, addr, size, _):
            if addr in (LOAD_Y, LOAD_C):
                tab = uc.reg_read(UC_ARM_REG_R2)
                loads[addr] = list(struct.unpack('<64H', uc.mem_read(tab, 128)))
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        uc.hook_add(UC_HOOK_CODE, code)
        uc.reg_write(UC_ARM_REG_R0, STRUCT)
        uc.reg_write(UC_ARM_REG_LR, EXIT)
        uc.emu_start(ENC_INIT, EXIT, count=10000)
        qy, qc = struct.unpack('<II', uc.mem_read(STRUCT + 0xcc, 8))
        assert (qy, qc) == (q, q), f'setting {setting}: Q {qy}/{qc}, want {q}'
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR),
                        (0, qy, qc, STACK, EXIT)):
            uc.reg_write(r, v)
        uc.emu_start(ENC_Q, EXIT, count=100000)
        ey, ec = ijg(STD_Y, q), ijg(STD_C, q)
        dqt = uc.mem_read(TPL, 0x270)
        assert list(dqt[0x27:0x67]) == [ey[z] for z in ZIGZAG], f'Q{q}: luma DQT'
        assert list(dqt[0x6c:0xac]) == [ec[z] for z in ZIGZAG], f'Q{q}: chroma DQT'
        assert loads == {LOAD_Y: ey, LOAD_C: ec}, f'Q{q}: encoder tables'
        print(f'ok: quality setting {setting} -> Q{q} (DQT and encoder tables, luma[0..3] {ey[:4]})')


if __name__ == '__main__':
    FW_BYTES = open(FW, 'rb').read()
    cfg = P.config()
    check_sizes(cfg, check_tables(cfg))
    check_quality()
