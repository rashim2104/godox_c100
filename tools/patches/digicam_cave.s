@ The digicam modes (tools/digicam.py): nor, CCD and Y2K, chosen with the
@ center button (lcd_cave.s; the mode is byte 0xf1 of the camera's saved
@ settings, anything else counts as nor). Every mode takes the factory's
@ sizes.
@
@ snap (cyc_jump.s: FUN_000187c4, the capture handler, once per photo,
@ camera task): hand the ISP the mode's profile (isp_profile), and in CCD or
@ Y2K render the date stamp, "DD MM 'YY" from the RTC, into a coverage buffer
@ (SW x SH bytes, allocated once).
@
@ hook (hook_jump.s: FUN_00015448, the scaler's "strip ready" callback,
@ interrupt): each call hands over one finished strip (FUN_0001523c queues one
@ buffer per call), strip A at PHOTO+0x18 or B after it, STRIP_BYTES each,
@ YUV 4:2:0 laid out as docs/c100-firmware.md "Strip buffer format". The
@ photo's width and height come from the JPEG header's SOF0 (0xe2f50, filled
@ by FUN_0001808c before the capture); a strip's rows = STRIP_BYTES / (1.5 W),
@ and V_ROW counts the rows handed over so far. Rows that cross the stamp's
@ rectangle (bottom right, MARGIN from the edges) get it blended in:
@ luma toward STAMP_Y (never darker), each 2x2 block's chroma toward STAMP_U/V,
@ by the coverage of its top-left pixel; tools/digicam.py apply_stamp is the
@ exact reference.
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
    sub     r6, r8, #MARGIN + SW
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
    cmp     r3, #STAMP_Y
    bhs     3f                            @ brighter than the stamp: as it is
    rsb     r1, r1, #256
    rsb     r3, r3, #STAMP_Y
    mul     r9, r3, r1
    mov     r9, r9, lsr #8
    rsb     r3, r9, #STAMP_Y              @ STAMP_Y - (STAMP_Y - Y)(256 - c) / 256
    strb    r3, [lr, r0]
3:  add     r0, r0, #1
    cmp     r0, #SW
    blo     2b
    tst     r2, #1
    bne     5f
    mov     r0, #0                        @ even row: the blocks' chroma
3:  ldrb    r1, [r12, r0]
    cmp     r1, #0
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
1:  mov     r0, #0
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
    bne     8f                            @ clock not set: no stamp
    mov     r4, #PAD                      @ r4 = x
    ldr     r0, [sp, #12]                 @ day
    mov     lr, pc
    b       pair
    ldr     r0, [sp, #16]                 @ month
    mov     lr, pc
    b       pair
    mov     r5, #APOS
    mov     lr, pc
    b       glyph
    add     r4, r4, #ADV_APOS
    ldr     r0, [sp, #20]                 @ year
3:  cmp     r0, #100
    subhs   r0, r0, #100
    bhs     3b
    mov     lr, pc
    b       pair
    ldr     r10, =VARS - base
    mov     r0, #1
    strb    r0, [r10, #V_ON]
8:  add     sp, sp, #28
9:  pop     {r0-r12, lr}
    push    {r3, r4, r5, r6, r7, lr}      @ the instruction we replaced (0x187c4)
    b       RESUME187

@ ISP profile r1 (0 = stock, then CCD, Y2K): point the ISP context's gamma
@ (+0x177c) and colour matrix (+0x1794) at its tables and reload both
@ (FUN_000981fc, FUN_000982a4, as the ISP's init does). Every photo, before
@ its capture, so nothing is cached. All registers preserved.
isp_profile:
    push    {r0-r12, lr}
    ldr     r2, =PROFILES - base
    add     r2, r2, r1, lsl #3
    ldm     r2, {r2, r3}
    ldr     r0, =ISP_CTX
    ldr     r0, [r0]
    cmp     r0, #0
    beq     1f
    add     r0, r0, #0x1700
    str     r2, [r0, #0x7c]
    str     r3, [r0, #0x94]
    mov     lr, pc
    b       GAMMA_SET
    mov     lr, pc
    b       CCM_SET
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

@ The segments of mask r5 (bit 0 = a, ..., bit 7 = the apostrophe) at x = r4
@ into the stamp r11, each as its RINGS (grown, at a coverage). r0-r10 kept.
glyph:
    push    {r0-r10, lr}
    ldr     r6, =SEGS - base
1:  movs    r5, r5, lsr #1
    bcc     4f
    ldr     r7, =RINGS - base
    mov     r8, #3
2:  ldrb    r9, [r7], #1                  @ grow by
    ldrb    r12, [r7], #1                 @ coverage
    ldrb    r0, [r6]
    add     r0, r0, r4
    sub     r0, r0, r9
    ldrb    r1, [r6, #1]
    add     r1, r1, #PAD
    sub     r1, r1, r9
    ldrb    r2, [r6, #2]
    add     r2, r2, r4
    add     r2, r2, r9
    ldrb    r3, [r6, #3]
    add     r3, r3, #PAD
    add     r3, r3, r9
    mov     lr, pc
    b       fill
    subs    r8, r8, #1
    bne     2b
4:  add     r6, r6, #4
    cmp     r5, #0
    bne     1b
    pop     {r0-r10, pc}

@ Raise the stamp r11 to coverage r12 over [r0, r2) x [r1, r3), each row
@ shifted right by its slant ((DH - 1 - clamp(y - PAD)) * 43 >> 8 = / 6),
@ clipped to the buffer. r0-r10 kept.
fill:
    push    {r0-r10, lr}
    cmp     r1, #0
    movlt   r1, #0
    cmp     r3, #SH
    movgt   r3, #SH
1:  cmp     r1, r3
    bge     9f
    subs    r4, r1, #PAD
    movlt   r4, #0
    cmp     r4, #DH - 1
    movgt   r4, #DH - 1
    rsb     r4, r4, #DH - 1
    mov     r5, #43
    mul     r6, r4, r5
    mov     r4, r6, lsr #8                @ r4 = the row's slant
    adds    r5, r0, r4
    movmi   r5, #0
    add     r6, r2, r4
    cmp     r6, #SW
    movgt   r6, #SW
    mov     r7, #SW
    mla     r8, r1, r7, r11               @ r8 = the row
2:  cmp     r5, r6
    bge     3f
    ldrb    r9, [r8, r5]
    cmp     r9, r12
    strblo  r12, [r8, r5]
    add     r5, r5, #1
    b       2b
3:  add     r1, r1, #1
    b       1b
9:  pop     {r0-r10, pc}
    .ltorg

    .align  2
PROFILES:                               @ gamma, colour matrix: stock (the calibration's), CCD, Y2K
    .word   0xd8050, 0xd6338
    .word   GAMMA_CCD - base, CCM_CCD - base
    .word   GAMMA_Y2K - base, CCM_Y2K - base
VARS:
    .word   0                             @ V_ROW
    .word   0                             @ V_BUF
    .byte   0, 0, 0, 0                    @ V_ON
    STAMP_DATA
