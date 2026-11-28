#!/bin/bash
# Start or stop only Dream Seeker; the BYOND pager is left alone.
set -eu

action="${1:-}"
case "$action" in
    start | stop) ;;
    *)
        echo "usage: byond-game.sh start|stop" >&2
        exit 2
        ;;
esac

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

game_pattern='(^|[\\/])dreamseeker[.]exe"?([[:space:]]|$)'

# Serialize with the full-session restart, which holds this lock while cleaning up.
exec 9>"$XDG_RUNTIME_DIR/byond-cleanup.lock"
if ! flock -w 30 9; then
    echo "Timed out waiting for BYOND startup or reset to finish" >&2
    exit 75
fi

if [ "$action" = stop ]; then
    if pkill -KILL -i -f -u "$EUID" "$game_pattern"; then
        :
    else
        status=$?
        [ "$status" -eq 1 ] || {
            echo "Failed to stop Dream Seeker" >&2
            exit 1
        }
    fi
    exit 0
fi

if [ -z "${BYOND_SERVER:-}" ] || [ -z "${BYOND_ACCOUNT:-}" ]; then
    if [ "${BYOND_GAME_QUIET:-0}" != 1 ]; then
        echo "BYOND_SERVER and BYOND_ACCOUNT are required to start Dream Seeker" >&2
    fi
    exit 0
fi
server="${BYOND_SERVER#byond://}"
if [[ ! "$server" =~ ^([a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):([0-9]{1,5})$ ]] ||
    ((10#${BASH_REMATCH[2]} < 1 || 10#${BASH_REMATCH[2]} > 65535)); then
    echo "Invalid BYOND_SERVER: expected host:port or byond://host:port" >&2
    exit 1
fi

# The viewer observation must happen after waiting for any reset to finish.
if [ "${BYOND_GAME_QUIET:-0}" = 1 ]; then
    python3 "${BYOND_VIEWER_CHECK:-/usr/local/bin/connect-on-selkies.py}" --check-viewer 2>/dev/null || exit $?
else
    python3 "${BYOND_VIEWER_CHECK:-/usr/local/bin/connect-on-selkies.py}" --check-viewer || exit $?
fi

pager_ready="$XDG_RUNTIME_DIR/byond-pager-ready"
pager_supervisor=""
pager_start=""
if [ -r "$pager_ready" ]; then
    read -r pager_supervisor pager_start <"$pager_ready" || true
fi
if [[ ! "$pager_supervisor" =~ ^[0-9]+$ ]] ||
    [[ ! "$pager_start" =~ ^[0-9]+$ ]] ||
    ! kill -0 "$pager_supervisor" 2>/dev/null ||
    [ "$(awk '{print $22}' "/proc/$pager_supervisor/stat" 2>/dev/null || true)" != "$pager_start" ] ||
    ! pgrep -i -x -u "$EUID" byond.exe >/dev/null; then
    if [ "${BYOND_GAME_QUIET:-0}" != 1 ]; then
        echo "Waiting for the BYOND pager before starting Dream Seeker" >&2
    fi
    exit 75
fi

bin_dir="$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin"
key_file="$WINEPREFIX/drive_c/users/steamuser/Documents/BYOND/key.txt"
if pgrep -i -x -u "$EUID" dreamseeker.exe >/dev/null; then
    exit 0
else
    status=$?
    if [ "$status" -ne 1 ]; then
        echo "Failed to check Dream Seeker" >&2
        exit 75
    fi
fi

if [ "${BYOND_GAME_QUIET:-0}" = 1 ]; then
    python3 "${BYOND_KEY_CHECK:-/usr/local/bin/byond-key-check.py}" "$key_file" "$BYOND_ACCOUNT" 2>/dev/null || exit 76
else
    python3 "${BYOND_KEY_CHECK:-/usr/local/bin/byond-key-check.py}" "$key_file" "$BYOND_ACCOUNT" || exit 76
fi

if [ "${SELKIES_WAYLAND:-false}" = true ]; then
    session_env="$XDG_RUNTIME_DIR/byond-xwayland"
    if ! { [ -r "$session_env" ] &&
        { IFS= read -r DISPLAY && IFS= read -r XAUTHORITY; } <"$session_env" &&
        [ -n "$DISPLAY" ] && [ -n "$XAUTHORITY" ] && [ -r "$XAUTHORITY" ]; }; then
        echo "Waiting for an authenticated XWayland display" >&2
        exit 75
    fi
    export DISPLAY XAUTHORITY
else
    export DISPLAY="${DISPLAY:-:20}"
fi

# The monitor inherits the lock even if its caller is interrupted. Wine must
# not inherit it, since the game can outlive the monitor.
(
    setsid wine "$bin_dir/dreamseeker.exe" "byond://$server" 9>&- &
    launch_pid=$!
    for attempt in {1..15}; do
        if pgrep -i -x -u "$EUID" dreamseeker.exe >/dev/null; then
            exit 0
        else
            status=$?
            if [ "$status" -ne 1 ]; then
                break
            fi
        fi
        if ! kill -0 "$launch_pid" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    kill -KILL -- "-$launch_pid" 2>/dev/null || true
    kill -KILL "$launch_pid" 2>/dev/null || true
    wait "$launch_pid" 2>/dev/null || true
    echo "Dream Seeker did not start; retrying on the next viewer poll" >&2
    exit 75
) &
monitor_pid=$!
exec 9>&-
wait "$monitor_pid"
