@ Make, model and artist in every video (EXIF=1).
@
@ The MOV muxer writes moov as mvhd, then FUN_000884d8 (udta > meta > ilst
@ from a key/value table at ctx+0x540 that nothing ever fills, so it
@ writes nothing and returns 0), then the tracks; it does this twice
@ (bl at 0x8c910 sizes moov, bl at 0x8ca1c writes it) and adds the
@ returned length both times. mov_meta_jump points both calls here: copy
@ a fixed udta (tools/exif.py udta: (c)mak, (c)mod, (c)ART as QuickTime
@ international text, which exiftool and Apple read as Make, Model and
@ Artist) to the buffer and return its length. The table stays empty, so
@ the muxer's close (FUN_0008ecd0, which frees its entries) is unchanged.
@
@ In the end of the video cave's dead range, after video_cave.s.
    .syntax unified
    .arm
    .org    0xbbaa0
mov_meta:                                 @ r0 = muxer ctx, r1 = buffer
    adr     r2, UDTA
    mov     r3, #0
1:  ldrb    ip, [r2, r3]
    strb    ip, [r1, r3]
    add     r3, r3, #1
    cmp     r3, #UDTA_LEN
    bne     1b
    mov     r0, r3
    bx      lr
    .include "udta.inc"
