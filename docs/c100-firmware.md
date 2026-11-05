# Godox C100 firmware hacking

_Last updated 2026-11-05_

**Now (`v032`):** six modes on the center button, `nor` → `CCD` → `Y2K` →
`bW` → `nGt` → `SUn`: the factory camera, and five early-2000s digicam looks
done in the camera's own ISP (full resolution, hardware JPEG; tone, colour,
vignette), with a clean orange `05 11 '26`
date stamp (DD MM 'YY) in the corner of every digicam photo and video. Videos
take the mode's look too. Photo size and JPEG quality are build options. Synthesized digicam
sounds (shutter "ka-chak", power-on chime, mode click). EXIF in every photo,
UTC dates in videos, and [`rASHIM` on the display at boot](#boot-splash) in
place of the GODOX logo.

The pixel-art presets (palettes, dithering, small photos and video, the site
editor, `v009`–`v027`) are gone since `v029`; they are in git history and
`build_backups/`.

## Status

| Feature | State |
|---|---|
| [Digicam modes](#digicam-modes) CCD and Y2K: gamma curves and colour matrix per mode in the ISP | on the camera, working (`v028`, 2026-11-05) |
| [Date stamp](#the-date-stamp) `DD MM 'YY`, bottom right, digicam modes only, drawn in the strip hook | on the camera (`v029`, IMG_0031–0036); clean italic digits `v031`, emulator |
| [Sounds](#sounds): shutter, power-on chime, mode click (`tools/sounds.py`) | emulator (`v029`) |
| [Center button](#mode-button-and-display) cycles the mode in photo/video mode, display shows it, kept across power-off | on the camera, working (since `v017`) |
| [EXIF in every photo](#exif): make, model, software, artist, date/time from the RTC with its UTC offset, pixel size, exposure time, ISO, f/2.4, white balance; videos: UTC dates, make, model, artist | photos on the camera (`v026`); video `v027` |
| [Boot splash](#boot-splash): `rASHIM` on the display's 7 cells instead of the GODOX logo | emulator (`v030`) |
| [More modes](#more-modes-and-stamp-options) BW, NGT, SUN; stamp order, time and colour as build options | emulator (`v032`) |
| [Vignette](#the-isp-look-vignette): lens shading off in the digicam modes | on the camera (`v032`) |
| [Digicam modes on video](#digicam-modes-on-video): the mode's ISP profile and the date stamp in every frame | emulator (`v032`) |
| [Photo sizes and JPEG quality](#photo-sizes-and-jpeg-quality): `SIZE*`, `JPEG_Q` | emulator (`v032`), factory by default |

Contents: [The device](#the-device) · [Image layout](#firmware-image-layout-gp_cardvr_upgradebin-v116) ·
[Tooling](#tooling) · [Backups](#backups-in-build_backups) · [Code caves and hooks](#code-caves-and-hooks) ·
[Photos](#photos) · [Digicam modes](#digicam-modes) · [Vignette](#the-isp-look-vignette) · [EXIF](#exif) · [Video](#video) · [Sounds](#sounds) ·
[UI graphics](#ui-graphics-gpzp-logos-and-the-osd-overlay) · [Ideas](#ideas-not-yet-done)

## The device

- Chip: **GeneralPlus GP22B** (ARM926-class, little-endian ARMv5TE, runs
  FreeRTOS). Measured at ~310 M instructions/s in the old video
  hook (`v020`); an ARM926 retires at most one
  instruction per cycle, so it runs at **≥ ~310 MHz**.
- Sensor: **GalaxyCore GC2083**, 1920×1080 native (16:9 uses the whole sensor;
  the other aspect ratios are crops of it).
- Storage: SPI flash; photos and videos on the microSD (TF) card in `DCIM`, as
  `IMG_xxxx.jpg` and `IMG_xxxx.mov`.
- Firmware update: copy `GP_CARDVR_UPGRADE.BIN` to the SD card root, restart,
  wait for the LED to stop flashing. The updater checks only a 4-byte magic:
  **no checksum, no signature**, so modified firmware is accepted.

## Firmware image layout (`GP_CARDVR_UPGRADE.BIN`, v1.1.6)

| File offset | Contents |
|---|---|
| `0x00000` | bootloader + `PGpssiipps` header (no SD-update code here) |
| `0x10000` | app header `GPCODEROM` |
| `0x10200` | **app code**, loaded at **RAM 0x0** (so `file offset = addr + 0x10200`) |
| `0x170000` | resource table (sounds, logos, fonts), 512-byte-sector offsets |

The SD updater lives in the app, so a patch that still boots and still reaches
the SD-card check is always recoverable by re-flashing a good build. Only
breaking the boot path or the updater itself would remove SD recovery. Photo
and video code only runs while taking a photo or recording, so bugs there are
always recoverable.

## Tooling

In `tools/`:

- `build.sh` — **rebuilds `build/GP_CARDVR_UPGRADE.BIN` from the original**:
  applies sounds, then assembles each `tools/patches/*.s` and patches it in.
  Fails if a patch overflows its slot or has an unresolved relocation. Options
  (environment variables):

  | Variable | Default | Effect |
  |---|---|---|
  | `SILENT` | 0 | 1 = no sounds and the speaker amp never switched on; 0 = the [digicam sounds](#sounds) |
  | `SHUTTER_WAV`, `POWERON_WAV`, `CLICK_WAV` | `build/sounds/*.wav` | other sounds (11025 Hz mono 16-bit, at most the slot) |
  | `EXIF` | 1 | [EXIF](#exif) in photos, metadata in videos; 0 = left out |
  | `VIDEOLOOK` | 1 | [the mode's look and stamp on video](#digicam-modes-on-video); 0 = factory video |
  | `SIZE169`, `SIZE32`, `SIZE43`, `SIZE11` | factory | [photo size](#photo-sizes-and-jpeg-quality) per aspect, `WxH` |
  | `JPEG_Q` | factory | photo JPEG quality, 1–98 |
  | `STAMP_ORDER`, `STAMP_TIME`, `STAMP_COLOR` | `dmy`, 0, `orange` | [stamp options](#more-modes-and-stamp-options) |

  The UI/focus beep (`BEEP.wav`) is silenced in every build.
- `digicam.py` — the [digicam modes](#digicam-modes): the profiles (tone
  curves, casts, saturation) turned into the ISP's gamma knots and colour
  matrices, the display codes, and the [date stamp](#the-date-stamp)'s
  glyphs and blend. `digicam.py asm` writes `digicam.inc` for the caves;
  `digicam.py preview IMG.jpg OUT` renders the looks off-camera, `digicam.py
  stamp OUT.png` the stamp.
- `photo.py` — the size stubs and quality patches for `SIZE*` / `JPEG_Q`.
- `sounds.py` — synthesizes the [sounds](#sounds) into `build/sounds/`.
- `emu_digicam.py` — runs the built digicam cave in Unicorn: per mode the ISP
  must get the mode's tables, and the strip hook must turn a real photo (in
  32-row strips, the camera's layout) into exactly `digicam.apply_stamp` of it:

  ```
  uv run --with unicorn,numpy,pillow tools/emu_digicam.py IMG.jpg
  ```
- `emu_seg.py` — runs the display's segment code (HT1621) and the center
  button in the emulator against the factory firmware (see
  [The transparent display](#the-transparent-display-a-segment-panel-ht1621)).
- `emu_exif.py` — EXIF in the emulator.
- `emu_video.py` — the video hooks: record start must set the mode's profile
  and look, and the frame hook must burn exactly `digicam.apply_stamp` into a
  frame. `emu_size.py` — the size stubs, tables and Q patches.
  `emu_stamp_options.sh` — builds and checks every stamp option combination.
- `patch_code.py` — apply byte patches addressed by RAM address; refuses to
  touch the bootloader or the SD updater, and verifies the original bytes first.
- `gp_res.py` — list/extract the resource table. `patch_res.py` — replace a
  resource (e.g. a WAV) in place, format- and size-checked. `mk_silence.py` —
  make a silent copy of a WAV (same header/size, data zeroed).
- `exif.py` — the EXIF template. `gpzp.py` — decode/encode the GPZP UI
  images (see [UI graphics](#ui-graphics-gpzp-logos-and-the-osd-overlay)).

Reverse engineering: Ghidra headless project under `build/ghidra/`, decompiled
C in `decomp/c100.c`, string→function index in `decomp/strings.tsv`
(scripts in `tools/ghidra/`). Raw disassembly via Homebrew `llvm-mc
--disassemble` on bytes sliced from the image (disassemble word by word:
literal pools are invalid instructions, and llvm-mc silently drops those,
which shifts every address after them).

## Backups (in `build_backups/`)

- `v001_original.bin` — factory v1.1.6.
- `v002_updated_sounds.bin` — + custom shutter / power-on sounds.
- `v003_smaller_image.bin` — + 4:3 photo mode remapped to 320×240.
- `v004_bw.bin` — + clean black & white (320×240). Re-flashed to confirm the
  photo path is fully recoverable.
- `v005_bw_dithering.bin`, `v006_first_colored_dithering.bin`,
  `v007_cycled_color_palettes_dithering.bin`,
  `v008_cycled_color_palettes_dithering_larger.bin` — the dithering steps up to
  the v1 palettes at 640 wide.
- `v009_more_palettes.bin` — 8 palettes of 10–32 colours, lookup table,
  random palette per photo (first photos: IMG_0199–0209).
- `v010_speaker_silenced.bin` — + palette tag, speaker amp never switched on
  (`SILENT=1`).
- `v011_small_video.bin` — + 640-wide video at every aspect ratio.
- `v012_color_dithered_video.bin` — + palette dithering and the palette tag on
  video (`SILENT=1`, default settings otherwise).
- `v013_active_palette_displayed.bin` — + the next palette's tag on the
  see-through display (ISO cells).
- `v014_presets.bin` — the 8 palettes replaced by 12 presets (3 palettes × 4
  films), three-letter code on photos/video and on the display's SS cells
  (`SILENT=1`). Works on the camera.
- `v015_preset_modes.bin` — 3 presets (EP6, 6FP, BW) + rnd, chosen with the
  center button, shown on the display; table kept while the preset stays
  (`SILENT=1`). On the camera the presets and display work, but the center
  button does nothing: it hooked the `IO_ISO` key, which is an arrow.
- `v016_center_button.bin` — v015 with the hook on the real center key
  (`F_key`, `0x1ddf8`). Works on the camera.
- `v017_mode_saved.bin` — + the mode kept in the camera's saved settings
  (survives power-off), W on the display with mirrored halves. Works on the
  camera.
- `v018_larger_photos.bin` — photos at ~420k pixels (864×484, 800×536,
  752×564, 640×640), video unchanged. Works on the camera.
- `v019_photos_274k.bin` — photos at ~274k pixels (704×396, 640×428, 608×456,
  528×528), video unchanged. Works on the camera.
- `v020_video_274k.bin` — video at the same sizes as photos. Works on the
  camera.
- `v021_editor_template.bin` — v020's code with the preset data in fixed
  slots (room for 8 presets of 32 colours), silent (`SILENT=1`), the same
  three presets and rnd. Behaves as v020 does; differs from it only in the
  photo cave's literals, the preset data and the display table. The site's
  download and editor template until v022. Works on the camera, and so do
  editor builds from it (2026-10-18).
- `v022_editor_template.bin` — v021 with the size stubs reading a table of
  their own (16 words: W, H, crop W, crop H per aspect) instead of merged
  `ldr =` literals, so the editor can set each size; same sizes, so it should
  behave as v021 does. The current build, the site's default download and the
  editor's template (`site/editor/`; v021 is now only in `build_backups/`).
  The site's default download until v023.
- `v023_editor_template.bin` — v022 plus the normal mode
  (after rnd) and contrast and brightness per
  preset. The site's default download
  until v024. Works on the camera (2026-10-26).
- `v024_editor_template.bin` — v023 plus the Game Boy Camera
  settings (ramp, tone, 4×4 pixels, sharpening; one
  strip routine for both hooks), GBC as a fourth built-in look and 6FP with 11
  colours, with the editor's contrast, brightness and sharpening for 6FP and
  BW. The site's default download until v025. Works on the camera (2026-10-26).
- `v025_editor_template.bin` — v024 plus the story at
  startup (`STORY.TXT` on the 7 cells; removed in `v030`) (silent, `SILENT=1`). The editor's template
  and the site's default download until v028. Nothing else shows on
  the display during the story (the first v025 still showed the icons,
  brackets and battery). Works on the camera (2026-11-02).
- `v026_exif.bin` — v025 plus [EXIF](#exif) in every photo (silent,
  `SILENT=1`). Works on the camera (2026-11-05). `EXIF=0` builds exactly v025.
- `v027_exif_video.bin` — v026 plus UTC dates and make, model, artist in
  videos. Emulator only so far.
- `v028_digicam_probe.bin` — the ISP profiles for CCD and Y2K next to the
  pixel presets, and a try at the firmware's own date stamp (byte `0x131bf8`,
  `FUN_00019568`), which never showed on photos. The looks work on the camera
  (2026-11-05, IMG_0015–0024).
- `v029_digicam.bin` — the pixel presets removed: `nor`, `CCD`, `Y2K` only,
  our own date stamp, the digicam sounds. Works on the camera (2026-11-05,
  IMG_0031–0036).
- `v030_splash.bin` — `rASHIM` at boot instead of the GODOX logo, the story
  removed. Emulator only so far.
- `v031_stamp.bin` — the clean stamp: italic, anti-aliased seven-segment
  digits, 1.35× larger, solid on bright ground. Emulator only so far.
- `v032_all.bin` — BW, NGT, SUN modes; per-mode sharpening, grain and
  vignette in the ISP; the mode's look and the stamp on video. Factory photo
  size and quality. On the camera (IMG_0039–0044): stamp and video stamp
  work; far too noisy indoors (NR at the bright level).
- `v033_nr.bin` — NR and sharpening follow the tuner's gain level; grain
  modes halve the thresholds instead of setting 1. On the camera
  (IMG_0045–0051): better, still 5–10× noisier than `v029`.
- `v034_clean.bin` — sharpening and NR left to the camera; the digicam modes
  keep only the vignette. Emulator only so far.

## Code caves and hooks

Everything is patched into dead code, and every hook replaces the first
instruction of a firmware function with a branch to a cave, which re-runs that
instruction and jumps back (e.g. the photo hook replaces `str lr, [sp, #-4]!`
at `0x15448` and returns to `0x1544c`).

| Hook point | When it runs | Cave entry | Purpose |
|---|---|---|---|
| `FUN_00015448` | scaler "strip ready" callback, photo only, **interrupt** | `hook` | the date stamp |
| `FUN_000187c4` | capture handler, once per photo, camera task | `snap` | ISP profile, draw the stamp |
| tail call `b 0x20fd0` at `0x21218` | SS readout on the see-through display, every refresh tick | `lcd_hook` | mode on the display |
| `bl 0x42c` at `0x1ddf8` (post `0x7041`) | center button, once per press | `center_hook` | step the mode |
| `0x22b38`, `0x350f0`, `0x2ed50` | — | (NOPs, `SILENT=1` only) | speaker amp off |
| `bl` at `0x35e30` (video record start) | once per recording | `rec_start` | the mode's ISP profile, draw the stamp |
| `FUN_00018d14` | every video frame, before H.264 | `vhook` | the stamp on video |
| tail call `b 0x4a64c` at `0x4ae38` | display init, once at boot | `splash` | [`rASHIM` instead of the logo](#boot-splash) |
| `0x18328`, `0x88180`, … | JPEG header write, MOV atoms | `exif_*`, `mov_*` | [EXIF](#exif) |

**Digicam cave** (`digicam_cave.s`) — dead `FUN_000bab6c`, `0xbab6c–0xbb340`
(verified against all B/BL targets and pointers, ARM and Thumb): `hook` at
`0xbab6c` (fixed: `hook_jump.s` branches here), `snap`, `isp_profile`, the
stamp's `pair`/`glyph`/`fill`, `PROFILES`, `VARS`, the glyph tables and the
two modes' gamma and matrix tables; ends `0xbb2f6` (74 B free).

**Display cave** (`lcd_cave.s`) — `0xbc400–0xbc660`, in the dead range
`0xbb774–0xbc744` (unreferenced functions `FUN_000bb774…FUN_000bc19c`):
`lcd_hook`, `center_hook`, `splash`, `SPLASH`, `LCD_TAGS`. The MOV metadata
uses `0xbbaa0–0xbbb08`; the rest of the range is free (`v025`–`v029`'s
story used `0xba74c–0xba91c`, `0xbb340–0xbb3f8`, `0xbbb08–0xbbc00` and
`0xbc660–0xbc744`).

Not dead after all, for the next search: `0x80c–0xc38` (unreferenced by
branches, but `0x80c` is a timer callback passed at `0xcb8`, and `0xbf4` /
`0xc18` are callback pointers at `0x24b4`) and `0xc589e–0xc5d30` (Thumb
libm code with a Thumb branch into it from `0xc609c`).

**Profile data** (`profile_data.s`) — `0xbbc00–0xbc400`: `PROFILES`, the
gamma/matrix tables, `LSC_ZERO`.
**Video look** (`video_look.s`) — `0xbb774–0xbbaa0`: `rec_start`, `vhook`.
**Size cave** (`size_cave.s`) — `0xbb340–0xbb3b0`: the `SIZE*` stubs.
Still free: `0xba74c–0xba91c`, `0xbbb08–0xbbc00`.

Only `hook` has a fixed address. `build.sh` reads every other address from
the object files (`llvm-nm`) and patches the jumps with them.

**Stale aspect slots.** `v023`–`v028`'s normal mode moved the UI's aspect to
slots 6, 7, 8, 10 and 13 of the photo (`0xf3d0`) and video (`0xf0a0`) size
tables. A camera flashed while in that mode keeps such a slot in its saved
settings, so `build.sh NORMAL_PATCHES` still points those slots at the
factory handlers of aspects 0–4; the next arrow press brings the aspect back
into 0–4.

## Photos

Photos are the factory's: the four aspect settings at 1920×1080, 1616×1080,
1440×1080 and 1024×1024, hardware JPEG (`FUN_0000f004` builds each capture
size; the photo size switch is the jump table at `0xf3d0`).

### Photo sizes and JPEG quality

`SIZE169`/`SIZE32`/`SIZE43`/`SIZE11=WxH` give an aspect setting its own size:
a stub on the `0xf3d0` jump table sets crop and output size and rejoins the
factory path at `0xf188`. The crop is the largest of the size's shape inside
the stock crop, so the bracket still frames it; downscale only, width a
multiple of 16, at least 320×240. `JPEG_Q=1..98` replaces the three
`mov r3, #Q` in `FUN_00011724` (stock: setting 0 → 98, 2 → 80, else 90; our
cameras use 90). A "2005 compact" build: `SIZE43=1280x960 SIZE169=1280x720
JPEG_Q=80`.

### Strip buffer format

Decoded from on-camera diagnostics. The scaler delivers the photo in
**32-row strips** into a double buffer (strip A at `PHOTO+0x18`, strip B right
after it; `PHOTO = 0x1317ac`); the hook gets one strip per call, A or B.
`STRIP_BYTES` (value at `0x13155c`) `= width × 32 × 3/2`. The pixel format
(`PHOTO+0x20`) is `'"'` (0x22) = **YUV 4:2:0**, laid out **row-interleaved
with a parity twist**. With `stride = width × 3/2` and `third = width/2`, each
2-row band (rows `2b`, `2b+1`) is:

```
even row:  luma Y [0, 2*third)            chroma pairs 0..third/2-1  [2*third, 3*third)
odd  row:  chroma pairs third/2..third-1  [0, third)   luma Y [third, 3*third)
```

So one **2×2 block** = one chroma (U,V) pair shared by 4 luma samples (2 in the
even row, 2 in the odd), U and V interleaved.

The hook derives `stride`, `third` and the split point from `STRIP_BYTES`, so
it is width-agnostic. It does cache maintenance around its writes (`0x401ac`
invalidate, `0x401b8` clean) so the JPEG encoder sees them, and only ever
writes a buffer whose address matches strip A/B: an unexpected call leaves
memory untouched.

Verifying these primitives in isolation (a per-row brightness gradient, then
five solid colour bars) before attempting colour matching is what made the
colour work predictable: it separated "can we address and write pixels" from
"is the colour maths right". The video format was decoded the same way.

## Digicam modes

Two looks of a 2005 compact, done where the camera does its own colour: the
ISP. So they cost nothing per pixel, stay at full resolution, and go through
the hardware JPEG like any photo.

- **CCD** — cool and punchy, a CCD point-and-shoot in daylight: a contrasty
  S-curve with crushed shadows (`ccd_tone`), a cool shift strongest in the
  mid-tones (`ccd_cast`: Cb +2.0, Cr −1.5 weighted 4·y·(1−y)), saturation
  ×1.15.
- **Y2K** — warm and faded: lifted blacks, rolled-off highlights
  (`Y2K_POINTS`), a warm cast with a split tone (`y2k_cast`), saturation
  ×0.85–0.9.

- **BW** — monochrome, contrasty S-curve, saturation 0.
- **NGT** — a cold night: crushed blacks, darker mids, a teal-blue cast.
- **SUN** — a disposable in the sun: lifted blacks, bright mids, golden cast.

### More modes and stamp options

The display shows `bW` (W spans two cells), `nGt`, `SUn`. Stamp build
options: `STAMP_ORDER` `dmy` (default) / `ymd` / `mdy`; `STAMP_TIME=1` adds
`14:07` after a gap; `STAMP_COLOR` `orange` / `red` / `yellow` / `green`.
`emu_digicam.py` and `emu_video.py` must run with the same values as the build.

### The ISP look: vignette

Every digicam mode turns lens shading off: `isp_profile` points the
strengths at ctx+`0x17b0` at `LSC_ZERO` (stock `0xd6a9c` = 25,25,25) and
regenerates the table with `FUN_00098810()`, so the corners keep the lens's
own falloff; `nor` restores stock. Lens shading (CDSP MMIO `0xd0800000`) is
only regenerated when the strengths change.

Tried and dropped (`v032`, `v033`): per-mode sharpening (edge
`FUN_0009852c`, sharpen `FUN_000914e8`), HbNr `FUN_000915b0` and lower NR
thresholds `FUN_00090af8` for grain. Set at capture they override the
capture path's own NR: `v032` sent the bright-light NR row at every gain
level (~45× stock noise indoors, IMG_0039–0043); `v033` sent the gain tuner's
current row (its level at ctx+`0x1530`, rows 1,3,5,6 / 3,5,7,9 / 6,8,12,14 /
8,12,14,16 / 10,28,30,42 in the table at ctx+`0x17a8`) and was still 5–10×
noisier than `v029`, even in `nor` (IMG_0045–0051). Grain, if wanted, belongs
in the strip hook, not the ISP.

### The ISP tables

The ISP context is at `*0x12846c`:

- `ctx + 0x177c` → **gamma**: 0x90 bytes, 3 channels (R, G, B) × 32 knots,
  then 3 × 16 segment bytes. Stock table `0xd8050`.
- `ctx + 0x1794` → **colour matrix**: 9 `s16`, `0x80` = 1.0. Stock
  `0xd6338`.
- `FUN_000981fc()` reloads the gamma, `FUN_000982a4()` the matrix (no
  arguments).

`digicam.py` builds a mode's gamma as its tone curve and cast applied to each
stock knot (`T_c(stock knot)`), so the stock tone mapping stays underneath,
and its matrix as the saturation matrix times the stock one. `snap`
(`isp_profile`) points the two pointers at the mode's tables (`nor`: the
stock ones) and calls both reloads before every capture. Checked on the
camera with `v028` (IMG_0015–0024): channel order R, G, B as expected. The
first CCD cast (Cb +3, Cr −2.5, ×1.25) went purple indoors.

The ISP state is global, so after a digicam photo the profile stays on for
video until the next `nor` photo resets it.

### The date stamp

A digicam's date imprint in the bottom right corner: `05 11 '26` (day,
month, apostrophe, year) in italic seven-segment digits with pointed ends and
hairline gaps, anti-aliased, deep orange with a faint warm glow. Only in CCD
and Y2K, and only if the clock is set (`GETTIME` `0x52bd4` returns 0).

The firmware has a stamp of its own (enable byte `0x131bf8`, drawn by
`FUN_00019568`), but it never showed on photos (`v028`), so the cave draws
one:

1. **`snap`** (per photo, camera task): allocates a 250×54 coverage buffer
   once (`pvPortMalloc` `0x5374c`), clears it, reads the RTC (`int t[7]` =
   sec min hour mday mon year wday) and draws the glyphs into it (`glyph`,
   `seg`). Each segment of `SEGS` (a–g and the apostrophe; digits 26×46 px)
   is a hexagon, `|across| ≤ TH` and `|along| + |across| ≤` its half length,
   in 1/16 px. Per pixel of its box, row by row, `seg` takes the signed
   distance from it, with the italic's shear (`SL`/256 per unit of height)
   taken out of x, and looks up the coverage in `LUT` (255 inside, an
   anti-aliased edge 255…128 over ±½ px, then the glow 88…0 out to 2.5 px),
   max-blended. About 350k instructions (~1.1 ms) before the capture. Then
   sets `V_ON`.
2. **`hook`** (per strip, interrupt): reads the photo's W and H from the
   JPEG header template's SOF (`0xe2f50`, big-endian H at +7, W at +9), the
   stride (1.5 W) and the strip's rows from `STRIP_BYTES`, counts rows in
   `V_ROW`, and blends the buffer's rows that fall in this strip at
   `MARGIN` = 40 px from the right and bottom (`blend_y`): coverage below
   128 is glow and only lightens towards `STAMP_Y` (170); from 128 the core
   lights as the glow's edge and then covers by `(c − 128) · 2`, also over
   brighter ground, so the digits stay solid orange on white. Each 2×2
   block's chroma goes towards (50, 202) by its four pixels' mean coverage
   (`blend_c`). Cache invalidate/clean around it.

`digicam.py check()` asserts that `render` (every segment at every pixel)
equals `render_boxed` (what the cave does) for several dates.
`emu_digicam.py` checks the cave's buffer against `render` and the photo
against `digicam.apply_stamp`, byte for byte (including the clock not set,
and a mode byte that isn't a mode). Up to 125k instructions per 32-row strip
(~0.40 ms at ~310 M instructions/s).

`v029` had a blocky stamp: 18×34 px digits sheared in 6-row steps, square
overlapping segments, flat glow rings that went brown on dark ground.

## EXIF

The stock JPEGs have no APP1: only SOI, SOF0, a `GPEncode` COM, DQT, DRI,
DHT and SOS, from a 0x270-byte header template at `0xe2f50`.
`FUN_0001808c` fills in the photo's size (SOF0, height at +7, width at +9)
and ends with a tail call `write(fd, template, 0x270)` (`b 0x385a0` at
`0x18328`). `exif_jump.s` points that branch at `exif_write`
(`exif_cave.s`), which writes the same file as SOI, APP1, then the
template after its SOI. `FUN_000385a0` waits for the file task to take the
data, so one static APP1 is enough. It runs once per photo in the camera task.

The APP1 (393 B) comes from `tools/exif.py` at build time. Per photo the
camera fills in:

- **Pixel size** (`ExifImageWidth/Height`), copied from the SOF0. IFD0
  `ImageWidth/Height` are left out: they aren't allowed in a JPEG.
- **`DateTimeOriginal` and `CreateDate`.**
  - They come from the RTC via `FUN_00052bd4(int t[7])`, which gives sec,
    min, hour, mday, mon, year, wday and returns 0.
  - The firmware's `snprintf` (`0xce234`) formats them.
  - If the clock was never set, `FUN_00052bd4` returns -1, and the dates
    are the blank `"    :  :     :  :  "` EXIF uses for unknown.
  - An empty `TIME.TXT` in the card root sets the clock from the file's own
    modified time (`FUN_00037914`, also `GODOX.TXT`).
- **`ExposureTime`** = lines × 30 / 1014000 s.
  - Lines are what the AE (`FUN_0004c22c`) last programmed into the GC2083:
    the cache at `0x1241a4`, stored at `0x4c36c` after the `0x0d03/0x0d04`
    writes.
  - The AE table (`0xd6d60`, rows {lines, gain ×64, 32}, 0..291) steps in
    10 ms anti-banding units of 338 lines, so 1014 lines = 30 ms. The
    firmware's own `t·G` double at `0x1217a8` uses the same lines / 1014 × 30 ms.
  - Independently, VTS is 1125 (`0x0d41/42` in the init table at `0xd80e0`)
    at 30 fps: 29.6 µs a line either way.
  - Range: 1/33800 to 1/33 s. Only the 30 fps mode is used (mode index
    `0x12419c` is only ever written 0).
- **`ISOSpeedRatings`** = 100 × gain/64, from `0x1241a0`.
  - This is the gain ×64 (× a multiplier that defaults to 1), stored at
    `0x4c4f0` after the gain registers. Range: 100–3200.
  - It is the firmware's own convention: the light meter
    (`FUN_00021420(N, t, S)` at `0x217c0`) computes EV with S = 100 for
    t × gain/64.
  - The meter's later lux calibration (slope ~0.22) puts the real
    sensitivity nearer 450 × gain/64. EXIF uses the nominal value.
- **`WhiteBalance`**: 0 (auto) when the user setting `temp_awb`
  (`0x132160 + 0x98`) is 0, else 1 (manual, one of the presets).
- AE isn't locked for the capture, so exposure and ISO may be one frame
  ahead of the photo.

The rest is fixed at build time:

- `EXIF_MAKE` (Godox), `EXIF_MODEL` (C100), `EXIF_SOFTWARE` (C100-V1.1.6),
  `EXIF_ARTIST`, and `EXIF_OFFSET` (+05:30) for `OffsetTimeOriginal`. The
  camera has no time zone.
- **`FNumber` 2.4**: the f-number the firmware's light meter uses for this
  lens (double at `0x21a5c`). No focal length or sensor size is anywhere
  in the firmware.
- 72 dpi, sRGB, `YCbCrPositioning` and `ComponentsConfiguration`, which
  exiftool's JPEG checks require.
- Every tag has its own value: shared values pass as TIFF but fail
  `exiftool -validate`.

**Cave:** the dead `FUN_000bb3f8`, `0xbb3f8–0xbb774`, used up to `0xbb764`.
The only thing in the firmware that looks like a pointer into it is the
word `0x000bb679` at `0xc4c60`. That word is fdlibm `pow`'s √3 threshold
(`0xbb67a`), next to `0x3988e` (√(3/2)) and `0x43400000` (2⁵³), not an
address. It is full: more tags need another cave.

**Check:** `tools/emu_exif.py IMG.jpg OUT.jpg [--no-clock]`.
- It runs `exif_write` from `0x18328` on a real photo's header.
- The RTC and write are stubbed, an AE state is planted (338 lines, gain
  81, a WB preset), and the firmware's own snprintf runs.
- It checks SOI, then APP1, then the untouched rest of the template, and
  that the stack is balanced.
- exiftool then shows 1/100 s, ISO 126, f/2.4 and manual WB, and
  `-validate` reports OK.

**Videos** (also `EXIF=1`):
- **Dates.** The mvhd writer `FUN_00088078` turns the file's FAT time
  (local) into seconds since 1904, then subtracts 8 h (`sub #0x7000`,
  `sub #0x80` at `0x88188`), as if the clock ran on China time. The tkhd and
  mdhd writers always write `0xb9e3b1ce` (2002-10-29 03:32:30), from the
  literal pools at `0x88bd0` and `0x88f9c`.
  - `mov_time.s` rewrites `0x88180–0x88194` in place (the reload at
    `0x88184` was redundant). It subtracts the `EXIF_OFFSET` offset
    instead, then stores the time into both pools as well. Those pools are
    in RAM, and mvhd is written before the tracks, so every track gets the
    real UTC date.
- **Make, model, artist.** The muxer writes moov as mvhd, then
  `FUN_000884d8`, then the tracks. It does this twice: the `bl` at
  `0x8c910` sizes moov, the one at `0x8ca1c` writes it.
  - `FUN_000884d8` writes udta > meta > ilst from a key/value table at
    `ctx+0x540`. Nothing ever fills that table, and the muxer's close
    `free()`s its entries.
  - `mov_meta.s` (`0xbbaa0`, the end of the video cave's dead range;
    `video_cave` now ends there) takes both calls instead. It copies a fixed
    59-byte udta from `tools/exif.py udta` and returns its length. That
    udta holds `©mak`, `©mod` and `©ART` as QuickTime international text,
    which exiftool reads as UserData Make, Model and Artist.
  - The emulator checks the copy, and exiftool checks a MOV built around it.

## Video

Stock video: H.264 High@4.1, 1920×1080, ~28 fps, ~9 Mbit/s, 16 kHz mono PCM,
in a QuickTime `.mov` named `IMG_xxxx.mov` (the `MOVA%04d.avi` strings in the
firmware are leftovers). Small, dithered video (`v011`–`v027`) is in git history.

### Digicam modes on video

`rec_start` (the `bl` at `0x35e30`) runs `isp_profile` for the current mode
(nor: stock, so a graded photo no longer leaks into video) and draws the stamp
once into the shared buffer; `vhook` (first instruction of `FUN_00018d14`)
blends it into each frame's bottom right using the frame's W (+`0xdc`), H
(+`0xe0`) and rows (+`0xd0`), ~224k instructions per frame. The time on the
stamp is the recording's start. `VIDEOLOOK=0` leaves video factory.

## Sounds

- `tools/sounds.py` synthesizes a 2000s compact's sounds (11025 Hz mono
  16-bit, peak −0.4 dB, each checked against its slot):
  - shutter (`CAMERA.wav`, 0x1c00 B slot): the fake shutter "ka-chak", a
    bright decaying noise burst through a 3400 Hz resonance, then a duller
    one at 1900 Hz 70 ms later; 0.22 s.
  - power-on (`POWERON_AUDIO.wav`, 0x4000): a rising chime E6, G#6, B6;
    0.70 s.
  - mode click (`CLICK.wav`, 0x1800): a 2200 Hz tick; 0.03 s.
- UI/focus beep (`BEEP.wav`): always silenced.
- `SILENT=1`: all silent, speaker amp never switched on.
- Mode-switch sound = `CLICK.wav` (sound slot 0). The mode switch handlers
  (`------mode N------` at 0x1dc0c etc.) and the center button post message
  `0x7018`; the state loops answer it with `FUN_00022a80(0)`, which plays
  `CLICK.WAV` if the key-tone setting (config byte +0x19) is on.
- Sound player `FUN_00022a80(slot)`: 0=CLICK, 1=CAMERA, 2/3=POWERON_AUDIO,
  4=unused handle, 5=BEEP. It turns the **speaker amp (GPIO 0x2c)** on, waits
  100 ms, then queues the WAV to the audio task. The amp is switched off by the
  peripheral task `FUN_00021e60` on message `0x6002` (posted every ~1 s): the
  first tick after a sound arms a counter, the second prints `@@@CLOSE SPEAKER`
  and drives GPIO 0x2c low. That is the ~1–2 s of hiss after every sound, even
  a silent one. Boot (`state_startup_init`, 0x350f0) also turns the amp on
  unconditionally.
- `SILENT=1` NOPs the three amp-on calls (0x22b38, 0x350f0, 0x2ed50), so the
  amp is never powered: no sounds and no hiss.

### What the speaker does to a sound

From a phone recording of a voice clip played on the camera (2026-10-23):

- No bass: below ~1 kHz is 10–35 dB down.
- No smoothing filter after the DAC: each sample is held, so the sound comes
  back mirrored around 11025 Hz (a 1350 Hz partial also plays at 9675 and
  12375 Hz), which sounds metallic and buzzy.
- Overdrive: clips peak-normalised to 0 dB distort; every clip that plays
  cleanly peaks at −8…−12 dB and sits at ≈ −17 dB RMS.

Hence the sounds' content sits at 1.9–3.4 kHz. A higher sample rate would
move the mirrored copies out of hearing range: the audio clock setter
`FUN_000438b4` takes 8000–48000 Hz and the decode task `FUN_000052c4`
accepts PCM, MS ADPCM, A-law, µ-law and IMA ADPCM, but neither is confirmed
on the UI-sound path. Untested.

## UI graphics (GPZP, logos, and the OSD overlay)

The firmware carries pixel graphics for a 320×240 TFT (below), but the C100's
own see-through display is a segment panel; see
[The transparent display](#the-transparent-display-a-segment-panel-ht1621).

### GPZP images (menu/status assets) — editable

`.gpzp` resources are `GPZP` magic + raw fixed-Huffman DEFLATE of **RGB565**
(little-endian, 2 B/px). `0x8C71` is the transparency key (the live LCD shows
through). The LCD is **320×240**. `tools/gpzp.py` decodes/encodes these:

```
gpzp.py decode IN.gpzp OUT.png [WIDTH]     # WIDTH auto-detected if omitted
gpzp.py encode IN.png  OUT.gpzp            # width/height from the PNG
gpzp.py decode-all FIRMWARE.BIN OUTDIR     # every GPZP -> PNG
```

Round-trip is pixel-exact and re-encodes smaller than the slot (fixed Huffman).
To change one: edit the PNG (same size; alpha-0 = transparent), `encode`, then
`patch_res.py` it in (size-checked). Decoded PNGs are in `gpzp/decoded/`.
Confirmed widths: BACKGROUND 320×240, TFT_WIFI_SYM 320×240, SELECTBAR_LONG
296×40. The small bars / SP_ICON sheet have ambiguous widths (colours are always
right; only the row-wrap may be off) — pin them from their draw calls if needed.

### Power logos — editable, and unused

`POWER_ON_LOGO.jpg` is a **beach photo** and `POWER_OFF_LOGO.jpg` is **"Good
Bye!"** — plain JPEGs, left over from the OEM/children's-camera software this
firmware descends from (like `WIFI.xml`). They are standard JPEGs: replace with
a 320×240 baseline JPEG that fits the slot via `patch_res.py`.

### The transparent display: a segment panel (HT1621)

The see-through display is a **segment display**: a fixed set of printed
shapes (the GODOX logo, the brackets, 7-segment digits, the icons), each
switched dark or clear. Technically it is a segment LCD with no backlight or
reflector, which is why you can see through it. It has no pixels. The code
draws nothing; it switches segments on and off through an
**HT1621**-compatible controller, bit-banged over GPIO.

Everything below was **confirmed in the emulator** (`tools/emu_seg.py` runs
the factory code, hooks the GPIO writes and decodes the HT1621 bitstream; see
the end of this section). Only the meaning of a few icon segments is still an
inference.

- **Pins:** GPIO `0x28` = CS, `0x29` = WR (clock), `0x2a` = DATA (`0x5f` is
  switched on with them; probably the panel's supply).
- **Protocol** (`FUN_00049dc0` sends n bits, MSB first):
  - command: `100` + 8 bits + 1 (`FUN_0004a01c`)
  - write: `101` + 6-bit address + 4 data bits (`0x49e34`, which Ghidra names
    `switchD_0004a0b8::default`; it is really `seg_write(addr, nibble)`).
- **Init** `FUN_0004ad68` (called by the display task at `0xe0dc`): commands
  `01 18 24 03` (SYS EN, RC 256K, BIAS 1/2 with 3 COMs, LCD ON). Then it clears
  all 25 addresses and calls `0x4a64c(1)` (logo on).
- **RAM:** 25 addresses × 3 COMs = 75 segments. The firmware keeps a copy at
  `0x1240e0` (one byte per address). Below, `AA.c` = address `AA`, COM `c`
  (COM0 is nibble bit `8`, COM1 `4`, COM2 `2`; bit `1` is unused).
- **Ghidra gets this code wrong:** `0x4a64c`, `0x4a6e0`, `0x4a700`,
  `0x4a894`, `0x4a9fc` and `0x4aae0` are real entry points that Ghidra never
  made into functions. It stitched them into their callers through tail
  branches, so the decompiled `FUN_0001ff10`, `FUN_00020afc`,
  `FUN_00021318` … contain code that is really in `0x4a6xx`–`0x4adxx`.
  Re-run the analysis with functions defined there before trusting
  decompiled code in this range.

**Refresh:** `FUN_00021318`, called periodically from the peripheral task
(`FUN_00021c9c`). After boot it returns early for its first 4 calls (counter
`0x12170c`). From then on, every call redraws the ISO/F/SS readouts. Every
other call (counter `0x1217b0`) also redraws the mode icons and logo
(`FUN_0001fe58`), the brackets (`FUN_0004a7f4`) and the battery
(`FUN_0002122c`).

**UI state** `0x121706` (set by the mode keys/switch, `FUN_0001e4f8`,
`FUN_0001e5a8`, `FUN_0001e658`) decides what is shown:

| State | Shown | Probably |
|---|---|---|
| 0 | bracket for the current aspect, `16.0`, `16.2`, battery; readouts blank | photo |
| 1 | bracket, `14.0` (blinks while recording, with the LED on GPIO `0x2b`), `16.2`, battery; readouts blank | video |
| 2 | ISO/F/SS readouts, `16.2`, `18.0`, battery; **no bracket** | light-meter readout (your second photo) |

**Boot, replayed in the emulator** (UI state 2, ISO 200, F5.6, SS 1/25),
matching the startup photo:

| Refresh call | Panel |
|---|---|
| (init) | logo only |
| 1–4 | logo only (refresh returns early) |
| 5 | logo + ISO 200 / F5.6 / SS 1/25 readouts, no icons or battery yet |
| 6 on | logo off (`FUN_0001fe58` → `FUN_0004a670` clears `16.1`), icons and battery on |

The logo stays on only if sensor preview init failed (flag `0xf187e`, set in
`FUN_0001109c`): then `FUN_0004a670` puts the logo back instead of clearing
it.

**Segment map:**

| Segment | What | How confirmed |
|---|---|---|
| `16.1` | **GODOX logo** | only segment lit by init; cleared on the 6th refresh call |
| `06.0` | **16:9 bracket** | aspect setting 1 |
| `15.0` | **3:2 bracket** | aspect setting 2 |
| `15.1` | **4:3 bracket** | aspect setting 3 |
| `15.2` | **1:1 bracket** | aspect setting 4 (0 and ≥5 light nothing; state 2 lights none) |
| `00.1 00.2 01.0 01.1 01.2 02.1 02.2` | ISO digit 1 | 7-segment cell (`FUN_00049ea8`) |
| `03.1 03.2 04.0 04.1 04.2 05.1 05.2` | ISO digit 2 | 7-segment cell |
| `00.0`, `02.0` | ISO label / box | always on with the readout |
| `05.0`, `03.0` | fixed "0"s: ISO 400 = `4` `0` + `05.0`, ISO 1600 = `1` `6` + `03.0` + `05.0` | readout values |
| `07.0 07.1 07.2 08.0 08.1 08.2 09.1` | F digit 1 | 7-segment cell (`FUN_0004a4ec`) |
| `09.0 0a.0 0a.1 0a.2 0b.0 0b.1 0b.2` | F digit 2 | 7-segment cell (`FUN_0004a074`) |
| `06.1`, `06.2` | F label / box | always on with the readout |
| `09.2` | F decimal point (5.6, 2.8; off for 11) | readout values |
| `0d.0 0d.1 0d.2 0e.0 0e.1 0e.2 0f.2` | SS digit 1 | 7-segment cell (`FUN_0004a374`) |
| `0f.0 0f.1 10.0 10.1 10.2 11.1 11.2` | SS digit 2 | 7-segment cell (`FUN_0004a1f0`) |
| `11.0 12.0 12.1 12.2 13.0 13.1 13.2` | SS digit 3 | 7-segment cell (`FUN_0004a074`) |
| `0c.0`, `0c.1`, `0c.2` | "SS", "1/", box | always on with the readout |
| `14.2` | fixed trailing "0" for 1/1000 and faster (1/8000 = `8` `0` `0` + `14.2`) | readout values |
| `14.1` | on when the SS value comes from the table (flag `0x12170b`) | meaning unknown |
| `16.0` | camera icon (inferred) | state 0 only |
| `14.0` | video icon (inferred) | state 1 only, blinks while recording |
| `16.2`, `18.0` | metering icon and centre reticle, not yet told apart | `16.2` in every state, `18.0` in state 2 only |
| `18.2`, `17.x` | battery outline and bars (inferred) | `FUN_0002122c`, blinks at level 0 |

The readouts come from the light-meter tables: F 1.0–14 at `0xe327c`, SS 1 s–1/8000
at `0xe31e4` (floats), indexed by config bytes `0x132160+0xeb` / `+0xea`; ISO
from `+0xec`. `FUN_00020c44` rounds a metered shutter speed to that scale.

**Patch points:**

- **No logo at boot:** `0x4ae30` `mov r0,#1` → `mov r0,#0`.
- **Keep the logo on:** `FUN_0004a670` clears `16.1` itself (`and r1,r3,#251`
  at `0x4a694`, `biceq r1,r3,#12` at `0x4a698`), so set it back:
  `orrne r1,r1,#10` at `0x4a69c` → `#14`, and `orreq r1,r1,#2` at
  `0x4a6a0` → `#6`.
- **Brackets:** jump table at `0x4a828` (`ldrls pc` at `0x4a820`, index
  `aspect − 1`) → handlers `0x4a878` (16:9, `orr r3,r3,#8` on address 6),
  `0x4a884` / `0x4a86c` / `0x4a838` (3:2 / 4:3 / 1:1, `mov r2,#8/#4/#2` into
  address `0x15`). Each bracket set is a single segment, so brackets can be
  combined (e.g. `mov r2,#0xe`) but not reshaped. They are hidden in state 2
  by the `cmp r0,#0; bne` at `0x4a804`/`0x4a814`.
- Anything else: write the segment through `seg_write` (`0x49e34`) and keep
  the copy at `0x1240e0` in sync, since the firmware read-modify-writes from it.

`tools/emu_seg.py` (`uv run --with unicorn tools/emu_seg.py`) prints the init
commands, the logo and bracket segments, checks that every digit routine
draws 7-segment digits (segment counts 6,2,5,5,4,5,6,3,7,6), decodes full
refreshes back into ISO/F/SS readouts, and replays the boot sequence.

### Boot splash

The display's init (`FUN_0004ad68`) clears all 25 addresses and ends in a
tail call to the logo routine, `b 0x4a64c` (r0 = 1: the GODOX logo, `16.1`)
at `0x4ae38`. `b_jump.s` points it at `splash` (`lcd_cave.s`), which lights
`rASHIM` on the 7 cells instead (`digicam.py SPLASH`, M over two cells;
`SPLASH_DATA`, the nibbles for addresses `0x00`–`0x13`) through `seg_write`,
and leaves the logo off. It stays through the refresh's first 4 calls (which
return early) and goes when the readouts first draw (call 5), about where
the factory's logo went off (call 6). If the sensor preview fails to start,
`FUN_0004a670` still lights the logo, as stock.

The 7 cells (`digicam.py CELLS`, found by running the firmware's digit
routines for 0–9 in the emulator):

| Cell | a | b | c | d | e | f | g |
|---|---|---|---|---|---|---|---|
| ISO 1 (`FUN_00049ea8`) | `01.0` | `02.1` | `02.2` | `01.2` | `00.2` | `00.1` | `01.1` |
| ISO 2 (`FUN_00049ea8`) | `04.0` | `05.1` | `05.2` | `04.2` | `03.2` | `03.1` | `04.1` |
| F 1 (`FUN_0004a4ec`) | `07.0` | `08.0` | `09.1` | `08.2` | `07.2` | `07.1` | `08.1` |
| F 2 (`FUN_0004a074`) | `0a.0` | `0b.0` | `0b.1` | `0b.2` | `0a.2` | `09.0` | `0a.1` |
| SS 1–3 | see [Mode button](#mode-button-and-display) | | | | | | |

`emu_seg.py` checks that init lights exactly `rASHIM` and no logo, that it
stays through the first 4 refresh calls, and that from the 6th the display
is the factory's (outside the SS cells) in photo, video and readout state.

### Mode button and display

In photo and video mode the **center button** cycles `nor` → `CCD` → `Y2K`
→ `nor`, and the display's SS cells show it (`nor`, `CCd`, `Y2K`). The mode
is used for every photo until changed, also across power-off. The readout
state (UI state 2) is unchanged: there the center button still cycles
ISO/F/SS.

**Remembering the mode** (since `v017`). The camera keeps its settings in a
0xF4-byte struct at `0x132160`, followed by a 4-byte checksum (`FUN_00023f04`).
Whenever its dirty byte `+0xa0` is 1, the firmware writes the whole struct to
NVRAM (SPI flash): at power-off (`FUN_00024094`, "config_store_power_off")
and on a peripheral-task event (near `0x22f50`). At boot it loads the struct
as a whole, and only if that fails resets it (`FUN_0002371c` →
`FUN_0002352c`). The mode lives in **byte `0xf1`**: inside the checksummed,
saved range, and unused (no load/store in the firmware uses offsets
`0xf1`–`0xf3`; it is padding after the light meter's fields). `center_hook`
writes it and sets `+0xa0`; `snap` and `lcd_hook` read it directly. Any value
above the last mode counts as `nor`.

**Buttons** (`FUN_0001f7e8` builds the key table):

| Handler | Posts | Photo/video mode | Readout state | Button |
|---|---|---|---|---|
| `F_key` `FUN_0001dd6c` | `0x7018`, `0x7041` | ignored | cycles ISO/F/SS (`*0x372bc + 1`) | **center** |
| `IO_ISO` `FUN_0001dcb8` | `0x7018`, `0x7042` | aspect −1 (`FUN_000213e0(-1)`) | value −1 | arrow |
| `T_key` `FUN_0001de20` | `0x7018`, `0x7043` | aspect +1 | value +1 | arrow |

Each posts once per press (a latch at `0x1217bc` shared by the three).

**Hooks** (`lcd_cave.s`):
- `center_hook`: `key_jump.s` redirects the `bl 0x42c` in `F_key` that posts
  `0x7041` (at `0x1ddf8`). In UI state 0/1 and not recording (`0x132abb` bit
  1) it steps the mode byte, wrapping after the last mode, and sets the dirty
  byte, then posts the message as before.
- `lcd_hook`: the display refresh draws the readouts with `0x21180(flag)`,
  ending in a tail call `b 0x20fd0` (SS, r0 = flag) at `0x21218`, which
  `lcd_jump.s` patches. In the readout state (r0 ≠ 0) it tail-calls the stock
  routine; otherwise it calls it, then writes the mode's 7 nibbles to HT1621
  addresses `0x0d`–`0x13` (only the SS cells live there) through `seg_write`
  (`0x49e34`).
- **SS cells** (`digicam.py SS_CELLS`, found by running the SS digit
  routines for 0–9 in the emulator), each wired differently:

  | Cell | a | b | c | d | e | f | g |
  |---|---|---|---|---|---|---|---|
  | 1 (`FUN_0004a374`) | `0d.0` | `0e.0` | `0f.2` | `0e.2` | `0d.2` | `0d.1` | `0e.1` |
  | 2 (`FUN_0004a1f0`) | `0f.0` | `10.0` | `11.1` | `11.2` | `10.2` | `0f.1` | `10.1` |
  | 3 (`FUN_0004a074`) | `12.0` | `13.0` | `13.1` | `13.2` | `12.2` | `11.0` | `12.1` |

Verified in the emulator (`emu_seg.py build/GP_CARDVR_UPGRADE.BIN`), against
the factory firmware run side by side: fresh settings show `nor`; center
presses step `CCD`, `Y2K`, `nor`, each still posting the stock messages and
marking the settings; a mode byte that isn't a mode shows `nor`; a press
while recording or in the readout state changes nothing; the arrow keys and
size tables are stock; everything outside the SS cells is exactly as stock.

**What the old notes got wrong.** The 320×240 TFT driver
(`tft_auo_a027dtn019_init`, panel descriptor at `0xd5c40`: 320×240, RGB565),
the 108-icon OSD compositor (`FUN_0000adb4`, icon table loaded from
`SP_ICON.GPZP` by `FUN_0005ee84`), the GPRS.pak glyph/string engine
(`FUN_000242fc`, `FUN_000259c8` …) and the parking-guide line drawer
(`FUN_0000d2e8`) are all generic OEM dashcam code. `SP_ICON` holds dashcam
icons (battery, WDR, ISO, LDW, …), `GPRS.pak` holds dashcam menu strings
("Loop recording", "Gsensor", "LDW" …), and none of it contains a Godox logo
or aspect brackets. None of it can reach the see-through panel, which is
driven only through the HT1621 pins. Whether the TFT code still runs at boot
(with no TFT attached) has not been checked; it does not matter for the
panel.

## Ideas not yet done

- Run a segment test on the transparent display to confirm the
  [segment map](#the-transparent-display-a-segment-panel-ht1621), then play
  with it (e.g. a custom startup animation from the logo and bracket segments).
