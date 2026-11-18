#!/bin/sh
set -eu

[ "${XDG_SESSION_TYPE:-}" = wayland ] || exit 0
if [ -z "${DISPLAY:-}" ] || [ -z "${XAUTHORITY:-}" ] || [ ! -r "$XAUTHORITY" ]; then
    echo "Plasma did not provide an authenticated XWayland display" >&2
    exit 1
fi

# Publish paths, not the X11 cookie, and never expose a partial update.
file="$(mktemp "$XDG_RUNTIME_DIR/byond-xwayland.XXXXXX")"
trap 'rm -f -- "$file"' EXIT
printf '%s\n' "$DISPLAY" "$XAUTHORITY" >"$file"
mv -f -- "$file" "$XDG_RUNTIME_DIR/byond-xwayland"
