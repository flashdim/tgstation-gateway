#!/bin/sh
set -eu

wine_path="$(command -v wine || true)"
if [ "$wine_path" != /opt/wine-proton/bin/wine ]; then
    echo "Expected wine at /opt/wine-proton/bin/wine; found ${wine_path:-nothing}" >&2
    exit 1
fi
if [ ! -x /opt/wine-proton/bin/wine-preloader ]; then
    echo "Missing or non-executable /opt/wine-proton/bin/wine-preloader" >&2
    exit 1
fi
for library in libfreetype.so.6 libfontconfig.so.1 libvulkan.so.1; do
    path="/usr/lib/i386-linux-gnu/$library"
    if [ ! -r "$path" ]; then
        echo "Missing or unreadable $path" >&2
        exit 1
    fi
done
