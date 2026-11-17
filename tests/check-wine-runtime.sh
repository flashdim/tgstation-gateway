#!/bin/sh
set -eu

wine_path="$(command -v wine || true)"
if [ "$wine_path" != /opt/wine-staging/bin/wine ]; then
    echo "Expected wine at /opt/wine-staging/bin/wine; found ${wine_path:-nothing}" >&2
    exit 1
fi
if [ "$(dpkg-query -W -f='${Version}' winehq-staging)" != "$WINE_PACKAGE_VERSION" ]; then
    echo "Installed winehq-staging does not match WINE_PACKAGE_VERSION" >&2
    exit 1
fi
if [ "$(cat "$WINEPREFIX/.gateway-wine-package-version")" != "$WINE_PACKAGE_VERSION" ]; then
    echo "Wine prefix does not match WINE_PACKAGE_VERSION" >&2
    exit 1
fi
test -x /opt/wine-staging/bin/wineserver || {
    echo "Missing or non-executable /opt/wine-staging/bin/wineserver" >&2
    exit 1
}
for architecture in i386 x86_64; do
    directory=""
    for libdir in lib lib64; do
        candidate="/opt/wine-staging/$libdir/wine/$architecture-unix"
        if [ -d "$candidate" ]; then
            candidate="$(readlink -f "$candidate")"
            test -z "$directory" || test "$directory" = "$candidate"
            directory="$candidate"
        fi
    done
    find /opt/wine-staging/lib /opt/wine-staging/lib64 \
        -path "*/$architecture-windows/ntdll.dll" -type f -print 2>/dev/null | grep -q . || {
        echo "Missing $architecture Windows modules" >&2
        exit 1
    }
    if [ -z "$directory" ]; then
        test "$architecture" = i386 || {
            echo "Missing $architecture Unix modules" >&2
            exit 1
        }
        for module in wow64.dll wow64cpu.dll; do
            find /opt/wine-staging/lib /opt/wine-staging/lib64 \
                -path "*/x86_64-windows/$module" -type f -print 2>/dev/null | grep -q . || {
                echo "Missing new WoW64 component $module" >&2
                exit 1
            }
        done
    else
        for loader in wine wine-preloader; do
            if [ ! -x "$directory/$loader" ]; then
                echo "Missing or non-executable $directory/$loader" >&2
                exit 1
            fi
        done
    fi
    for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
        libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1; do
        path="/usr/lib/$architecture-linux-gnu/$library"
        if [ ! -r "$path" ]; then
            echo "Missing or unreadable $path" >&2
            exit 1
        fi
    done
    path="/usr/lib/$architecture-linux-gnu/libvulkan_lvp.so"
    if [ ! -r "$path" ]; then
        echo "Missing Mesa Vulkan driver $path" >&2
        exit 1
    fi
    if [ "$architecture" = i386 ]; then
        icd="i686"
    else
        icd="x86_64"
    fi
    path="/usr/share/vulkan/icd.d/lvp_icd.$icd.json"
    if [ ! -r "$path" ]; then
        echo "Missing Mesa Vulkan ICD $path" >&2
        exit 1
    fi
done
