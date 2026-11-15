#!/bin/sh
set -eu

if ! pgrep -f '[b]yond.exe' >/dev/null; then
    echo "BYOND pager is not running" >&2
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
