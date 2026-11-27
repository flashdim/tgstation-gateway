#!/bin/sh
set -eu

if [ -n "${BYOND_SERVER:-}" ]; then
    process='(^|[\\/])dreamseeker[.]exe"?([[:space:]]|$)'
    client='Dream Seeker'
else
    process='(^|[\\/])byond[.]exe"?([[:space:]]|$)'
    client='BYOND pager'
fi

if ! pgrep -f "$process" >/dev/null; then
    echo "$client is not running" >&2
    exit 1
fi

prefix="${SELKIES_SUBFOLDER-${SUBFOLDER-}}"
prefix="${prefix#/}"
prefix="${prefix%/}"
prefix="${prefix:+/$prefix}"
port="${SELKIES_PORT:-8080}"

if ! curl -fs -k --max-time 2 -o /dev/null "https://localhost:$port$prefix/api/health" &&
    ! curl -fsS --max-time 2 -o /dev/null "http://localhost:$port$prefix/api/health"; then
    echo "Selkies health endpoint is unavailable" >&2
    exit 1
fi
