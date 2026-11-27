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
    echo "BYOND_SERVER and BYOND_ACCOUNT are required to start Dream Seeker" >&2
    exit 0
fi
server="${BYOND_SERVER#byond://}"
if [[ ! "$server" =~ ^([a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):([0-9]{1,5})$ ]] ||
    ((10#${BASH_REMATCH[2]} < 1 || 10#${BASH_REMATCH[2]} > 65535)); then
    echo "Invalid BYOND_SERVER: expected host:port or byond://host:port" >&2
    exit 1
fi

bin_dir="$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin"
key_file="$WINEPREFIX/drive_c/users/steamuser/Documents/BYOND/key.txt"
if ! python3 "${BYOND_KEY_CHECK:-/usr/local/bin/byond-key-check.py}" "$key_file" "$BYOND_ACCOUNT"; then
    exit 0
fi
if pgrep -i -f -u "$EUID" "$game_pattern" >/dev/null; then
    exit 0
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

# The lock descriptor must not leak into the long-lived game process.
setsid wine "$bin_dir/dreamseeker.exe" "byond://$server" 9>&- &
exit 0
