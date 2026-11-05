"""Run exif_write (exif_cave.s) in the emulator on a real photo's header.

    python3 tools/emu_exif.py IMG.jpg OUT.jpg [--no-clock]

Takes the photo's first 0x270 bytes (the camera's JPEG header) as the
template at 0xe2f50, enters at the patched tail call (0x18328) as
FUN_0001808c does, stubs write (records what is written) and the RTC
(2026-11-05 14:07:09, or -1 with --no-clock), plants an AE state (AE:
338 lines, gain 81, a WB preset), and runs the firmware's own
snprintf. Writes the recorded file plus the photo's scan data to OUT.jpg
and checks the layout; `exiftool -validate OUT.jpg` checks the EXIF.
"""
import os, struct, sys
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_LR,
                               UC_ARM_REG_PC, UC_ARM_REG_SP)
sys.argv[1:] = [a if a.startswith('-') else os.path.abspath(a) for a in sys.argv[1:]]
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FW = 'build/GP_CARDVR_UPGRADE.BIN'
APP = 0x10200
TPL, TPL_LEN = 0xe2f50, 0x270
HOOK_AT, WRITE, GETTIME = 0x18328, 0x385a0, 0x52bd4
EXIT, STACK, FD = 0xfff000, 0xf00000, 7
CLOCK = (9, 7, 14, 5, 11, 2026, 4)  # sec min hour mday mon year wday
AE_LINES, AE_GAIN, WB_MODE = 0x1241a4, 0x1241a0, 0x1321f8
AE = (338, 81, 3)  # 10 ms (1/100 s), gain 81/64 (ISO 126), a WB preset (manual)


def run(jpg, clock=True, ae=AE):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(0, 0x1000000)
    uc.mem_write(0, open(FW, 'rb').read()[APP:APP + 0x200000])
    uc.mem_write(TPL, jpg[:TPL_LEN])
    uc.mem_write(AE_LINES, struct.pack('<I', ae[0]))
    uc.mem_write(AE_GAIN, struct.pack('<I', ae[1]))
    uc.mem_write(WB_MODE, bytes([ae[2]]))
    out = bytearray()

    def ret(r0=None):
        if r0 is not None:
            uc.reg_write(UC_ARM_REG_R0, r0 & 0xffffffff)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def on_code(uc, addr, size, _):
        if addr == WRITE:
            fd, buf, n = (uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            assert fd == FD, fd
            out.extend(uc.mem_read(buf, n))
            ret()
        elif addr == GETTIME:
            uc.mem_write(uc.reg_read(UC_ARM_REG_R0), struct.pack('<7i', *CLOCK))
            ret(0 if clock else -1)
        elif addr == EXIT:
            uc.emu_stop()
    uc.hook_add(UC_HOOK_CODE, on_code)

    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_R0, FD)
    uc.reg_write(UC_ARM_REG_R1, TPL)
    uc.reg_write(UC_ARM_REG_R2, TPL_LEN)
    uc.reg_write(UC_ARM_REG_LR, EXIT)
    uc.emu_start(HOOK_AT, 0xffffffff, count=1_000_000)
    assert uc.reg_read(UC_ARM_REG_PC) == EXIT, 'did not return'
    assert uc.reg_read(UC_ARM_REG_SP) == STACK, 'stack not balanced'
    return bytes(out)


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    jpg = open(sys.argv[1], 'rb').read()
    head = run(jpg, clock='--no-clock' not in sys.argv)
    assert head[:2] == b'\xff\xd8' and head[2:4] == b'\xff\xe1', head[:4].hex()
    app1_len = 2 + struct.unpack('>H', head[4:6])[0]
    assert head[2 + app1_len:] == jpg[2:TPL_LEN], 'template after APP1 differs'
    open(sys.argv[2], 'wb').write(head + jpg[TPL_LEN:])
    print(f'ok: SOI + APP1 ({app1_len} B) + template ({TPL_LEN - 2} B) -> {sys.argv[2]}')
