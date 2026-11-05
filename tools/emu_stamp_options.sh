#!/bin/sh
# Check the stamp's build options (tools/digicam.py STAMP_*) in the emulator:
# rebuild with each non-default combination below and run emu_digicam.py with
# the same settings, then rebuild and check the default.
#   sh tools/emu_stamp_options.sh PHOTO.jpg
# PY = a python with unicorn, numpy and pillow (default: the repo's .venv).
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-$ROOT/.venv/bin/python3}
PHOTO=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
for opts in "STAMP_ORDER=ymd STAMP_TIME=1 STAMP_COLOR=red" \
            "STAMP_ORDER=mdy STAMP_COLOR=green" \
            "STAMP_TIME=1 STAMP_COLOR=yellow"; do
    echo "== $opts"
    env $opts sh "$ROOT/tools/build.sh" >/dev/null
    env $opts "$PY" "$ROOT/tools/emu_digicam.py" "$PHOTO"
done
echo "== default"
sh "$ROOT/tools/build.sh" >/dev/null
"$PY" "$ROOT/tools/emu_digicam.py" "$PHOTO"
