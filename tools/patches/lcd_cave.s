@ The camera's mode on the see-through display, cycled with the center button.
@
@ The mode (digicam_cave.s: nor, CCD, Y2K; NMODES) lives in byte 0xf1 of the
@ camera's settings (0x132160, 0xf4 bytes, checksummed and saved to NVRAM at
@ power-off when its dirty byte +0xa0 is 1; no firmware instruction uses
@ offsets 0xf1-0xf3), so it survives power-off; any other value counts as
@ nor. The display is an HT1621 segment panel (see docs/c100-firmware.md); in
@ photo and video mode its readouts are blank. There, the three cells of the
@ shutter-speed (SS) readout show the mode's code: "nor", "CCd" or "Y2K".
@
@ lcd_hook: the periodic display refresh (FUN_00021318) draws the readouts
@ with 0x21180(flag), flag = 1 in the readout state (UI state 2), else 0. It
@ draws ISO (FUN_0001ff10) and F (FUN_00020afc), then tail-calls 0x20fd0 (the
@ video icon and SS) with r0 = flag at 0x21218, or, in the readout state with
@ SS blinking, at 0x21200. lcd_jump.s points the tail call at 0x21218 here.
@ In photo and video mode (r0 = 0, readouts blank) run the stock routine,
@ then write the code over the blank SS cells (HT1621 addresses 0x0d..0x13,
@ nothing else lives there) and return to the refresh's caller. With r0 != 0
@ (the readout state) just tail-call the stock routine.
@
@ center_hook: the center button's handler (FUN_0001dd6c,
@ ap_peripheral_F_key_exe, an ADC key) posts message 0x7041 once per press;
@ only the readout state acts on it (it cycles ISO/F/SS there; the arrows are
@ IO_ISO = 0x7042 and T = 0x7043, aspect -1/+1 in photo and video mode).
@ key_jump.s points that post (bl 0x42c at
@ 0x1ddf8) here: in photo and video mode, and not while recording, step the
@ mode and mark the settings dirty (so the firmware saves them at power-off);
@ then post the message as before. Every mode takes the factory's sizes, so
@ nothing else changes.
@
@ splash: the display's init (FUN_0004ad68) clears all 25 addresses and ends
@ in a tail call to the logo routine, 0x4a64c(1) (the GODOX logo, 16.1).
@ b_jump.s points that tail call (0x4ae38) here instead: light "rASHIM" on
@ the 7 cells (SPLASH_DATA) and leave the logo off. The refresh's readouts
@ clear it when they first draw, where the factory's logo went off.
    .syntax unified
    .arm
    .include "digicam.inc"                @ NMODES, SS_*, LCD_TAG_DATA
base:
    .set    SS_ROUTINE,  base + 0x20fd0   @ video icon + SS readout (r0 = blink flag)
    .set    SEG_WRITE,   base + 0x49e34   @ seg_write(addr, nibble), updates SHADOW
    .set    MSG_POST,    base + 0x42c     @ post to a message queue (5 args, 1 on the stack)
    .equ    CFG,         0x132160         @ the camera's settings (see above)
    .equ    CFG_MODE,    0xf1             @ our mode byte in them
    .equ    CFG_DIRTY,   0xa0             @ 1 = save at power-off (FUN_00024094)
    .equ    UI_STATE,    0x121706         @ 0/1 = photo/video mode, 2 = readout
    .equ    REC_FLAGS,   0x132abb         @ FUN_00035dac; bit 1 = recording
    .equ    SHADOW,      0x1240e0         @ firmware's copy of the HT1621 RAM

    .org    0xbc400
lcd_hook:
    cmp     r0, #0                        @ readout state: stock SS readout
    bne     SS_ROUTINE
    push    {r4-r6, lr}
    mov     lr, pc                        @ the stock routine (r0 = 0, blank)
    b       SS_ROUTINE
    ldr     r0, =CFG
    ldrb    r0, [r0, #CFG_MODE]
    cmp     r0, #NMODES - 1
    movhi   r0, #0                        @ not a mode: nor (as snap)
    ldr     r5, =LCD_TAGS - base          @ r5 = this mode's SS_COUNT nibbles
    mov     r1, #SS_COUNT
    mla     r5, r0, r1, r5
    mov     r6, #0
3:  ldrb    r1, [r5, r6]
    add     r0, r6, #SS_FIRST
    ldr     r2, =SHADOW
    ldrb    r2, [r2, r0]
    cmp     r1, r2                        @ only send what changed
    movne   lr, pc
    bne     SEG_WRITE
    add     r6, r6, #1
    cmp     r6, #SS_COUNT
    blo     3b
    pop     {r4-r6, pc}

center_hook:                            @ r0-r3 and [sp] are MSG_POST's arguments
    push    {r0-r3, lr}
    ldr     r0, =UI_STATE
    ldrb    r0, [r0]
    cmp     r0, #1                        @ photo or video mode only
    bhi     1f
    ldr     r0, =REC_FLAGS
    ldrb    r0, [r0]
    tst     r0, #2                        @ not while recording
    bne     1f
    ldr     r1, =CFG
    ldrb    r0, [r1, #CFG_MODE]
    add     r0, r0, #1                    @ the next mode, after the last (or not a
    cmp     r0, #NMODES                   @  mode) the first
    movhs   r0, #0
    strb    r0, [r1, #CFG_MODE]
    mov     r3, #1
    strb    r3, [r1, #CFG_DIRTY]          @ save it at power-off
1:  pop     {r0-r3, lr}
    b       MSG_POST                      @ returns to the key handler

splash:
    push    {r4, lr}
    mov     r4, #0
4:  ldr     r1, =SPLASH - base
    ldrb    r1, [r1, r4]
    cmp     r1, #0                        @ init cleared them all
    movne   r0, r4
    movne   lr, pc
    bne     SEG_WRITE
    add     r4, r4, #1
    cmp     r4, #NSPLASH
    blo     4b
    pop     {r4, pc}
    .ltorg

SPLASH:
    SPLASH_DATA
LCD_TAGS:
    LCD_TAG_DATA
