@ Photo sizes per aspect setting (SIZE169/32/43/11, tools/photo.py), in the
@ dead 0xbb340-0xbb3f8. build.sh points the photo size jump table (0xf3d0,
@ `ldrls pc, [pc, r6, lsl #2]` at 0xf3c8) at a stub only for the aspects that
@ are set; video's table (0xf0a0) stays stock. Each stub sets the size struct
@ (r4) as v019-v027 did: crop C (+10/+12) = first scaler S (+6/+8) = the
@ crop, target T (+14/+16) = the output, mode byte (+4) = 1 (photo), then
@ rejoins the photo path at 0xf188 with r6/r7 = T and r3/r2 = S, as the stock
@ code has them there. Setting only T would make the firmware crop, not scale.
    .syntax unified
    .arm
    .include "size.inc"
base:
    .set    PHOTO_PATH, base + 0xf188

    .org    0xbb340
sz169:
    adr     r1, SZ169
    b       sz_common
sz32:
    adr     r1, SZ32
    b       sz_common
sz43:
    adr     r1, SZ43
    b       sz_common
sz11:
    adr     r1, SZ11
sz_common:
    ldrh    r6, [r1]
    ldrh    r7, [r1, #2]
    ldrh    r3, [r1, #4]
    ldrh    r2, [r1, #6]
    strh    r6, [r4, #14]                 @ target
    strh    r7, [r4, #16]
    strh    r3, [r4, #10]                 @ crop
    strh    r2, [r4, #12]
    strh    r3, [r4, #6]                  @ first scaler = crop
    strh    r2, [r4, #8]
    mov     r0, #1                        @ photo mode byte
    strb    r0, [r4, #4]
    b       PHOTO_PATH

@ Per aspect: output W, H, crop W, H.
SZ169:  .hword  P169_W, P169_H, P169_CW, P169_CH
SZ32:   .hword  P32_W, P32_H, P32_CW, P32_CH
SZ43:   .hword  P43_W, P43_H, P43_CW, P43_CH
SZ11:   .hword  P11_W, P11_H, P11_CW, P11_CH
