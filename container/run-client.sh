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
    dreamseeker="$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe"
    server_url="byond://$server"
    process='/dreamseeker[.]exe([[:space:]]|$)'
    warmup_marker="$XDG_RUNTIME_DIR/byond-dpi-warmup-complete"

    dreamseeker_window() {
        local pids windows window desktop pid process_pid
        pids="$(pgrep -f "$process" || true)"
        [ -n "$pids" ] || return 1
        windows="$(wmctrl -l -p)" || return 1
        while read -r window desktop pid _; do
            while IFS= read -r process_pid; do
                if [ "$pid" = "$process_pid" ]; then
                    printf '%s\n' "$window"
                    return 0
                fi
            done <<<"$pids"
        done <<<"$windows"
        return 1
    }

    if [ ! -e "$warmup_marker" ]; then
        : >"$warmup_marker"
        wine "$dreamseeker" "$server_url" &
        warmup_pid=$!
        window=""
        for _ in {1..120}; do
            if ! kill -0 "$warmup_pid" 2>/dev/null; then
                wait "$warmup_pid" || true
                warmup_pid=""
                break
            fi
            window="$(dreamseeker_window || true)"
            [ -n "$window" ] && break
            sleep 1
        done

        if [ -n "$window" ]; then
            sleep 5
            if wmctrl -ic "$window"; then
                for _ in {1..30}; do
                    if ! pgrep -f "$process" >/dev/null; then
                        wait "$warmup_pid" || true
                        warmup_pid=""
                        break
                    fi
                    sleep 1
                done
            fi
        fi

        if [ -n "$warmup_pid" ]; then
            echo "Dream Seeker DPI warmup did not close; keeping the first launch running" >&2
            wait "$warmup_pid"
            exit $?
        fi
    fi

    exec wine "$dreamseeker" "$server_url"
fi

exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"
