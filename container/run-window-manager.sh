#!/bin/sh
set -eu

XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
while [ ! -f "$XDG_RUNTIME_DIR/container-env" ]; do
    sleep 1
done
. "$XDG_RUNTIME_DIR/container-env"

# labwc already manages XWayland windows in a Wayland session.
if [ "${SELKIES_WAYLAND:-false}" = true ]; then
    exec sleep infinity
fi

export DISPLAY="${DISPLAY:-:20}"
until timeout 2 xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
    sleep 1
done

exec openbox
