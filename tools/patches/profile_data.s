@ The modes' ISP profiles (tools/digicam.py: PROFILE_DATA): PROFILES, per mode
@ the gamma table and colour matrix isp_profile (digicam_cave.s) hands the
@ ISP, then each mode's GAMMA_* (0x90 bytes) and CCM_* (9 shorts). In the
@ dead range 0xbbc00-0xbc400 (the old preset data cave). Data only; build.sh
@ passes PROFILES to digicam_cave.s.
    .syntax unified
    .arm
    .include "digicam.inc"
base:
    .org    0xbbc00
    PROFILE_DATA
