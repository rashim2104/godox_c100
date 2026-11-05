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
# Presets (match palettes x film colours) with their contrast and brightness,
# rnd and the normal mode (no effect) on or off, tags and display codes from
# tools/palettes.py (PRESETS_JSON), included by the caves. The preset data is too big for the
# photo cave: it goes in the unused end of the fx4 cave's dead range,
# 0xbbc00-0xbc400 (see tools/patches/preset_data.s).
python3 -I tools/palettes.py asm > build/obj/palettes.inc
python3 -I tools/digicam.py asm > build/obj/digicam.inc   # the digicam modes' ISP profiles
nmsym() {  # nmsym OBJ LABEL: address of a label in an assembled cave
    $LLVM/llvm-nm "build/obj/$1.o" | awk -v s="$2" '$3 == s { print "0x" $1 }'
}
PDATA=$(asm preset_data 0xbbc00 0xbc400)
CAVE=$(asm photo_cave 0xbab6c 0xbb340 \
    --defsym=MATCH_ADDR=$(nmsym preset_data MATCH_PALETTES) --defsym=PMATCH_ADDR=$(nmsym preset_data PRESET_MATCH) \
    --defsym=DPTRS_ADDR=$(nmsym preset_data DISPLAY_PTRS) --defsym=TAGS_ADDR=$(nmsym preset_data TAGS) \
    --defsym=FX_ADDR=$(nmsym preset_data PRESET_FX) \
    --defsym=GBTONE_ADDR=$(nmsym preset_data gb_tone_fill) --defsym=UDIV_ADDR=$(nmsym preset_data udiv) \
    --defsym=ISPPROF_ADDR=$(nmsym preset_data isp_profile))  # dead FUN_000bab6c
sym() {  # address of a label in the assembled photo cave
    nmsym photo_cave "$1"
}
HOOK_JUMP=$(asm hook_jump 0x15448 0x1544c --defsym=HOOK=$(sym hook))
CYC_JUMP=$(asm cyc_jump 0x187c4 0x187c8 --defsym=STUB=$(sym idx_stub))  # per-photo palette + table
# fx_strip's 4x4 blocks (FX_PIX4, the GBC preset) at a fixed 0xbb774, in the
# dead FUN_000bb774 (tools/patches/fx4.s).
FX4CAVE=$(asm fx4 0xbb774 0xbbaa0 --defsym=PVARS_ADDR=$(sym VARS))
# Preset mode on the see-through display and the center button (LCDTAG=1,
# default; LCDTAG=0 = stock blank display, center button does nothing, always
# the first preset): in photo and video mode the center button cycles the
# presets and rnd (a random preset per photo/recording), and the display's
# shutter-speed readout cells show the current one. Redirects the refresh's
# tail call to 0x20fd0 (SS readout) at 0x21218 and the center key handler's
# message post at 0x1ddf8 into a third cave in the same dead code,
# 0xbc400-0xbc744. See tools/patches/lcd_cave.s. It also switches to the
# factory's sizes in the normal mode (aspect slots 6, 7, 8, 10 and 13,
# NORMAL_PATCHES below), redirecting the arrow keys' aspect change at 0x213e0
# and the display's aspect bracket at 0x4a818 there too.
LCDTAG=${LCDTAG:-1}
STORY=${STORY:-1}
LCD_PATCHES=""
if [ "$LCDTAG" = "1" ]; then
    LCAVE=$(asm lcd_cave 0xbc400 0xbc660)
    LJUMP=$(asm lcd_jump 0x21218 0x2121c --defsym=HOOK=$(nmsym lcd_cave lcd_hook))
    KJUMP=$(asm key_jump 0x1ddf8 0x1ddfc --defsym=HOOK=$(nmsym lcd_cave center_hook))
    [ "$STORY" = "1" ] && KJUMP=""      # the story's center hook goes first, then center_hook
    AJUMP=$(asm aspect_jump 0x213e0 0x213e4 --defsym=HOOK=$(nmsym lcd_cave aspect_hook))
    BJUMP=$(asm bracket_jump 0x4a818 0x4a81c --defsym=HOOK=$(nmsym lcd_cave bracket_hook))
    LCD_PATCHES="$LCAVE $LJUMP $KJUMP $AJUMP $BJUMP"
