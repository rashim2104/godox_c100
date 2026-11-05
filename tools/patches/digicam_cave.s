@ The digicam modes (tools/digicam.py): nor, CCD, Y2K, BW, NGT and SUN,
@ chosen with the center button (lcd_cave.s; the mode is byte 0xf1 of the
@ camera's saved settings, anything else counts as nor). Every mode takes the
@ factory's sizes.
@
@ snap (cyc_jump.s: FUN_000187c4, the capture handler, once per photo,
@ camera task): hand the ISP the mode's profile (isp_profile, tables in
@ profile_data.s), and in every mode but nor render the date stamp, "DD MM
@ 'YY" from the RTC (STAMP_ORDER, STAMP_TIME), into a coverage buffer (SW x
@ SH bytes, allocated once).
@
@ hook (hook_jump.s: FUN_00015448, the scaler's "strip ready" callback,
@ interrupt): each call hands over one finished strip (FUN_0001523c queues one
@ buffer per call), strip A at PHOTO+0x18 or B after it, STRIP_BYTES each,
@ YUV 4:2:0 laid out as docs/c100-firmware.md "Strip buffer format". The
@ photo's width and height come from the JPEG header's SOF0 (0xe2f50, filled
@ by FUN_0001808c before the capture); a strip's rows = STRIP_BYTES / (1.5 W),
@ and V_ROW counts the rows handed over so far. Rows that cross the stamp's
@ rectangle (bottom right, MARGIN from the edges) get it blended in:
@ luma by blend_y (the glow only lightens, the core covers), each 2x2 block's
@ chroma toward STAMP_U/V by its mean coverage; tools/digicam.py apply_stamp
@ is the exact reference.
    .syntax unified
    .arm
    .include "digicam.inc"                @ NMODES, SW, SH, ..., STAMP_DATA
base:
    .set    RESUME,      base + 0x1544c
    .set    RESUME187,   base + 0x187c8
    .set    CACHE_INV,   base + 0x401ac
    .set    CACHE_CLEAN, base + 0x401b8
    .set    MALLOC,      base + 0x5374c   @ pvPortMalloc(size, align)
    .set    GETTIME,     base + 0x52bd4   @ RTC: int t[7] (sec min hour mday mon year wday); 0 = set
    .set    GAMMA_SET,   base + 0x981fc   @ ISP: load the gamma at ctx+0x177c
    .set    CCM_SET,     base + 0x982a4   @ ISP: load the colour matrix at ctx+0x1794
    .set    EDGE_SET,    base + 0x9852c   @ CDSP edge enhancer, r0 = amp gain 0..3
    .set    SHARP_SET,   base + 0x914e8   @ YUV sharpen gain (reg 0x290 byte 2)
    .set    HBNR_SET,    base + 0x915b0   @ HbNr on/off
    .set    NR_SET,      base + 0x90af8   @ YUV NR thresholds (4 args)
    .set    LSC_SET,     base + 0x98810   @ lens shading, regenerated from ctx+0x17b0
    .equ    PHOTO,       0x1317ac
    .equ    STRIP_BYTES, 0x13155c
    .equ    SOF,         0xe2f50          @ JPEG header: height at +7, width at +9 (big-endian)
    .equ    ISP_CTX,     0x12846c         @ -> the ISP context
    .equ    CFG,         0x132160         @ the camera's settings
    .equ    CFG_MODE,    0xf1
    .equ    V_ROW,       0                @ offsets into VARS
    .equ    V_BUF,       4
    .equ    V_ON,        8

    .org    0xbab6c
