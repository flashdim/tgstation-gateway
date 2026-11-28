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
export WINEDEBUG=-all

# A reset can interrupt this launcher while cleanup is running. Keep the lock
# inherited by cleanup commands so the next service invocation waits for them.
exec 9>"$XDG_RUNTIME_DIR/byond-cleanup.lock"
flock -x 9
pager_ready="$XDG_RUNTIME_DIR/byond-pager-ready"
rm -f -- "$pager_ready"
if timeout --kill-after=1s 15s wineserver -k; then
    :
else
    status=$?
    # Wine returns 1 both when no server exists and when signaling fails.
    if [ "$status" -ne 1 ]; then
        echo "Failed to stop the Wine session; refusing to launch BYOND" >&2
        exit 1
    fi
fi
if ! timeout --kill-after=1s 5s wineserver --wait; then
    echo "Failed to stop the Wine session; refusing to launch BYOND" >&2
    exit 1
fi

client_pattern='(^|[\\/])(dreamseeker|byond|msedgewebview2)[.]exe"?([[:space:]]|$)'
if pkill -KILL -i -f -u "$EUID" "$client_pattern"; then
    :
else
    status=$?
    if [ "$status" -ne 1 ]; then
        echo "Failed to stop BYOND or WebView2 processes; refusing to launch BYOND" >&2
        exit 1
    fi
fi
clients_stopped=false
for attempt in {1..5}; do
    if pgrep -i -f -u "$EUID" "$client_pattern" >/dev/null; then
        sleep 1
    else
        status=$?
        if [ "$status" -ne 1 ]; then
            echo "Failed to check BYOND and WebView2 processes; refusing to launch BYOND" >&2
            exit 1
        fi
        clients_stopped=true
        break
    fi
done
if [ "$clients_stopped" != true ]; then
    echo "BYOND or WebView2 processes did not stop; refusing to launch BYOND" >&2
    exit 1
fi

reset_flag="$XDG_RUNTIME_DIR/byond-reset-requested"
reset_requested=false
if [ -e "$reset_flag" ]; then
    reset_requested=true
    rm -f -- "$reset_flag"
fi

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

desktop_ready() (
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/selkies-session-bus"
    local marker="$XDG_RUNTIME_DIR/byond-plasma-ready" bus owner
    [ -r "$marker" ] &&
        { IFS= read -r bus && IFS= read -r owner; } <"$marker" &&
        [ -n "$bus" ] && [ -n "$owner" ] &&
        [ "$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
            org.freedesktop.DBus.GetId 2>/dev/null)" = "$bus" ] &&
        [ "$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
            org.freedesktop.DBus.GetNameOwner org.kde.plasmashell 2>/dev/null)" = "$owner" ] &&
        [ "$(timeout 2 qdbus6 org.kde.StatusNotifierWatcher /StatusNotifierWatcher \
            org.kde.StatusNotifierWatcher.IsStatusNotifierHostRegistered 2>/dev/null)" = true ] &&
        timeout 2 python3 /usr/local/bin/x11-tray-ready.py
)

desktop_is_ready=false
for attempt in {1..120}; do
    if desktop_ready; then
        desktop_is_ready=true
        break
    fi
    if [ "$attempt" -eq 1 ]; then
        echo "Waiting for Plasma panel and system tray before starting BYOND" >&2
    fi
    sleep 1
done
if [ "$desktop_is_ready" != true ]; then
    echo "Timed out waiting for Plasma panel and system tray; refusing to launch BYOND" >&2
    exit 1
fi

if ! bash -c 'status=0; timeout --kill-after=1s 30s "$@" 9>&- || status=$?; exit "$status"' \
    _ wine reg add 'HKCU\Software\Dantom\BYOND' /v userpath /t REG_SZ \
    /d 'C:\users\steamuser\Documents\BYOND\' /f >/dev/null; then
    echo "Failed to configure BYOND userpath" >&2
    exit 1
fi

