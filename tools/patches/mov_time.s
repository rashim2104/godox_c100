@ Video (MOV) dates in UTC, from the camera's clock (EXIF=1).
@
@ The mvhd writer FUN_00088078 turns the file's FAT time (local) into
@ seconds since 1904 and then takes off 8 hours (sub #0x7000, sub #0x80 at
@ 0x88188), as if the clock ran on China time. The tkhd and mdhd writers
@ don't use the clock at all: they write 0xb9e3b1ce (2002-10-29 03:32:30)
@ from the literal pools at 0x88bd0 (tkhd, loads at 0x8884c, 0x88868) and
@ 0x88f9c (mdhd, loads at 0x88c28, 0x88c44), for every track.
@
@ This rewrites 0x88180-0x88194 in place (the code is unoptimised; the
@ ldr at 0x88184 only reloads what 0x88180 stored): take off the real UTC
@ offset (MOV_OFFSET seconds, from EXIF_OFFSET), then store the time into
@ both pools as well, so the tracks, written after mvhd, get the same date.
@ The pools are in RAM, as the caves' own variables are.
    .syntax unified
    .arm
    .org    0x88180
    .if MOV_OFFSET >= 0
    sub     r3, r3, #(MOV_OFFSET & 0xff00)
    sub     r3, r3, #(MOV_OFFSET & 0xff)
    .else
    add     r3, r3, #((-MOV_OFFSET) & 0xff00)
    add     r3, r3, #((-MOV_OFFSET) & 0xff)
    .endif
    str     r3, [pc, #(0x88bd0 - 0x88190)]    @ tkhd's date
    str     r3, [pc, #(0x88f9c - 0x88194)]    @ mdhd's date
    str     r3, [fp, #-0xc]                   @ mvhd's, as before
