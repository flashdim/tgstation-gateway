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
        return "$status"
    fi
}

export WINEDEBUG=-all,err+all
export PATH="/opt/wine-proton/bin:$PATH"
export WINELOADER="/opt/wine-proton/bin/wine"
export WINESERVER="/opt/wine-proton/bin/wineserver"
unset LD_PRELOAD
# Mono and Gecko setup dialogs cannot be answered on the virtual display.
run_stage "Wine prefix initialization" 300s \
    env 'WINEDLLOVERRIDES=mscoree,mshtml=d' wineboot --update
run_stage "Wine prefix startup" 30s wineserver --wait
run_stage "Winetricks vcrun2022" 120s winetricks -q vcrun2022
run_stage "Winetricks dxtrans" 120s winetricks -q dxtrans
if run_stage "Winetricks corefonts" 180s winetricks -q corefonts; then
    :
else
    corefonts_status=$?
    # Winetricks returns 1 when font registration loses its wineserver connection.
    [ "$corefonts_status" -eq 1 ] || exit "$corefonts_status"
    echo "Retrying Winetricks corefonts once after Wine shuts down" >&2
    run_stage "Wine server shutdown before corefonts retry" 30s wineserver --wait
    run_stage "Winetricks corefonts retry" 180s winetricks -q corefonts
fi
run_stage "Winetricks webview2" 240s winetricks -q webview2
run_stage "Wine server shutdown" 30s wineserver --wait
if ! find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
    -name msedgewebview2.exe -print -quit | grep -q .; then
    echo "WebView2 installation did not produce the expected runtime" >&2
    exit 1
fi
