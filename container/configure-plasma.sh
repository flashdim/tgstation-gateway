#!/bin/sh
set -eu

script="$(cat /usr/local/share/plasma-layout.js)"
attempt=0
while [ "$attempt" -lt 60 ]; do
    result="$(qdbus6 org.kde.plasmashell /PlasmaShell \
        org.kde.PlasmaShell.evaluateScript "$script" 2>/dev/null || true)"
    if [ "$result" = configured ]; then
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 1
done

echo "Timed out waiting for the Plasma panel to load" >&2
exit 1
