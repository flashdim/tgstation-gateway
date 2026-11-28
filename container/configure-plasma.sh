#!/bin/sh
set -eu

script="$(cat /usr/local/share/plasma-layout.js)"
attempt=0
while :; do
    bus="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.GetId 2>/dev/null || true)"
    owner="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.GetNameOwner org.kde.plasmashell 2>/dev/null || true)"
    result="$(timeout 2 qdbus6 org.kde.plasmashell /PlasmaShell \
        org.kde.PlasmaShell.evaluateScript "$script" 2>/dev/null || true)"
    current_bus="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.GetId 2>/dev/null || true)"
    current_owner="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.GetNameOwner org.kde.plasmashell 2>/dev/null || true)"
    if [ -n "$bus" ] && [ -n "$owner" ] && [ "$result" = configured ] &&
        [ "$bus" = "$current_bus" ] && [ "$owner" = "$current_owner" ]; then
        file="$(mktemp "$XDG_RUNTIME_DIR/byond-plasma-ready.XXXXXX")"
        trap 'rm -f -- "$file"' EXIT
        printf '%s\n%s\n' "$bus" "$owner" >"$file"
        mv -f -- "$file" "$XDG_RUNTIME_DIR/byond-plasma-ready"
        attempt=0
        while :; do
            sleep 1
            current_bus="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
                org.freedesktop.DBus.GetId 2>/dev/null || true)"
            current_owner="$(timeout 2 qdbus6 org.freedesktop.DBus /org/freedesktop/DBus \
                org.freedesktop.DBus.GetNameOwner org.kde.plasmashell 2>/dev/null || true)"
            [ "$bus" = "$current_bus" ] && [ "$owner" = "$current_owner" ] || break
        done
        continue
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "Still waiting for the Plasma panel to load" >&2
        attempt=0
    fi
    sleep 1
done
