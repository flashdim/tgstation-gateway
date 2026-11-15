#!/bin/bash
set -eu

XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
while [ ! -f "$XDG_RUNTIME_DIR/container-env" ]; do
    sleep 1
done
. "$XDG_RUNTIME_DIR/container-env"

export DISPLAY="${DISPLAY:-:20}"
until timeout 2 xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
    sleep 1
done

exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"
