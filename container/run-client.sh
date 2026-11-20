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
    process='dreamseeker[.]exe'
    warmup_marker="$XDG_RUNTIME_DIR/byond-dpi-warmup-complete"

    dreamseeker_window() {
        local pids windows window desktop pid process_pid
        pids="$(pgrep -ix -u "$EUID" "$process" || true)"
        windows="$(timeout --kill-after=1s 1s wmctrl -l -p)" || return 1
        while read -r window desktop pid _; do
            while IFS= read -r process_pid; do
                if [ "$pid" = "$process_pid" ]; then
                    printf '%s\n' "$window"
                    return 0
                fi
            done <<<"$warmup_pid"$'\n'"$pids"
        done <<<"$windows"
        return 1
    }

    force_wine_shutdown() {
        pkill -KILL -ix -u "$EUID" 'dreamseeker[.]exe|byond[.]exe|wineserver[.]exe' || true
        # The native wineserver uses a different process name; select it by prefix.
        timeout --kill-after=1s 5s wineserver -k9 || true
        if ! timeout --kill-after=1s 5s wineserver --wait; then
            echo "Wine server did not stop; refusing to relaunch Dream Seeker" >&2
            return 1
        fi
    }

    if [ ! -e "$warmup_marker" ]; then
        printf '%s\n' cleanup-pending >"$warmup_marker"
        SECONDS=0
        wine "$dreamseeker" "$server_url" &
        warmup_pid=$!
        close_at=-1
        close_requested=false
        warmup_running() {
            kill -0 "$warmup_pid" 2>/dev/null || pgrep -ix -u "$EUID" "$process" >/dev/null
        }
        while ((SECONDS < 15)) && warmup_running; do
            if ! "$close_requested"; then
                window="$(dreamseeker_window || true)"
                if [ -z "$window" ]; then
                    close_at=-1
                elif ((close_at < 0)); then
                    close_at=$((SECONDS + 5))
                elif ((SECONDS >= close_at && SECONDS < 15)); then
                    if timeout --kill-after=1s 1s wmctrl -ic "$window"; then
                        close_requested=true
                    fi
                fi
            fi
            if ((SECONDS >= 15)); then
                break
            fi
            sleep 1
        done

        if warmup_running; then
            echo "Dream Seeker DPI warmup timed out after 15 seconds; forcing Wine shutdown before restart" >&2
            printf '%s\n' cleanup-pending >"$warmup_marker"
            kill -KILL "$warmup_pid" 2>/dev/null || true
            force_wine_shutdown
        fi
        wait "$warmup_pid" 2>/dev/null || true
        : >"$warmup_marker"
    elif grep -qx cleanup-pending "$warmup_marker"; then
        force_wine_shutdown
        : >"$warmup_marker"
    fi

    exec wine "$dreamseeker" "$server_url"
fi

exec wine "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"
