@ The digicam modes on video (VIDEOLOOK=1): the mode's ISP profile from the
@ start of every recording, and in CCD and Y2K the date stamp burned into
@ every frame, exactly as on photos.
@
@ rec_start (bl_jump.s: the bl to FUN_0000fb28, video_encode_record_start,
@ at 0x35e30 in FUN_00035dbc, its only caller; UI task): isp_profile(mode)
@ (nor: stock), and in CCD/Y2K draw the stamp (stamp_draw) into the digicam
@ cave's buffer (its V_BUF, allocated here if no photo did yet). W_ON says
@ whether frames get it. Then on to FUN_0000fb28 with its arguments (r0-r3
@ and the two on the stack) untouched.
@
@ vhook (b_jump.s: FUN_00018d14's first instruction, ldr r3, [r0]; camera
@ task): r0 = the video encode struct (0x131490), r1 = the frame's
@ timestamp. On the front-camera path ([0] = 1) in format '#' (+0x101) its
@ buffer ([2], tagged | 0x30000000, 0x50000000 = none) holds +0xd0 rows of a
@ +0xdc x +0xe0 frame (the whole frame at the stock sizes; 64-row strips
@ when the scaler shrinks, as v011-v027's small video), YUV 4:2:0 laid out
@ like the photo strips. W_Y counts the rows handed over in this frame (a
@ new timestamp or a full frame starts over at 0). The rows that cross the
@ stamp (bottom right, MARGIN from the edges) get it with the photo hook's
@ blend (digicam.py apply_stamp), with cache maintenance over just those
@ rows.
    .syntax unified
    .arm
    .include "digicam.inc"                @ NMODES, SW, SH, MARGIN, STAMP_Y/U/V
base:
    .set    RESUME,      base + 0x18d18
    .set    REC_START,   base + 0xfb28
    .set    CACHE_INV,   base + 0x401ac
    .set    CACHE_CLEAN, base + 0x401b8
    .set    MALLOC,      base + 0x5374c   @ pvPortMalloc(size, align)
    .set    ISP_PROFILE, base + ISP_PROFILE_ADDR  @ digicam_cave.s (from build.sh)
    .set    STAMP_DRAW,  base + STAMP_DRAW_ADDR   @ digicam_cave.s (from build.sh)
    .equ    DVARS,       DVARS_ADDR       @ digicam_cave.s VARS (from build.sh)
    .equ    V_BUF,       4                @  its stamp buffer
    .equ    CFG,         0x132160         @ the camera's settings
    .equ    CFG_MODE,    0xf1
    .equ    W_ON,        0                @ offsets into WVARS
    .equ    W_TS,        4
    .equ    W_Y,         8

    .org    0xbb774
rec_start:
    push    {r0-r12, lr}
    ldr     r10, =WVARS - base
    mov     r0, #0
    strb    r0, [r10, #W_ON]              @ no stamp until it is drawn
    str     r0, [r10, #W_Y]
    ldr     r0, =CFG
    ldrb    r1, [r0, #CFG_MODE]
    cmp     r1, #NMODES - 1
    movhi   r1, #0                        @ not a mode: nor
    mov     lr, pc
    b       ISP_PROFILE
    cmp     r1, #0
    beq     9f                            @ nor: stock, no stamp
    ldr     r9, =DVARS
    ldr     r11, [r9, #V_BUF]
    cmp     r11, #0
    bne     1f
    ldr     r0, =SW * SH
    mov     r1, #0x20
    mov     lr, pc
    b       MALLOC
    ldr     r9, =DVARS
    movs    r11, r0
    beq     9f                            @ no memory: no stamp
    str     r11, [r9, #V_BUF]
1:  mov     lr, pc
    b       STAMP_DRAW
    cmp     r0, #0
    moveq   r0, #1                        @ drawn (else the clock is not set)
    strbeq  r0, [r10, #W_ON]
9:  pop     {r0-r12, lr}
    b       REC_START

vhook:
    push    {r0-r11, lr}                  @ r0-r1 are FUN_00018d14's live args
    ldr     r10, =WVARS - base
    ldrb    r2, [r10, #W_ON]
    cmp     r2, #0
    beq     vdone
    ldr     r2, [r0]
    cmp     r2, #1                        @ front camera path
    bne     vdone
    ldrb    r2, [r0, #0x101]
    cmp     r2, #0x23                     @ '#'
    bne     vdone
    ldr     r11, [r0, #8]
    cmp     r11, #0x50000000
    cmpne   r11, #0
    beq     vdone
    bic     r11, r11, #0x30000000         @ r11 = the buffer (FUN_00047228)
    ldr     r8, [r0, #0xdc]               @ r8 = W
    ldr     r9, [r0, #0xe0]               @ r9 = H
    ldr     r5, [r0, #0xd0]               @ r5 = its rows
    cmp     r5, #0
    beq     vdone
    cmp     r5, r9
    bhi     vdone
    ldr     r2, [r10, #W_TS]
    str     r1, [r10, #W_TS]
    cmp     r1, r2
    ldreq   r4, [r10, #W_Y]               @ r4 = its first row: the frame's
    movne   r4, #0                        @  next, or 0 for a new frame
    cmp     r4, r9
    movhs   r4, #0
    add     r2, r4, r5
    str     r2, [r10, #W_Y]
    add     r7, r8, r8, lsr #1            @ r7 = stride, 1.5 W
    ldr     r10, =DVARS
    ldr     r10, [r10, #V_BUF]            @ r10 = the stamp
    cmp     r10, #0
    beq     vdone
    subs    r9, r9, #MARGIN + SH
    bmi     vdone
    bic     r9, r9, #1                    @ r9 = the stamp's top row, Y0
    cmp     r4, r9
    movge   r2, r4
    movlt   r2, r9                        @ r2 = first row to do
    add     r3, r4, r5
    add     r0, r9, #SH
    cmp     r3, r0
    movgt   r3, r0                        @ r3 = past the last
    cmp     r2, r3
    bge     vdone
    sub     r0, r2, r4
    bic     r0, r0, #1
    mul     r6, r0, r7
    add     r6, r6, r11                   @ r6 = the first band's even row
    sub     r1, r3, r2
    add     r1, r1, #1
    bic     r1, r1, #1
    mul     r12, r1, r7                   @ r12 = the bands' bytes
    push    {r2, r3, r6, r9, r12}         @ [sp] = row, +4 end, +8 start, +12 Y0, +16 bytes
    mov     r1, r12
    mov     r0, r6
    mov     lr, pc
    b       CACHE_INV
    sub     r6, r8, #MARGIN
    subs    r6, r6, #SW
    bmi     vend
    bic     r6, r6, #1                    @ r6 = the stamp's left column, X0
row:                                      @ as digicam_cave.s hook
    ldr     r2, [sp]
    sub     r0, r2, r4                    @ the row in the buffer
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
vend:
    ldr     r0, [sp, #8]
    ldr     r1, [sp, #16]
    add     sp, sp, #20
    mov     lr, pc
    b       CACHE_CLEAN
vdone:
    pop     {r0-r11, lr}
    ldr     r3, [r0]                      @ the instruction we replaced
    b       RESUME
    .ltorg
    .align  2
WVARS:
    .byte   0, 0, 0, 0                    @ W_ON
    .word   0                             @ W_TS: the last buffer's timestamp
    .word   0                             @ W_Y: rows of this frame so far
