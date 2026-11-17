#!/bin/sh
set -eu

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
export W_CACHE="$workdir/winetricks-cache"
mkdir -p "$W_CACHE"

directx="$WINEPREFIX/drive_c/Program Files (x86)/BYOND/directx"
test -f "$directx/DXSETUP.exe" && test -f "$directx/Jun2010_d3dx9_43_x86.cab" || {
    echo "BYOND archive is missing the bundled DirectX setup or D3DX9 CAB" >&2
    exit 1
}

(cd "$directx" && timeout --kill-after=10s 300s wine DXSETUP.exe /silent)
cabextract -q -L -F d3dx9_43.dll -d "$workdir" "$directx/Jun2010_d3dx9_43_x86.cab"
cmp "$workdir/d3dx9_43.dll" "$WINEPREFIX/drive_c/windows/syswow64/d3dx9_43.dll" || {
    echo "Bundled DirectX setup did not install the expected D3DX9 library" >&2
    exit 1
}
wine reg add 'HKCU\Software\Wine\DllOverrides' /v '*d3dx9_43' /t REG_SZ /d native /f

timeout --kill-after=10s 300s winetricks -q dxvk
timeout --kill-after=10s 30s wineserver --wait
