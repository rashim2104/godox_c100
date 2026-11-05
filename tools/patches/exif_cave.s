@ EXIF in every photo (EXIF=1).
@
@ FUN_0001808c builds the JPEG header for a photo (a 0x270-byte template at
@ 0xe2f50: SOI, SOF0 with this photo's size, COM, DQT, DRI, DHT, SOS) and
@ ends with a tail call write(fd, template, 0x270) at 0x18328. exif_jump
@ points that tail call here instead, which writes the same file as
@
@     SOI | APP1 (Exif) | the template after its SOI
@
@ The APP1 (tools/exif.py, exif.inc) is fixed apart from the photo's size,
@ copied from the SOF0 (height at +7, width at +9, big-endian), the date
@ from the RTC (FUN_00052bd4: 0, or -1 if the clock was never set, then a
@ blank date as EXIF wants for unknown), and the exposure the sensor was
@ last set to by the AE (FUN_0004c22c): lines at 0x1241a4 (x 30/1014000 s),
@ gain x64 at 0x1241a0 (ISO = 100 x gain/64), and the white balance
@ setting (0x132160 + 0x98, "temp_awb": 0 = auto). write (FUN_000385a0) waits for the
@ file task to take the data, so one static APP1 is enough; it only runs in
@ the camera task, once per photo, never in an interrupt.
@
@ In the dead FUN_000bb3f8, 0xbb3f8-0xbb774: its only "pointer" is the word
@ 0x000bb679 at 0xc4c60, which is fdlibm pow's sqrt(3) threshold (0xbb67a,
@ next to 0x3988e = sqrt(3/2) and 0x43400000 = 2^53), not an address.
    .syntax unified
    .arm
base:
    .set    WRITE,    base + 0x385a0      @ write(fd, buf, len)
    .set    GETTIME,  base + 0x52bd4      @ (int t[7]) sec min hour mday mon year wday
    .set    SNPRINTF, base + 0xce234
    .set    AE_LINES, base + 0x1241a4
    .set    AE_GAIN,  base + 0x1241a0
    .set    WB_MODE,  base + 0x1321f8
    .equ    T, 20                         @ t[7] on the stack, after 5 varargs

    .org    0xbb3f8
exif_write:                               @ r0 = fd, r1 = template, r2 = 0x270
    push    {r4-r6, lr}
    sub     sp, sp, #48
    mov     r4, r0
    mov     r5, r1
    mov     r2, #2                        @ SOI
    mov     lr, pc
    b       WRITE

    ldr     r6, =APP1 - base
    ldrb    r0, [r5, #9]                  @ width
    ldrb    r1, [r5, #10]
    orr     r0, r1, r0, lsl #8
    ldr     r3, =W
    strh    r0, [r6, r3]
    ldr     r3, =W0
    strh    r0, [r6, r3]
    ldrb    r0, [r5, #7]                  @ height
    ldrb    r1, [r5, #8]
    orr     r0, r1, r0, lsl #8
    ldr     r3, =H
    strh    r0, [r6, r3]
    ldr     r3, =H0
    strh    r0, [r6, r3]

    ldr     r3, =AE_LINES - base          @ ExposureTime = lines x 30 / 1014000
    ldr     r0, [r3]
    mov     r1, #30
    mul     r2, r0, r1
    ldr     r3, =EXPO
    strh    r2, [r6, r3]
    ldr     r3, =AE_GAIN - base           @ ISO = gain x 100/64 = gain x 25/16
    ldr     r0, [r3]
    mov     r1, #25
    mul     r2, r0, r1
    lsr     r2, r2, #4
    ldr     r3, =ISO
    strh    r2, [r6, r3]
    ldr     r3, =WB_MODE - base           @ 0 auto, else a preset: manual
    ldrb    r0, [r3]
    subs    r0, r0, #0
    movne   r0, #1
    ldr     r3, =WHITE_BALANCE
    strh    r0, [r6, r3]

    add     r0, sp, #T
    mov     lr, pc
    b       GETTIME
    ldr     r2, =BLANK - base
    cmp     r0, #0
    blt     1f
    ldr     r0, [sp, #T + 16]             @ mon
    str     r0, [sp]
    ldr     r0, [sp, #T + 12]             @ mday
    str     r0, [sp, #4]
    ldr     r0, [sp, #T + 8]              @ hour
    str     r0, [sp, #8]
    ldr     r0, [sp, #T + 4]              @ min
    str     r0, [sp, #12]
    ldr     r0, [sp, #T]                  @ sec
    str     r0, [sp, #16]
    ldr     r3, [sp, #T + 20]             @ year
    ldr     r2, =FMT - base
1:  ldr     r0, =DATE0
    add     r0, r6, r0
    mov     r1, #20
    mov     lr, pc
    b       SNPRINTF
    ldr     r0, =DATE0                    @ the same date in DATE1
    add     r0, r6, r0
    ldr     r1, =DATE1
    add     r1, r6, r1
    mov     r3, #20
2:  ldrb    ip, [r0], #1
    strb    ip, [r1], #1
    subs    r3, r3, #1
    bne     2b

    mov     r0, r4
    mov     r1, r6
    ldr     r2, =APP1_LEN
    mov     lr, pc
    b       WRITE

    mov     r0, r4                        @ the rest of the template, as the
    add     r1, r5, #2                    @ original tail call did
    ldr     r2, =0x26e
    add     sp, sp, #48
    pop     {r4-r6, lr}
    b       WRITE

    .ltorg
FMT:
    .asciz  "%04u:%02u:%02u %02u:%02u:%02u"
BLANK:
    .asciz  "    :  :     :  :  "
    .include "exif.inc"