cfg_dir="$WINEPREFIX/drive_c/users/steamuser/Documents/BYOND/cfg"
mkdir -p "$cfg_dir"
set_byond_option() {
    local file="$1" option="$2" value="$3" temporary
    temporary="$(mktemp "$file.XXXXXX")"
    if { [ ! -e "$file" ] || awk -v option="$option" '$1 != option { print }' "$file"; } >"$temporary" &&
        printf '%s %s\n' "$option" "$value" >>"$temporary" &&
        mv -f -- "$temporary" "$file"; then
        return 0
    fi
    rm -f -- "$temporary"
    echo "Failed to configure BYOND settings" >&2
    exit 1
}
set_byond_option "$cfg_dir/pager.txt" auto-login on
set_byond_option "$cfg_dir/seeker.txt" graphics-hwmode on
set_byond_option "$cfg_dir/seeker.txt" guest-login off

dimensions="$(xdpyinfo -display "$DISPLAY" | awk '$1 == "dimensions:" { print $2; exit }')"
if [[ ! "$dimensions" =~ ^([0-9]+)x([0-9]+)$ ]]; then
    echo "Could not determine display dimensions" >&2
    exit 1
fi
display_width=$((10#${BASH_REMATCH[1]}))
display_height=$((10#${BASH_REMATCH[2]}))
if ((display_width == 0 || display_height == 0)); then
    echo "Display dimensions must be positive" >&2
    exit 1
fi
one_third_width=$(((display_width + 1) / 3))
two_thirds_width=$(((display_width * 2 + 1) / 3))
one_third_height=$(((display_height + 1) / 3))
half_height=$(((display_height + 1) / 2))
layout_dir="$WINEPREFIX/drive_c/users/steamuser/Documents/BYOND/Skins/exadv1/spacestation13"
mkdir -p "$layout_dir"
cat >"$layout_dir/saved.txt" <<EOF
mainwindow.pos = "16,16"
mainwindow.size = "$((display_width - 64))x$((display_height - 128))"
mainwindow.is-minimized = "false"
mainwindow.is-maximized = "false"
mapwindow.pos = "0,0"
mapwindow.size = "${two_thirds_width}x$((display_height - 128))"
mapwindow.is-minimized = "false"
mapwindow.is-maximized = "false"
lobby_screen.pos = "0,0"
lobby_screen.size = "${two_thirds_width}x$((display_height - 128))"
lobby_screen.is-minimized = "false"
lobby_screen.is-maximized = "false"
mapwindow.map_lobby_selector.splitter = "50"
map_screen.pos = "0,0"
map_screen.size = "640x480"
map_screen.is-minimized = "false"
map_screen.is-maximized = "false"
map_screen.map.zoom = "0"
map_screen.map.letterbox = "true"
map_screen.map.zoom-mode = "distort"
info_and_buttons.pos = "0,0"
info_and_buttons.size = "${one_third_width}x$((display_height - 128))"
info_and_buttons.is-minimized = "false"
info_and_buttons.is-maximized = "false"
infobuttons.pos = "0,0"
infobuttons.size = "${one_third_width}x19"
infobuttons.is-minimized = "false"
infobuttons.is-maximized = "false"
infobuttons.options.is-checked = "false"
infobuttons.hotkeys.is-checked = "false"
infobuttons.emotes.is-checked = "false"
infobuttons.fullscreen-toggle.is-checked = "false"
infobuttons.reconnect.is-checked = "false"
infobuttons.chat.is-checked = "false"
infowindow.pos = "0,0"
infowindow.size = "${one_third_width}x$((display_height - 160))"
infowindow.is-minimized = "false"
infowindow.is-maximized = "false"
statwindow.pos = "0,0"
statwindow.size = "${one_third_width}x${one_third_height}"
statwindow.is-minimized = "false"
statwindow.is-maximized = "false"
outputwindow.pos = "0,0"
outputwindow.size = "${one_third_width}x${half_height}"
outputwindow.is-minimized = "false"
outputwindow.is-maximized = "false"
output_selector.pos = "0,0"
output_selector.size = "${one_third_width}x${half_height}"
output_selector.is-minimized = "false"
output_selector.is-maximized = "false"
output_legacy.pos = "0,0"
output_legacy.size = "318x254"
output_legacy.is-minimized = "false"
output_legacy.is-maximized = "false"
output_legacy_pane.pos = "0,0"
output_legacy_pane.size = "318x248"
output_legacy_pane.is-minimized = "false"
output_legacy_pane.is-maximized = "false"
input_buttons.pos = "0,0"
input_buttons.size = "318x6"
input_buttons.is-minimized = "false"
input_buttons.is-maximized = "false"
inputwindow.pos = "0,0"
inputwindow.size = "223x6"
inputwindow.is-minimized = "false"
inputwindow.is-maximized = "false"
inputwindow.input.command = ""
inputbuttons.pos = "0,0"
inputbuttons.size = "95x6"
inputbuttons.is-minimized = "false"
inputbuttons.is-maximized = "false"
inputbuttons.saybutton.is-checked = "false"
inputbuttons.whisperbutton.is-checked = "false"
inputbuttons.mebutton.is-checked = "false"
inputbuttons.oocbutton.is-checked = "false"
input_buttons.input_buttons_child.splitter = "70"
output_legacy.output_and_input_legacy.splitter = "97.500000"
output_selector.legacy_output_selector.splitter = "80"
outputwindow.output_selector_screen.splitter = "50"
infowindow.info_child.splitter = "40"
info_and_buttons.info_button_child.splitter = "2"
output_browser.pos = "0,0"
output_browser.size = "${one_third_width}x${half_height}"
output_browser.is-minimized = "false"
output_browser.is-maximized = "false"
popupwindow.pos = "281,0"
popupwindow.size = "120x120"
popupwindow.is-minimized = "false"
popupwindow.is-maximized = "false"
preferences_window.pos = "281,0"
preferences_window.size = "${two_thirds_width}x$((display_height - 128))"
preferences_window.is-minimized = "false"
preferences_window.is-maximized = "false"
preferences_window.character_preview_map.zoom = "0"
preferences_window.character_preview_map.letterbox = "true"
preferences_window.character_preview_map.zoom-mode = "normal"
mainwindow.split.splitter = "66.666667"
EOF

case "${BYOND_WEBVIEW2_GPU:-0}" in
    0 | "") ;;
    1)
        # Keep the lock in the wrapper, but not in Wine or its server.
        if ! bash -c 'status=0; timeout --kill-after=1s 30s "$@" 9>&- || status=$?; exit "$status"' \
            _ wine reg add 'HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments' \
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

pager="$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe"

wine "$pager" 9>&- &
pager_pid=$!
clear_pager_ready() {
    if [ -f "$pager_ready" ] && [ "$(cut -d' ' -f1 "$pager_ready")" = "$$" ]; then
        rm -f -- "$pager_ready"
    fi
}
trap clear_pager_ready EXIT
stop_pager() {
    local status="$1"
    trap '' TERM INT HUP
    kill -TERM "$pager_pid" 2>/dev/null || true
    wait "$pager_pid" 2>/dev/null || true
    exit "$status"
}
trap 'stop_pager 143' TERM
trap 'stop_pager 130' INT
trap 'stop_pager 129' HUP
sleep 3
for attempt in {1..15}; do
    if ! kill -0 "$pager_pid" 2>/dev/null; then
        break
    fi
    if pgrep -i -x -u "$EUID" byond.exe >/dev/null; then
        printf '%s %s\n' "$$" "$(awk '{print $22}' "/proc/$$/stat")" >"$pager_ready"
        break
    fi
    sleep 1
done
flock -u 9
exec 9>&-

if [ ! -f "$pager_ready" ] && kill -0 "$pager_pid" 2>/dev/null; then
    echo "Timed out waiting for the BYOND pager" >&2
    stop_pager 1
fi
if [ "$reset_requested" = true ]; then
    "${BYOND_GAME_CONTROL:-/usr/local/bin/byond-game.sh}" start || true
fi
status=0
wait "$pager_pid" || status=$?
exit "$status"
