#!/bin/sh
set -eu

case "${BYOND_DXVK:-0}" in
    0) exit 0 ;;
    1) ;;
    *)
        echo "Invalid BYOND_DXVK: expected 0 or 1" >&2
        exit 1
        ;;
esac

cache_dir="$(mktemp -d)"
trap 'rm -rf "$cache_dir"' EXIT
export W_CACHE="$cache_dir"

echo "Installing experimental DXVK 2.7.1"
if timeout --kill-after=10s 180s xvfb-run -a winetricks -q dxvk2071; then
    echo "Installed DXVK 2.7.1"
else
    status=$?
    echo "DXVK installation failed with exit code $status" >&2
    exit "$status"
fi
timeout --kill-after=10s 30s wineserver -k
timeout --kill-after=10s 30s wineserver --wait
