#!/bin/sh
set -eu

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
export W_CACHE="$workdir/winetricks-cache"
mkdir -p "$W_CACHE"

timeout --kill-after=10s 300s winetricks -q d3dx9
timeout --kill-after=10s 300s winetricks -q d3dx9_43
timeout --kill-after=10s 300s winetricks -q dxvk
timeout --kill-after=10s 30s wineserver --wait
