#!/bin/sh
set -eu

wine_path="$(command -v wine || true)"
if [ "$wine_path" != /opt/ge-proton/files/bin/wine ]; then
    echo "Expected wine at /opt/ge-proton/files/bin/wine; found ${wine_path:-nothing}" >&2
    exit 1
fi
for package in wine wine32:i386 wine64; do
    if [ "$(dpkg-query -W -f='${Version}' "$package")" != "$WINE_PACKAGE_VERSION" ]; then
        echo "Installed $package does not match WINE_PACKAGE_VERSION" >&2
        exit 1
    fi
done
if [ "$GE_PROTON_VERSION" != GE-Proton10-34 ] ||
    [ "$(cat "$WINEPREFIX/.gateway-ge-proton-version")" != "$GE_PROTON_VERSION" ]; then
    echo "Wine prefix does not match GE_PROTON_VERSION" >&2
    exit 1
fi
if [ "$WINE" != /usr/local/bin/proton-wine ] ||
    [ -z "$STEAM_COMPAT_DATA_PATH" ] ||
    [ "$WINEPREFIX" != "$STEAM_COMPAT_DATA_PATH/pfx" ] ||
    [ "$UMU_ID" != umu-default ]; then
    echo "GE-Proton launch environment is incomplete" >&2
    exit 1
fi
for binary in /opt/ge-proton/proton /opt/ge-proton/files/bin/wine \
    /opt/ge-proton/files/bin/wine64 /opt/ge-proton/files/bin/wineserver; do
    if [ ! -x "$binary" ]; then
        echo "Missing or non-executable $binary" >&2
        exit 1
    fi
done
for architecture in i386 x86_64; do
    directory="/opt/ge-proton/files/lib/wine/$architecture-unix"
    if [ ! -d "$directory" ]; then
        echo "Missing $architecture Unix modules" >&2
        exit 1
    fi
    for module in ntdll.so win32u.so winex11.so winewayland.so \
        winealsa.so winepulse.so winevulkan.so; do
        if [ ! -r "$directory/$module" ]; then
            echo "Missing $directory/$module" >&2
            exit 1
        fi
    done
    for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
        libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1; do
        path="/usr/lib/$architecture-linux-gnu/$library"
        if [ ! -r "$path" ]; then
            echo "Missing or unreadable $path" >&2
            exit 1
        fi
    done
done
