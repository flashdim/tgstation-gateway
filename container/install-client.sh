#!/bin/sh
set -eu

for installer in /installers/byond.exe /installers/webview2-x64.exe; do
    if [ ! -r "$installer" ]; then
        echo "Missing or unreadable installer: $installer" >&2
        exit 1
    fi
done

export WINEDEBUG=-all
wineboot --init
wineserver --wait
winetricks -q vcrun2022 dxtrans dxvk2071
wine /installers/webview2-x64.exe /silent /install
wineserver -k
wineserver --wait
wine /installers/byond.exe /S
wineserver -k
wineserver --wait

if [ ! -f "$WINEPREFIX/drive_c/Program Files (x86)/BYOND/bin/byond.exe" ]; then
    echo "BYOND installation did not produce the expected executable" >&2
    exit 1
fi

if ! find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
    -name msedgewebview2.exe -print -quit | grep -q .; then
    echo "WebView2 installation did not produce the expected runtime" >&2
    exit 1
fi
