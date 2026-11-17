#!/bin/sh
set -eu

cache_dir="$(mktemp -d)"
trap 'rm -rf "$cache_dir"' EXIT
export W_CACHE="$cache_dir"

run_stage() {
    name="$1"
    limit="$2"
    shift 2
    echo "Starting $name (timeout: $limit)"
    if timeout --kill-after=10s "$limit" "$@"; then
        echo "Completed $name"
    else
        status=$?
        if [ "$status" -eq 124 ]; then
            echo "$name timed out after $limit" >&2
        else
            echo "$name failed with exit code $status" >&2
        fi
        exit "$status"
    fi
}

export WINEDEBUG=-all,err+all
export PATH="/opt/wine-proton/bin:$PATH"
export WINELOADER="/opt/wine-proton/bin/wine"
export WINESERVER="/opt/wine-proton/bin/wineserver"
export WINEDLLOVERRIDES="${WINEDLLOVERRIDES:+$WINEDLLOVERRIDES;}tabtip.exe=d"
# Disable TabTip's UI Automation handler, which can stall older Proton prefixes.
# Mono and Gecko setup dialogs cannot be answered on the virtual display.
run_stage "Wine prefix initialization" 300s \
    env 'WINEDLLOVERRIDES=mscoree,mshtml=d;tabtip.exe=d' wineboot --init
run_stage "Wine prefix startup" 30s wineserver --wait
run_stage "Winetricks vcrun2022" 120s winetricks -q vcrun2022
run_stage "Winetricks dxtrans" 120s winetricks -q dxtrans
run_stage "Winetricks corefonts" 180s winetricks -q corefonts
run_stage "Winetricks riched20" 300s winetricks -q riched20
run_stage "Winetricks msftedit" 900s winetricks -q msftedit
run_stage "Winetricks webview2" 240s winetricks -q webview2
run_stage "Wine server shutdown" 30s wineserver --wait
if ! find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
    -name msedgewebview2.exe -print -quit | grep -q .; then
    echo "WebView2 installation did not produce the expected runtime" >&2
    exit 1
fi
