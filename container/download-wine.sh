#!/bin/sh
set -eu

. "$(dirname "$0")/wine-proton.env"
directory="$1"
archive="$directory/wine-proton.tar.gz"
mkdir -p "$directory"
if [ ! -f "$archive" ]; then
    temporary="$(mktemp "$directory/wine-proton.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    echo "Downloading GE-Proton $WINE_PROTON_VERSION"
    curl -fsSL --retry 3 \
        "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${WINE_PROTON_VERSION}/${WINE_PROTON_VERSION}.tar.gz" \
        -o "$temporary"
    echo "$WINE_PROTON_SHA512  $temporary" | sha512sum -c -
    mv "$temporary" "$archive"
else
    echo "Verifying cached GE-Proton $WINE_PROTON_VERSION"
    echo "$WINE_PROTON_SHA512  $archive" | sha512sum -c -
fi
