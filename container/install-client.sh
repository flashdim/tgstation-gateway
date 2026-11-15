#!/bin/sh
set -eu

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
# Mono and Gecko setup dialogs cannot be answered on the virtual display.
run_stage "Wine prefix initialization" 90s \
    env WINEDLLOVERRIDES=mscoree,mshtml=d wineboot --init
run_stage "Wine prefix startup" 30s wineserver --wait
run_stage "Winetricks vcrun2022" 120s winetricks -q vcrun2022
run_stage "Winetricks dxtrans" 120s winetricks -q dxtrans
run_stage "Winetricks dxvk2071" 120s winetricks -q dxvk2071
run_stage "Winetricks webview2" 240s winetricks -q webview2
run_stage "Wine process shutdown" 30s wineserver -k
run_stage "Wine server shutdown" 30s wineserver --wait
if [ ! -f "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe" ]; then
    echo "BYOND installation did not produce the expected executable" >&2
    exit 1
fi

if ! find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
    -name msedgewebview2.exe -print -quit | grep -q .; then
    echo "WebView2 installation did not produce the expected runtime" >&2
    exit 1
fi