fi
# A story on the display at startup (STORY=1, default; STORY=0 leaves it out):
# STORY.TXT from the SD card root (none there: no story), one line at a time
# on the ISO/F/SS cells, the right arrow and the shutter to the next line, the
# left arrow back, until past the last. Font from story/font.json (STORY_FONT), see tools/story.py
# and tools/patches/story_cave.s. Caves in the rest of the dead code: the
# drawing at 0xba74c-0xba91c (dead FUN_000ba74c), the file at 0xbb340-0xbb3f8
# (the end of the photo cave's dead function), the hooks at 0xbbb08-0xbbc00
# (the end of the fx4 cave's) and the font at 0xbc660-0xbc744 (the end of
# the display cave's). Hooks: the card mount (bl at 0x3e03c), the display
# refresh (b at its start, 0x21318: only the line, nothing else, during the
# story), the arrows' and center's posts (bl at 0x1dd44, 0x1deac, 0x1ddf8)
# and the shutter (0x1dff8).
STORY_PATCHES=""
if [ "$STORY" = "1" ]; then
    python3 -I tools/story.py asm > build/obj/story.inc
    SDATA=$(asm story_data 0xbc660 0xbc744)
    SCAVE=$(asm story_cave 0xba74c 0xba91c --defsym=FONT_ADDR=$(nmsym story_data FONT) \
        --defsym=WIDE_ADDR=$(nmsym story_data WIDE) --defsym=PUT_ADDR=$(nmsym story_data put))
    SVARS=$(nmsym story_cave VARS)
    SLOAD=$(asm story_load 0xbb340 0xbb3f8 --defsym=VARS_ADDR=$SVARS --defsym=PATH_ADDR=$(nmsym story_cave PATH))
    CENTER_NEXT=0x42c                   # the stock post, or with LCDTAG=1 center_hook
    [ "$LCDTAG" = "1" ] && CENTER_NEXT=$(nmsym lcd_cave center_hook)
    SHOOKS=$(asm story_hooks 0xbbb08 0xbbc00 --defsym=VARS_ADDR=$SVARS --defsym=CENTER_NEXT=$CENTER_NEXT \
        --defsym=PREV_ADDR=$(nmsym story_cave story_prev) --defsym=DRAW_ADDR=$(nmsym story_cave draw))
    hook() {  # hook b|bl AT LABEL: a branch at AT to a label of story_hooks / story_load
        obj=story_hooks; [ "$3" = story_load ] && obj=story_load
        asm "$1_jump" "$2" "$(printf '0x%x' $(($2 + 4)))" --defsym=AT=$2 --defsym=HOOK=$(nmsym $obj "$3")
    }
    STORY_PATCHES="$SDATA $SCAVE $SLOAD $SHOOKS $(hook bl 0x3e03c story_load) $(hook b 0x21318 story_refresh)
        $(hook bl 0x1dd44 story_left) $(hook bl 0x1deac story_right) $(hook bl 0x1ddf8 story_center)
        $(hook b 0x1dff8 story_shutter)"
fi
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
    # Videos: make, model and artist (udta), in the end of the fx4 cave's dead range.
    python3 -I tools/exif.py udta > build/obj/udta.inc
    MMETA=$(asm mov_meta 0xbbaa0 0xbbb08)
    MHOOK=$(nmsym mov_meta mov_meta)
    MJUMP1=$(asm bl_jump 0x8c910 0x8c914 --defsym=AT=0x8c910 --defsym=HOOK=$MHOOK)
    MJUMP2=$(asm bl_jump 0x8ca1c 0x8ca20 --defsym=AT=0x8ca1c --defsym=HOOK=$MHOOK)
    EXIF_PATCHES="$ECAVE $EJUMP $MTIME $MMETA $MJUMP1 $MJUMP2"
fi
# The digicam modes' date stamp: the firmware's own photo stamp (FUN_00019568,
# off in the stock settings), which isp_profile (photo_cave.s) turns on per
# photo in a digicam mode. As '26 11 05 (format at 0xd0fc8, its length check
# at 0x1c164, year_fix for the two-digit year at the snprintf's bl, 0x1c160),
# in orange (the literal at 0x1c650: Y << 16 | U << 8 | V).
STAMP_PATCHES="0xd0fc8:$(python3 -I -c "print(b'%04u/%02u/%02u %02u:%02u:%02u\0'.hex())"):$(python3 -I -c "print(b\"'%02u %02u %02u\".ljust(30, b'\0').hex())")
    0x1c164:130050e3:090050e3 0x1c650:8080ff00:c334a100
    $(asm bl_jump 0x1c160 0x1c164 --defsym=AT=0x1c160 --defsym=HOOK=$(nmsym preset_data year_fix))"
# Resolution jump table @0xf3d0 (ldrls pc,[pc,idx,lsl#2] @0xf3c8): entries hold
# absolute handler addresses, so point each photo aspect ratio straight at its
# cave stub. 0/1=16:9 1920, 2=3:2 1616, 3=4:3 1440, 4=1:1 1024; b/c = hi-res.
jt() {  # jt ENTRY OLDHEX LABEL -> ENTRY:OLDHEX:<label address, little-endian>
    printf '%s:%s:%s\n' "$1" "$2" "$(python3 -I -c "import sys; print(int(sys.argv[1], 0).to_bytes(4, 'little').hex())" "$(sym "$3")")"
}
# The normal mode uses the factory's sizes: its aspects are slots 6, 7,
# 8, 10 and 13 (lcd_cave.s NIDX), whose entries in both tables (photo @0xf3d0,
# video @0xf0a0) become the factory handlers of aspects 0-4, copied from the
# original (nothing else uses those slots).
NORMAL_PATCHES="0xf3e8:10f70000:9cf70000 0xf3ec:24f70000:9cf70000 0xf3f0:38f70000:b0f70000 0xf3f8:4cf70000:c4f70000 0xf404:88f70000:d4f60000
    0xf0b8:58f60000:f8f50000 0xf0bc:68f60000:f8f50000 0xf0c0:d8f70000:a8f60000 0xf0c8:d8f70000:88f60000 0xf0d4:d8f70000:98f60000"
python3 tools/patch_code.py "$OUT" "$OUT" \
    "$HOOK_JUMP" "$CYC_JUMP" "$PDATA" "$CAVE" "$FX4CAVE" $LCD_PATCHES $STORY_PATCHES $EXIF_PATCHES $STAMP_PATCHES \
    "$(jt 0xf3d0 9cf70000 stub169)" \
    "$(jt 0xf3d4 9cf70000 stub169)" \
    "$(jt 0xf3d8 b0f70000 stub32)" \
    "$(jt 0xf3dc c4f70000 photo43)" \
    "$(jt 0xf3e0 d4f60000 stub11)" \
    $NORMAL_PATCHES \
    "$(jt 0xf3fc 60f70000 photo43)" \
    "$(jt 0xf400 74f70000 photo43)" \
    $SPK_PATCHES
