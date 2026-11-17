#!/bin/sh
set -eu

. "$(dirname "$0")/ge-proton.env"
directory="$1"
archive="$directory/$GE_PROTON_VERSION.tar.gz"
mkdir -p "$directory"
if [ ! -f "$archive" ]; then
    temporary="$(mktemp "$directory/ge-proton.XXXXXX")"
    trap 'rm -f "$temporary"' EXIT
    echo "Downloading GE-Proton $GE_PROTON_VERSION"
    curl -fsSL --retry 3 \
        "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/$GE_PROTON_VERSION/$GE_PROTON_VERSION.tar.gz" \
        -o "$temporary"
    echo "$GE_PROTON_SHA512  $temporary" | sha512sum -c -
    mv "$temporary" "$archive"
else
    echo "Verifying cached GE-Proton $GE_PROTON_VERSION"
    echo "$GE_PROTON_SHA512  $archive" | sha512sum -c -
fi
