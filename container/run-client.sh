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
export PATH="/opt/wine-proton/bin:$PATH"
export WINELOADER="/opt/wine-proton/bin/wine"
export WINESERVER="/opt/wine-proton/bin/wineserver"

display_ready() {
    if [ "${SELKIES_WAYLAND:-false}" = true ]; then
        # KWin sets these after Selkies writes container-env.
        local session_env="$XDG_RUNTIME_DIR/byond-xwayland"
        [ -r "$session_env" ] &&
            { IFS= read -r DISPLAY && IFS= read -r XAUTHORITY; } <"$session_env" &&
            [ -n "$DISPLAY" ] && [ -n "$XAUTHORITY" ] && [ -r "$XAUTHORITY" ] || return 1
        export DISPLAY XAUTHORITY
    fi
    timeout 2 xdpyinfo -display "$DISPLAY" >/dev/null 2>&1
}

export DISPLAY="${DISPLAY:-:20}"
until display_ready; do
    sleep 1
done

wait_for_browser() {
    local prefix="${SELKIES_SUBFOLDER-${SUBFOLDER-}}" url response attempt
    prefix="${prefix#/}"
    prefix="${prefix%/}"
    url="localhost:${SELKIES_PORT:-8080}${prefix:+/$prefix}/api/sessions"
    for ((attempt = 0; attempt < 15; attempt++)); do
        if response="$(curl -fs --noproxy '*' --max-time 1 "http://$url" ||
            curl -fsk --noproxy '*' --max-time 1 "https://$url")" &&
            python3 -c 'import json, sys
sessions = json.load(sys.stdin)["sessions"]
sys.exit(not any(s.get("role") == "controller" and s.get("display") == "primary"
                 for s in sessions))' <<<"$response" 2>/dev/null; then
            # The session appears before the browser finishes negotiating its display size.
            sleep 2
            return
        fi
        sleep 1
    done
    echo "No Selkies browser controller detected; starting Dream Seeker anyway" >&2
}

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
    if [ "${BYOND_WAIT_FOR_BROWSER:-0}" = 1 ]; then
        wait_for_browser
    fi
    exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe" "byond://$server"
fi

exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"
