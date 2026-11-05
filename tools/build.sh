#!/bin/sh
# Rebuild build/GP_CARDVR_UPGRADE.BIN from the original firmware:
# custom sounds + code patches. Edit the lists below to change what goes in.
set -e
cd "$(dirname "$0")/.."
LLVM=/opt/homebrew/opt/llvm/bin
[ -d "$LLVM" ] || LLVM=/opt/homebrew/opt/llvm@18/bin
ORIG=c100_v1.1.6_20260929/GP_CARDVR_UPGRADE.BIN
OUT=build/GP_CARDVR_UPGRADE.BIN
mkdir -p build/obj

# --- sounds ---
# By default the camera sounds like a 2000s compact (tools/sounds.py): a fake
# "ka-chak" shutter, a rising power-on chime and a tick for the center
# button's mode change. SILENT=1 makes them silent (same slots, zeroed
# samples) AND never switches the speaker amplifier on (see SPK_PATCHES
# below), so there is no amp hiss either.
#   sh tools/build.sh            -> digicam sounds
#   SILENT=1 sh tools/build.sh   -> no sounds, speaker amp stays off
# SHUTTER_WAV / POWERON_WAV / CLICK_WAV pick other sounds (11025 Hz mono
# 16-bit PCM, at most the slot's size).
SILENT=${SILENT:-0}
python3 -I tools/sounds.py build/sounds
SHUTTER_WAV=${SHUTTER_WAV:-build/sounds/shutter.wav}
POWERON_WAV=${POWERON_WAV:-build/sounds/poweron.wav}
CLICK_WAV=${CLICK_WAV:-build/sounds/click.wav}
python3 tools/gp_res.py "$ORIG" build/res >/dev/null
if [ "$SILENT" = "1" ]; then
    python3 -I tools/mk_silence.py "$SHUTTER_WAV" build/silent_cam.wav
    python3 -I tools/mk_silence.py "$POWERON_WAV" build/silent_pwr.wav
    python3 -I tools/mk_silence.py build/res/CLICK.wav build/click_silent.wav
    python3 tools/patch_res.py "$ORIG" CAMERA.wav build/silent_cam.wav "$OUT"
    python3 tools/patch_res.py "$OUT" POWERON_AUDIO.wav build/silent_pwr.wav "$OUT"
    python3 tools/patch_res.py "$OUT" CLICK.wav build/click_silent.wav "$OUT"
else
    python3 tools/patch_res.py "$ORIG" CAMERA.wav "$SHUTTER_WAV" "$OUT"
    python3 tools/patch_res.py "$OUT" POWERON_AUDIO.wav "$POWERON_WAV" "$OUT"
    python3 tools/patch_res.py "$OUT" CLICK.wav "$CLICK_WAV" "$OUT"
fi

# BEEP.wav (the UI/focus beep) is always silenced, in both sound profiles.
python3 -I tools/mk_silence.py build/res/BEEP.wav build/beep_silent.wav
python3 tools/patch_res.py "$OUT" BEEP.wav build/beep_silent.wav "$OUT"

# Speaker amplifier = GPIO 0x2c, driven by gpio_write FUN_000433f4(pin, level).
# Sound playback FUN_00022a80 switches it on, waits 100 ms, then queues the WAV;
# the peripheral task (FUN_00021e60, ~1 s tick) only switches it off again on
# its 2nd tick after that, so every sound gives ~1-2 s of amp hiss even when
# the WAV is silent. With SILENT=1 the "on" calls become NOPs (pure pin writes,
# return value unused), so the amp is never powered:
#   0x22b38  FUN_00022a80, every UI sound (shutter, click, power-on, beep)
#   0x350f0  state_startup_init, unconditional "on" at boot
#   0x2ed50  photo state, the remaining "on"
SPK_PATCHES=""
if [ "$SILENT" = "1" ]; then
    SPK_PATCHES="0x22b38:2d8200eb:0000a0e1 0x350f0:bf3800eb:0000a0e1 0x2ed50:a75100eb:0000a0e1"
