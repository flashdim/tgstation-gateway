#!/bin/sh
set -eu

. "$(dirname "$0")/wine-proton.env"
directory="$1"
archive="$directory/wine-proton.tar.xz"
mkdir -p "$directory"
if [ ! -f "$archive" ]; then
    temporary="$(mktemp "$directory/wine-proton.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    echo "Downloading Proton Wine $WINE_PROTON_VERSION"
    curl -fsSL --retry 3 \
        "https://github.com/Kron4ek/Wine-Builds/releases/download/proton-${WINE_PROTON_VERSION}/wine-proton-${WINE_PROTON_VERSION}-amd64.tar.xz" \
        -o "$temporary"
    echo "$WINE_PROTON_SHA256  $temporary" | sha256sum -c -
    mv "$temporary" "$archive"
else
    echo "Verifying cached Proton Wine $WINE_PROTON_VERSION"
    echo "$WINE_PROTON_SHA256  $archive" | sha256sum -c -
fi
