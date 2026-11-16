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

archive="$workdir/dxvk.tar.gz"
curl -fsSL --retry 3 \
    https://github.com/doitsujin/dxvk/releases/download/v2.7.1/dxvk-2.7.1.tar.gz \
    -o "$archive"
echo "d85ce7c79f57ecd765aaa1b9e7007cb875e6fde9f6d331df799bce73d513ce87  $archive" | sha256sum -c -
tar -xzf "$archive" -C "$workdir"
for dll in d3d9 d3d10core d3d11 dxgi; do
    cp --remove-destination "$workdir/dxvk-2.7.1/x32/$dll.dll" "$WINEPREFIX/drive_c/windows/syswow64/$dll.dll"
    cp --remove-destination "$workdir/dxvk-2.7.1/x64/$dll.dll" "$WINEPREFIX/drive_c/windows/system32/$dll.dll"
    wine reg add 'HKCU\Software\Wine\DllOverrides' /v "*$dll" /t REG_SZ /d native /f
done
timeout --kill-after=10s 30s wineserver -k
timeout --kill-after=10s 30s wineserver --wait