fi

# --- assemble a patch: prints ADDR:OLDHEX:NEWHEX for patch_code.py ---
asm() {  # asm NAME START END [extra llvm-mc args, e.g. --defsym=X=1]
    name=$1 start=$2 end=$3; shift 3
    $LLVM/llvm-mc -triple=armv5te-none-eabi \
        -I build/obj -I tools/patches "$@" -filetype=obj "tools/patches/$name.s" -o "build/obj/$name.o"
    set -- "$name" "$start" "$end"
    if $LLVM/llvm-readobj -r "build/obj/$1.o" | grep -q R_ARM; then
        echo "$1: unresolved relocation (use 'mov lr, pc; b X' instead of 'bl X')" >&2; exit 1
    fi
    $LLVM/llvm-objcopy -O binary "build/obj/$1.o" "build/obj/$1.bin"
    python3 -I -c "
import sys
start, end = int(sys.argv[3], 0), int(sys.argv[4], 0)
blob = open(sys.argv[1], 'rb').read()
assert len(blob) <= end, f'{sys.argv[1]}: code runs past {end:#x} (ends at {len(blob):#x})'
new = blob[start:end]
old = open(sys.argv[2], 'rb').read()[start + 0x10200:end + 0x10200]
new += old[len(new):]
print(f'{start:#x}:{old.hex()}:{new.hex()}')
" "build/obj/$1.bin" "$ORIG" "$2" "$3"
}

# --- code patches ---
# The modes, nor, CCD and Y2K (tools/digicam.py: digicam.inc), in the dead
# FUN_000bab6c, 0xbab6c-0xbb340 (tools/patches/digicam_cave.s): per photo
# (the capture handler, 0x187c4) the mode's ISP profile and the date stamp,
# per strip (the scaler's callback, 0x15448) the stamp blended in. The center
# button cycles the modes and the display's shutter-speed cells show the
# current one (tools/patches/lcd_cave.s, 0xbc400-0xbc744: the refresh's tail
# call at 0x21218 and the center key's post at 0x1ddf8).
python3 -I tools/digicam.py asm > build/obj/digicam.inc
nmsym() {  # nmsym OBJ LABEL: address of a label in an assembled cave
    $LLVM/llvm-nm "build/obj/$1.o" | awk -v s="$2" '$3 == s { print "0x" $1 }'
}
CAVE=$(asm digicam_cave 0xbab6c 0xbb340)
HOOK_JUMP=$(asm hook_jump 0x15448 0x1544c --defsym=HOOK=$(nmsym digicam_cave hook))
CYC_JUMP=$(asm cyc_jump 0x187c4 0x187c8 --defsym=STUB=$(nmsym digicam_cave snap))
LCAVE=$(asm lcd_cave 0xbc400 0xbc744)
LJUMP=$(asm lcd_jump 0x21218 0x2121c --defsym=HOOK=$(nmsym lcd_cave lcd_hook))
KJUMP=$(asm key_jump 0x1ddf8 0x1ddfc --defsym=HOOK=$(nmsym lcd_cave center_hook))
# The boot splash: "rASHIM" on the display's 7 cells instead of the GODOX
# logo (the display init's tail call to the logo routine, 0x4ae38).
SJUMP=$(asm b_jump 0x4ae38 0x4ae3c --defsym=AT=0x4ae38 --defsym=HOOK=$(nmsym lcd_cave splash))
# EXIF in every photo (EXIF=1, default; EXIF=0 leaves it out): make, model,
# software, artist, date and time (from the RTC; set it with TIME.TXT), its
# UTC offset and the pixel size. See tools/exif.py (EXIF_ARTIST, EXIF_OFFSET,
# ...) and tools/patches/exif_cave.s, in the dead FUN_000bb3f8.
EXIF=${EXIF:-1}
EXIF_PATCHES=""
if [ "$EXIF" = "1" ]; then
    python3 -I tools/exif.py asm > build/obj/exif.inc
    ECAVE=$(asm exif_cave 0xbb3f8 0xbb774)
    EJUMP=$(asm exif_jump 0x18328 0x1832c --defsym=HOOK=$(nmsym exif_cave exif_write))
    # Videos: UTC dates (the stock firmware takes off 8 h) on the movie and its tracks.
    MOV_OFFSET=$(python3 -I -c "import sys; s=sys.argv[1]; h,m=s[1:].split(':'); print((-1 if s[0]=='-' else 1)*(int(h)*3600+int(m)*60))" "${EXIF_OFFSET:-+05:30}")
    MTIME=$(asm mov_time 0x88180 0x88194 --defsym=MOV_OFFSET=$MOV_OFFSET)
    # Videos: make, model and artist (udta), in the dead range 0xbb774-0xbbc00.
    python3 -I tools/exif.py udta > build/obj/udta.inc
    MMETA=$(asm mov_meta 0xbbaa0 0xbbb08)
    MHOOK=$(nmsym mov_meta mov_meta)
    MJUMP1=$(asm bl_jump 0x8c910 0x8c914 --defsym=AT=0x8c910 --defsym=HOOK=$MHOOK)
    MJUMP2=$(asm bl_jump 0x8ca1c 0x8ca20 --defsym=AT=0x8ca1c --defsym=HOOK=$MHOOK)
    EXIF_PATCHES="$ECAVE $EJUMP $MTIME $MMETA $MJUMP1 $MJUMP2"
