#!/bin/bash
set -eu

XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
export XDG_RUNTIME_DIR
while [ ! -f "$XDG_RUNTIME_DIR/container-env" ]; do
    sleep 1
done
. "$XDG_RUNTIME_DIR/container-env"

unset LD_PRELOAD
export PATH="/opt/wine-proton/bin:$PATH"
export WINELOADER="/opt/wine-proton/bin/wine"
export WINESERVER="/opt/wine-proton/bin/wineserver"
export WINEDEBUG=-all

exec python3 /usr/local/bin/connect-on-selkies.py