hook:
    push    {r0-r11, lr}                  @ r0-r3 are the callback's live args
    sub     r3, r0, #0x200000
    cmp     r3, #0xe00000
    bhs     done
    ldr     r4, =PHOTO
    ldr     r6, =STRIP_BYTES
    ldr     r6, [r6]                      @ r6 = a strip's bytes
    cmp     r6, #96
    bls     done
    ldr     r5, [r4, #0x18]
    cmp     r1, r5                        @ strip A
    addne   r5, r5, r6
    cmpne   r1, r5                        @  or B
    bne     done
    mov     r11, r1                       @ r11 = the strip
    ldr     r0, =SOF
    ldrb    r2, [r0, #9]
    ldrb    r3, [r0, #10]
    orr     r8, r3, r2, lsl #8            @ r8 = W
    ldrb    r2, [r0, #7]
    ldrb    r3, [r0, #8]
    orr     r9, r3, r2, lsl #8            @ r9 = H
    adds    r7, r8, r8, lsr #1            @ r7 = stride, 1.5 W
    beq     done
    mov     r5, #0                        @ r5 = the strip's rows
    mov     r0, r6
1:  subs    r0, r0, r7
    addhs   r5, r5, #1
    bhi     1b
    ldr     r10, =VARS - base
    ldr     r4, [r10, #V_ROW]             @ r4 = the strip's first row
    add     r0, r4, r5
    str     r0, [r10, #V_ROW]
    ldrb    r0, [r10, #V_ON]
    cmp     r0, #0
    beq     done
    ldr     r10, [r10, #V_BUF]            @ r10 = the stamp
    sub     r9, r9, #MARGIN + SH
    bic     r9, r9, #1                    @ r9 = the stamp's top row, Y0
    cmp     r4, r9
    movge   r2, r4
    movlt   r2, r9                        @ r2 = first row to do
    add     r3, r4, r5
    add     r0, r9, #SH
    cmp     r3, r0
    movgt   r3, r0                        @ r3 = past the last
    cmp     r2, r3
    bge     done
    push    {r2, r3, r6, r9}              @ [sp] = row, +4 end, +8 bytes, +12 Y0
    mov     r0, r11
    mov     r1, r6
    mov     lr, pc
    b       CACHE_INV
    sub     r6, r8, #MARGIN
    sub     r6, r6, #SW
    bic     r6, r6, #1                    @ r6 = the stamp's left column, X0
row:
    ldr     r2, [sp]
    sub     r0, r2, r4                    @ the row in the strip
    bic     r0, r0, #1
    mul     r5, r0, r7
    add     r5, r5, r11                   @ r5 = its band's even row
    ldr     r1, [sp, #12]
    sub     r1, r2, r1                    @ the row in the stamp
    mov     r0, #SW
    mla     r12, r1, r0, r10              @ r12 = its coverage
    tst     r2, #1
    moveq   lr, r5                        @ even row: luma at [0, W)
    addne   lr, r5, r7                    @ odd row: at [W/2, 1.5 W) of the next
    addne   lr, lr, r8, lsr #1
    add     lr, lr, r6                    @ lr = luma at X0
    mov     r0, #0
2:  ldrb    r1, [r12, r0]                 @ coverage
    cmp     r1, #0
    beq     3f
    ldrb    r3, [lr, r0]
    cmp     r1, #128
    bhs     6f
    cmp     r3, #STAMP_Y                  @ glow: only lighten, by c / 128
    bhs     3f
    rsb     r9, r3, #STAMP_Y
    mul     r9, r1, r9
    add     r3, r3, r9, lsr #7
    b       7f
6:  sub     r1, r1, #128                  @ core: lit as the glow's edge,
    mov     r1, r1, lsl #1
    cmp     r3, #STAMP_Y
    bhs     8f
    rsb     r9, r3, #STAMP_Y              @  STAMP_Y - t + 11 t / 16,
    add     r3, r9, r9, lsl #1
    add     r3, r3, r9, lsl #3
    rsb     r3, r9, r3, lsr #4
    add     r3, r3, #STAMP_Y
8:  rsb     r9, r3, #STAMP_Y              @  then covered by (c - 128) * 2 / 256
    mul     r9, r1, r9
    add     r3, r3, r9, asr #8
7:  strb    r3, [lr, r0]
3:  add     r0, r0, #1
    cmp     r0, #SW
    blo     2b
    tst     r2, #1
    bne     5f
    mov     r0, #0                        @ even row: the blocks' chroma, by
3:  add     r9, r12, r0                   @  their four pixels' mean coverage
    ldrb    r1, [r9]
    ldrb    r3, [r9, #1]
    add     r1, r1, r3
    ldrb    r3, [r9, #SW]
    add     r1, r1, r3
    ldrb    r3, [r9, #SW + 1]
    add     r1, r1, r3
    movs    r1, r1, lsr #2
    beq     4f
    add     r9, r6, r0
    mov     r9, r9, lsr #1                @ the block's column
    cmp     r9, r8, lsr #2
    addlo   lr, r5, r8                    @ the first W/4 pairs: in the even row
    addlo   lr, lr, r9, lsl #1
    subhs   r9, r9, r8, lsr #2
    addhs   lr, r5, r7                    @ the others: in the odd row
    addhs   lr, lr, r9, lsl #1            @ lr = the pair (U, V)
    ldrb    r3, [lr]
    rsb     r9, r3, #STAMP_U
    mul     r9, r1, r9
    add     r3, r3, r9, asr #8
    strb    r3, [lr]
    ldrb    r3, [lr, #1]
    rsb     r9, r3, #STAMP_V
    mul     r9, r1, r9
    add     r3, r3, r9, asr #8
    strb    r3, [lr, #1]
4:  add     r0, r0, #2
    cmp     r0, #SW
    blo     3b
5:  ldr     r2, [sp]
    add     r2, r2, #1
    str     r2, [sp]
    ldr     r3, [sp, #4]
    cmp     r2, r3
    blo     row
    ldr     r1, [sp, #8]
    add     sp, sp, #16
    mov     r0, r11
    mov     lr, pc
    b       CACHE_CLEAN
done:
    pop     {r0-r11, lr}
    str     lr, [sp, #-4]!                @ the instruction we replaced
    b       RESUME
    .ltorg

snap:
    push    {r0-r12, lr}
    ldr     r10, =VARS - base
    mov     r0, #0
    str     r0, [r10, #V_ROW]
    strb    r0, [r10, #V_ON]              @ no stamp until it is rendered
    ldr     r0, =CFG
    ldrb    r1, [r0, #CFG_MODE]
    cmp     r1, #NMODES - 1
    movhi   r1, #0                        @ not a mode: nor
    mov     lr, pc
    b       isp_profile
    cmp     r1, #0
    beq     9f                            @ nor: no stamp
    ldr     r11, [r10, #V_BUF]
    cmp     r11, #0
    bne     1f
    ldr     r0, =SW * SH
    mov     r1, #0x20
    mov     lr, pc
    b       MALLOC
    ldr     r10, =VARS - base
    movs    r11, r0
    beq     9f                            @ no memory: no stamp
    str     r11, [r10, #V_BUF]
1:  mov     lr, pc
    b       stamp_draw
    cmp     r0, #0
    bne     9f                            @ clock not set: no stamp
    mov     r0, #1
    strb    r0, [r10, #V_ON]
9:  pop     {r0-r12, lr}
    push    {r3, r4, r5, r6, r7, lr}      @ the instruction we replaced (0x187c4)
    b       RESUME187

@ Clear the stamp buffer r11 and draw the clock's date (and time, with
@ STAMP_TIME) into it, laid out by FIELDS (digicam.py fields). r0 = 0 when
@ drawn, else the clock is not set (the buffer stays clear). r1-r12 kept.
stamp_draw:
    push    {r1-r12, lr}
    mov     r0, #0
    ldr     r1, =SW * SH
    mov     r2, r11
2:  str     r0, [r2], #4
    subs    r1, r1, #4
    bhi     2b
    sub     sp, sp, #28
    mov     r0, sp
    mov     lr, pc
    b       GETTIME
    cmp     r0, #0
    bne     8f
    mov     r4, #PAD                      @ r4 = x
    ldr     r6, =FIELDS - base            @ per item: what, x's extra advance
1:  ldrb    r0, [r6], #1
    ldrsb   r7, [r6], #1
    cmp     r0, #F_END
    beq     7f
    cmp     r0, #G_APOS
    blo     2f                            @ an RTC field
    moveq   r5, #APOS                     @  else the apostrophe or the colon
    movne   r5, #COLON
    mov     lr, pc
    b       glyph
    b       5f
2:  ldr     r0, [sp, r0]
3:  cmp     r0, #100                      @ the year's last two digits
    subhs   r0, r0, #100
    bhs     3b
    mov     lr, pc
    b       pair
5:  add     r4, r4, r7
    b       1b
7:  mov     r0, #0
8:  add     sp, sp, #28
    pop     {r1-r12, pc}

@ ISP profile r1 (0 = stock, then CCD, Y2K, BW, NGT, SUN): point the ISP context's gamma
@ (+0x177c) and colour matrix (+0x1794) at its tables and reload both
@ (FUN_000981fc, FUN_000982a4, as the ISP's init does). Then its LOOKS: the
@ edge enhancer's amp gain, the sharpen gain (also as the gain tuner's per
@ level), HbNr, the NR thresholds (and the tuner's table) and lens shading
@ (regenerated only when its strengths change). nor restores the stock ones.
@ Every photo and recording, before its capture. All registers preserved.
isp_profile:
    push    {r0-r12, lr}
    ldr     r2, =PROFILES                 @ profile_data.s (build.sh --defsym)
    add     r2, r2, r1, lsl #3
    ldm     r2, {r2, r3}
    ldr     r0, =ISP_CTX
    ldr     r0, [r0]
    cmp     r0, #0
    beq     1f
    mov     r6, r0                        @ r6 = the context
    add     r0, r0, #0x1700
    str     r2, [r0, #0x7c]
    str     r3, [r0, #0x94]
    mov     lr, pc
    b       GAMMA_SET
    mov     lr, pc
    b       CCM_SET
    ldr     r9, =PROFILES
    add     r7, r9, #NMODES * 8
    add     r7, r7, r1, lsl #2            @ r7 = the mode's LOOKS
    ldrb    r0, [r7]
    mov     lr, pc
    b       EDGE_SET
    ldrb    r0, [r7, #1]
    add     r2, r6, #0x1400               @ the gain tuner's sharpen gains per
    str     r0, [r2, #0xa0]               @  gain level (stock 0x20, 0x1d, 0x19,
    sub     r3, r0, #3                    @  0x16), so it keeps ours
    str     r3, [r2, #0xa4]
    sub     r3, r0, #7
    str     r3, [r2, #0xa8]
    sub     r3, r0, #10
    str     r3, [r2, #0xac]
    mov     lr, pc
    b       SHARP_SET
    ldrb    r8, [r7, #2]                  @ r8 = flags
    tst     r8, #1
    moveq   r0, #1
    movne   r0, #0
    mov     lr, pc
    b       HBNR_SET
    add     r5, r6, #0x1700
    tst     r8, #2
    addne   r3, r9, #NMODES * 12 + 8      @ NR_LOW
    ldreq   r3, =0xd62e4
    str     r3, [r5, #0xa8]               @ the tuner's NR table
    movne   r0, #1
    movne   r1, #1
    movne   r2, #1
    movne   r3, #1
    moveq   r0, #1
    moveq   r1, #3
    moveq   r2, #5
    moveq   r3, #6
    mov     lr, pc
    b       NR_SET
    tst     r8, #4
    addne   r3, r9, #NMODES * 12          @ LSC_ZERO
    ldreq   r3, =0xd6a9c
    ldr     r0, [r5, #0xb0]
    cmp     r0, r3
    beq     1f                            @ unchanged: no regenerating
    str     r3, [r5, #0xb0]
    mov     lr, pc
    b       LSC_SET
1:  pop     {r0-r12, pc}

@ r0 = 0..99: its two digits at x = r4, then r4 past them and a space.
pair:
    push    {r0-r3, r5, lr}
    mov     r1, #0
1:  cmp     r0, #10
    subhs   r0, r0, #10
    addhs   r1, r1, #1
    bhs     1b
    ldr     r2, =DIGITS - base
    ldrb    r5, [r2, r1]
    mov     lr, pc
    b       glyph
    add     r4, r4, #ADV_DIGIT
    ldrb    r5, [r2, r0]
    mov     lr, pc
    b       glyph
    add     r4, r4, #ADV_DIGIT + ADV_SPACE
    pop     {r0-r3, r5, pc}

@ The segments of mask r5 (bit 0 = a, ..., bit 7 = the apostrophe, 8-9 the
@ colon's dots) at x = r4
@ into the stamp r11. r0-r10 kept.
glyph:
    push    {r0-r10, lr}
    ldr     r6, =SEGS - base
1:  movs    r5, r5, lsr #1
    movcs   lr, pc
    bcs     seg
    add     r6, r6, #8
    cmp     r5, #0
    bne     1b
    pop     {r0-r10, pc}

@ Segment r6 (cx, cy, half length, vertical; Q = 1/16 px) of the glyph at
@ x = r4 into the stamp r11, max with what is there: per pixel of its box,
@ row by row, the signed distance d from its hexagon (sheared by the italic),
@ coverage LUT[d + 8] (255 inside, 0 past the glow). digicam.py
@ render_boxed is the exact reference. All registers kept.
    .equ    F_Y1, 0
    .equ    F_GX, 4
    .equ    F_EX, 8
    .equ    F_CY, 12
    .equ    F_HL, 16
    .equ    F_Y,  20
seg:
    push    {r0-r12, lr}
    sub     sp, sp, #24
    str     r4, [sp, #F_GX]
    ldrh    r7, [r6]                      @ r7 = cx
    ldrh    r8, [r6, #2]                  @ cy
    ldrh    r9, [r6, #4]                  @ half length
    ldrh    r10, [r6, #6]                 @ r10 = vertical
    str     r8, [sp, #F_CY]
    str     r9, [sp, #F_HL]
    add     r0, r9, #2 * R + 24           @ the box: along the segment
    mov     r1, #TH + R + 16              @  and across
    cmp     r10, #0
    moveq   r2, r0
    moveq   r3, r1
    movne   r2, r1
    movne   r3, r0
    str     r2, [sp, #F_EX]               @ x extent
    add     r1, r8, r3
    mov     r1, r1, asr #4
    add     r1, r1, #PAD + 2
    cmp     r1, #SH
    movgt   r1, #SH
    str     r1, [sp, #F_Y1]               @ past the last row
    sub     r0, r8, r3
    mov     r0, r0, asr #4
    adds    r0, r0, #PAD - 1
    movmi   r0, #0                        @ r0 = the first row
    ldr     lr, =LUT - base
1:  ldr     r1, [sp, #F_Y1]
    cmp     r0, r1
    bge     9f
    str     r0, [sp, #F_Y]
    sub     r1, r0, #PAD
    mov     r1, r1, lsl #4
    add     r1, r1, #8                    @ r1 = ly
    ldr     r2, [sp, #F_CY]
    subs    r12, r1, r2
    rsbmi   r12, r12, #0                  @ dv = |ly - cy|
    ldr     r2, [sp, #F_HL]
    sub     r8, r12, r2                   @ r8 = dv - hl
    sub     r9, r12, #TH                  @ r9 = dv - TH
    rsb     r2, r1, #DH * 16
    mov     r3, #SL
    mul     r12, r2, r3
    mov     r12, r12, asr #8              @ r12 = the row's shear
    ldr     r2, [sp, #F_EX]
    ldr     r4, [sp, #F_GX]
    sub     r5, r7, r2
    add     r5, r5, r12
    add     r2, r7, r2
    add     r2, r2, r12
    mov     r3, r2, asr #4
    add     r3, r3, r4
    add     r3, r3, #2
    cmp     r3, #SW
    movgt   r3, #SW                       @ r3 = past the last column
    mov     r2, r5, asr #4
    add     r2, r2, r4
    subs    r2, r2, #1
    movmi   r2, #0                        @ r2 = x, the first column
    sub     r5, r2, r4
    mov     r5, r5, lsl #4
    add     r5, r5, #8
    sub     r5, r5, r12                   @ r5 = lx, unsheared
    mov     r4, #SW
    mla     r6, r0, r4, r11               @ r6 = the row
    cmp     r2, r3
    bge     8f
2:  subs    r12, r5, r7
    rsbmi   r12, r12, #0                  @ du = |lx - cx|
    add     r0, r12, r8
    mov     r1, #181
    mul     r4, r0, r1
    mov     r4, r4, asr #8                @ (du + dv - hl) / sqrt 2
    cmp     r10, #0
    subne   r0, r12, #TH                  @ across - TH
    moveq   r0, r9
    cmp     r0, r4
    movlt   r0, r4                        @ d
    adds    r0, r0, #8
    movmi   r1, #255
    bmi     3f
    cmp     r0, #NLUT
    bhs     4f
    ldrb    r1, [lr, r0]
3:  ldrb    r0, [r6, r2]
    cmp     r1, r0
    strbhi  r1, [r6, r2]
4:  add     r2, r2, #1
    add     r5, r5, #16
    cmp     r2, r3
    blt     2b
8:  ldr     r0, [sp, #F_Y]
    add     r0, r0, #1
    b       1b
9:  add     sp, sp, #24
    pop     {r0-r12, pc}
    .ltorg

    .align  2
VARS:
    .word   0                             @ V_ROW
    .word   0                             @ V_BUF
    .byte   0, 0, 0, 0                    @ V_ON
    STAMP_DATA