fi
# Photo sizes and JPEG quality (tools/photo.py; unset = the factory's).
#   SIZE43=1280x960 SIZE169=1280x720 ...  one per aspect setting, downscales only:
#     tools/patches/size_cave.s, in the dead 0xbb340-0xbb3f8, takes that
#     aspect's slots of the photo size table (0xf3d0). Video stays stock.
#   JPEG_Q=80   the photo encoder's IJG quality (FUN_00011724's three movs).
SIZE_PATCHES=$(python3 -I tools/photo.py quality)
if [ -n "${SIZE169}${SIZE32}${SIZE43}${SIZE11}" ]; then
    python3 -I tools/photo.py asm > build/obj/size.inc
    SCAVE=$(asm size_cave 0xbb340 0xbb3f8)
    SLOTS=$(python3 -I tools/photo.py patches $(nmsym size_cave sz169) $(nmsym size_cave sz32) \
        $(nmsym size_cave sz43) $(nmsym size_cave sz11))
    SIZE_PATCHES="$SIZE_PATCHES $SCAVE $SLOTS"
fi
# Every mode takes the factory's sizes. Until v028 the normal mode had aspect
# slots of its own (6, 7, 8, 10 and 13), and a camera can still have one
# saved: their entries in both size tables (photo @0xf3d0, video @0xf0a0) stay
# the factory handlers of aspects 0-4 (nothing else uses those slots).
NORMAL_PATCHES="0xf3e8:10f70000:9cf70000 0xf3ec:24f70000:9cf70000 0xf3f0:38f70000:b0f70000 0xf3f8:4cf70000:c4f70000 0xf404:88f70000:d4f60000
    0xf0b8:58f60000:f8f50000 0xf0bc:68f60000:f8f50000 0xf0c0:d8f70000:a8f60000 0xf0c8:d8f70000:88f60000 0xf0d4:d8f70000:98f60000"
python3 tools/patch_code.py "$OUT" "$OUT" \
    "$HOOK_JUMP" "$CYC_JUMP" "$CAVE" "$LCAVE" "$LJUMP" "$KJUMP" "$SJUMP" $EXIF_PATCHES \
    $NORMAL_PATCHES $SPK_PATCHES $SIZE_PATCHES
