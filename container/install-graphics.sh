#!/bin/sh
set -eu

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

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

dxvk_version=3.1.1
dxvk_dir="dxvk-$dxvk_version"
archive="$workdir/$dxvk_dir.tar.gz"
curl -fsSL --retry 3 --max-time 120 \
    "https://github.com/doitsujin/dxvk/releases/download/v$dxvk_version/$dxvk_dir.tar.gz" \
    -o "$archive"
printf '%s  %s\n' 40565b4a724aadc4433fa4e010b4b23916d9b1f1baeee64e17186db94f54e608 "$archive" |
    sha256sum -c -
tar -xzf "$archive" -C "$workdir"
for dll in dxgi d3d8 d3d9 d3d10core d3d11; do
    cp "$workdir/$dxvk_dir/x32/$dll.dll" "$WINEPREFIX/drive_c/windows/syswow64/"
    cp "$workdir/$dxvk_dir/x64/$dll.dll" "$WINEPREFIX/drive_c/windows/system32/"
    wine reg add 'HKCU\Software\Wine\DllOverrides' /v "$dll" /t REG_SZ /d native /f
done
timeout --kill-after=10s 30s wineserver --wait
