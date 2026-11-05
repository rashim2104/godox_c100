@ One `bl HOOK` at AT (both from build.sh, --defsym), in place of a call:
@ the MOV metadata hooks (mov_meta.s). Encoded by hand: llvm-mc would leave a
@ relocation for `bl` (see docs/c100-firmware.md).
    .syntax unified
    .arm
    .org    AT
    .word   0xeb000000 | (((HOOK - AT - 8) >> 2) & 0xffffff)
