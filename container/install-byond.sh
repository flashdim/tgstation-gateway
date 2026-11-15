#!/bin/sh
set -eu

version="${BYOND_VERSION:?BYOND_VERSION is required}"
major="${version%%.*}"
minor="${version#*.}"
case "$version" in
    *.*) ;;
    *) echo "Invalid BYOND_VERSION: expected major.minor" >&2; exit 1 ;;
esac
case "$major" in
    ''|*[!0-9]*) echo "Invalid BYOND_VERSION: expected numeric major.minor" >&2; exit 1 ;;
esac
case "$minor" in
    ''|*[!0-9]*) echo "Invalid BYOND_VERSION: expected numeric major.minor" >&2; exit 1 ;;
esac

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
archive="$workdir/byond.zip"
curl -fsSL --retry 3 \
    "https://byond-builds.dm-lang.org/$major/${version}_byond.zip" \
    -o "$archive"

if [ -n "${BYOND_SHA256:-}" ]; then
    printf '%s  %s\n' "$BYOND_SHA256" "$archive" | sha256sum -c -
fi

unzip -qt "$archive"
unzip -q "$archive" -d "$workdir"
if [ ! -f "$workdir/byond/bin/byond.exe" ]; then
    echo "BYOND archive is missing byond/bin/byond.exe" >&2
    exit 1
fi
destination="$WINEPREFIX/drive_c/Program Files (x86)/BYOND"
mkdir -p "$destination"
cp -a "$workdir/byond/." "$destination/"
