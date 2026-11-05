@ Point the JPEG header's tail call write(fd, template, 0x270) at 0x18328
@ (end of FUN_0001808c) at exif_write (exif_cave.s).
    .syntax unified
    .arm
base:
    .set    TARGET, base + HOOK           @ exif_write (address from build.sh)
    .org    0x18328
    b       TARGET
