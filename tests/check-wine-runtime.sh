#!/bin/sh
set -eu

wine_path="$(command -v wine || true)"
if [ "$wine_path" != /opt/wine-proton/bin/wine ]; then
    echo "Expected wine at /opt/wine-proton/bin/wine; found ${wine_path:-nothing}" >&2
    exit 1
fi
for package in wine wine32:i386 wine64; do
    if [ "$(dpkg-query -W -f='${Version}' "$package")" != "$WINE_PACKAGE_VERSION" ]; then
        echo "Installed $package does not match WINE_PACKAGE_VERSION" >&2
        exit 1
    fi
done
if [ "$WINE_PROTON_VERSION" != 11.0-2 ] ||
    [ "$(cat "$WINEPREFIX/.gateway-proton-version")" != "$WINE_PROTON_VERSION" ]; then
    echo "Wine prefix does not match WINE_PROTON_VERSION" >&2
    exit 1
fi
for binary in /opt/wine-proton/bin/wine /opt/wine-proton/bin/wineserver; do
    if [ ! -x "$binary" ]; then
        echo "Missing or non-executable $binary" >&2
        exit 1
    fi
done
for architecture in i386 x86_64; do
    directory="/opt/wine-proton/lib/wine/$architecture-unix"
    if [ ! -d "$directory" ]; then
        echo "Missing $architecture Unix modules" >&2
        exit 1
    fi
    if [ ! -x "$directory/wine-preloader" ]; then
        echo "Missing or non-executable $directory/wine-preloader" >&2
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
