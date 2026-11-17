#!/bin/sh
set -eu

wine_path="$(command -v wine || true)"
if [ "$wine_path" != /opt/wine-proton/bin/wine ]; then
    echo "Expected wine at /opt/wine-proton/bin/wine; found ${wine_path:-nothing}" >&2
    exit 1
fi
case "${WINE_PROTON_VERSION:-10.0-4}" in
    10.0-4) loaders="/opt/wine-proton/bin/wine-preloader" ;;
    11.0-2)
        loaders="/opt/wine-proton/lib/wine/i386-unix/wine-preloader /opt/wine-proton/lib/wine/x86_64-unix/wine-preloader /opt/wine-proton/lib/wine/i386-unix/wine /opt/wine-proton/lib/wine/x86_64-unix/wine"
        ;;
    *)
        echo "Unsupported WINE_PROTON_VERSION" >&2
        exit 1
        ;;
esac
for loader in $loaders; do
    if [ ! -x "$loader" ]; then
        echo "Missing or non-executable $loader" >&2
        exit 1
    fi
done
for library in libfreetype.so.6 libfontconfig.so.1 libvulkan.so.1; do
    path="/usr/lib/i386-linux-gnu/$library"
    if [ ! -r "$path" ]; then
        echo "Missing or unreadable $path" >&2
        exit 1
    fi
done
