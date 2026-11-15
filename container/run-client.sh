#!/bin/bash
set -eu

XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
while [ ! -f "$XDG_RUNTIME_DIR/container-env" ]; do
    sleep 1
done
. "$XDG_RUNTIME_DIR/container-env"

# Selkies' input and webcam interposers cause Wine's VC runtime installer to
# crash and leave BYOND panels blank.
unset LD_PRELOAD

export DISPLAY="${DISPLAY:-:20}"
until timeout 2 xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
    sleep 1
done

case "${BYOND_WEBVIEW2_GPU:-0}" in
    0 | "") ;;
    1)
        if ! wine reg add 'HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments' \
            /v '*' /t REG_SZ \
            /d '--ignore-gpu-blocklist --use-gl=angle --use-angle=d3d11 --disable-direct-composition' /f; then
            echo "Failed to configure WebView2 GPU acceleration" >&2
            exit 1
        fi
        ;;
    *)
        echo "Invalid BYOND_WEBVIEW2_GPU: expected 0 or 1" >&2
        exit 1
        ;;
esac

if [ -n "${BYOND_SERVER:-}" ]; then
    server="${BYOND_SERVER#byond://}"
    if [[ ! "$server" =~ ^([a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):([0-9]{1,5})$ ]] ||
        ((10#${BASH_REMATCH[2]} < 1 || 10#${BASH_REMATCH[2]} > 65535)); then
        echo "Invalid BYOND_SERVER: expected host:port or byond://host:port" >&2
        exit 1
    fi
    exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe" "byond://$server"
fi

exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"
