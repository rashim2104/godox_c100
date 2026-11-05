@ fx_strip (photo_cave.s) for 4x4 blocks (FX_PIX4), at a fixed address
@ (0xbb774, in the dead FUN_000bb774), as fx_strip jumps here. From its stack
@ frame and registers: r11 = strip, r7 = stride, r8 = third, r12 = table,
@ r5 = paint colours, r4 = row buffer, [sp] = the sharpening weight. A row of
@ 4x4 blocks is 2 bands; their luma is read as words (two bytes per 16-bit
@ lane) and painted as words, so the strip must be word aligned (it is; else
@ it is left alone). Ends as fx_strip's fxdone.
    .syntax unified
    .arm
    .include "palettes.inc"                      @ MAX_BLOCKS
    .include "look.inc"                          @ VARS offsets, CLAMP, SHARPEN, LOOKUP
base:
    .equ    PVARS,       PVARS_ADDR              @ photo cave VARS (from build.sh)

    .org    0xbb774
fx4:
    tst     r11, #3
    bne     4f
    mov     r10, #0                       @ r10 = a row of 4x4 blocks, 0..15
fx4row:
    sub     lr, r12, #YMAP_BYTES          @ lr = the luma map
    ldr     r6, =0x00FF00FF
    mov     r9, #0                        @ r9 = block c, x = 4c
1:  add     r2, r11, r9, lsl #2
    mov     r0, #0
    @ the 4 rows: the upper band's even and odd, the lower band's
    ldr     r1, [r2]
    and     r3, r1, r6
    add     r0, r0, r3
    and     r3, r6, r1, lsr #8
    add     r0, r0, r3
    add     r2, r2, r7
    add     r2, r2, r8
    ldr     r1, [r2]
    and     r3, r1, r6
    add     r0, r0, r3
    and     r3, r6, r1, lsr #8
    add     r0, r0, r3
    add     r2, r2, r7
    sub     r2, r2, r8
    ldr     r1, [r2]
    and     r3, r1, r6
    add     r0, r0, r3
    and     r3, r6, r1, lsr #8
    add     r0, r0, r3
    add     r2, r2, r7
    add     r2, r2, r8
    ldr     r1, [r2]
    and     r3, r1, r6
    add     r0, r0, r3
    and     r3, r6, r1, lsr #8
    add     r0, r0, r3
    add     r0, r0, r0, lsr #16
    mov     r0, r0, lsl #16
    mov     r0, r0, lsr #20               @ the 16 luma's mean
    ldrb    r0, [lr, r0]
    strb    r0, [r4, r9]
    add     r9, r9, #1
    cmp     r9, r8, lsr #1
    blo     1b
    PAD     r8, lsr #1
    ldr     lr, =PVARS + DITHER
    and     r0, r10, #3
    add     lr, lr, r0, lsl #2            @ lr = this row's 4 dither offsets
    mov     r9, #0
2:  ldrb    r0, [r4, r9]
    SHARPEN
    and     r1, r9, #3
    ldrsb   r1, [lr, r1]
    add     r0, r0, r1
    CLAMP
    str     r0, [sp, #-4]!
    mov     r3, r9, lsl #1                @ its first 2x2 column's pair: in the even
    cmp     r3, r8, lsr #1                @  row's chroma, or the odd row's
    addlo   r6, r11, r8, lsl #1
    addlo   r6, r6, r3, lsl #1
    subhs   r3, r3, r8, lsr #1
    addhs   r6, r11, r7
    addhs   r6, r6, r3, lsl #1            @ r6 = the upper band's 2 pairs (+ 2 stride: the lower's)
    add     r0, r6, r7, lsl #1
    ldrb    r1, [r6]                      @ U: the 4 pairs' mean
    ldrb    r3, [r6, #2]
    add     r1, r1, r3
    ldrb    r3, [r0]
    add     r1, r1, r3
    ldrb    r3, [r0, #2]
    add     r1, r1, r3
    ldrb    r2, [r6, #1]                  @ V
    ldrb    r3, [r6, #3]
    add     r2, r2, r3
    ldrb    r3, [r0, #1]
    add     r2, r2, r3
    ldrb    r3, [r0, #3]
    add     r2, r2, r3
    mov     r1, r1, lsr #2
    mov     r2, r2, lsr #2
    ldr     r0, [sp], #4
    LOOKUP
    orr     r1, r1, r2, lsl #8            @ paint: the 4 pairs, U V U V
    orr     r1, r1, r1, lsl #16
    str     r1, [r6]
    str     r1, [r6, r7, lsl #1]
    orr     r0, r0, r0, lsl #8            @ the 16 luma, 4 per row
    orr     r0, r0, r0, lsl #16
    add     r3, r11, r9, lsl #2
    str     r0, [r3]
    add     r3, r3, r7
    str     r0, [r3, r8]
    add     r3, r3, r7
    str     r0, [r3]
    add     r3, r3, r7
    str     r0, [r3, r8]
    add     r9, r9, #1
    cmp     r9, r8, lsr #1
    blo     2b
    add     r11, r11, r7, lsl #2          @ next row: 2 bands
    add     r10, r10, #1
    cmp     r10, #16
    blo     fx4row
4:  add     sp, sp, #4                    @ fx_strip's fxdone
    pop     {r0-r12, pc}
    .ltorg
