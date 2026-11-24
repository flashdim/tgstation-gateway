#!/bin/bash
set -euo pipefail

image="${1:?Pass the player image to test}"
key_file="${2:?Pass the temporary BYOND key file}"
server="ss13.lazorgator.party"
port=1337
container=""

cleanup() {
    result=$?
    if [ -n "$container" ] &&
        ! docker rm -f "$container" >/dev/null; then
        echo "Failed to remove BYOND login test container" >&2
        result=1
    fi
    exit "$result"
}
trap cleanup EXIT

if [ ! -s "$key_file" ] ||
    [ "$(stat -c '%u:%g %a' "$key_file")" != "1000:1000 400" ]; then
    echo "BYOND key must be a non-empty UID-1000 mode-400 file" >&2
    exit 1
fi

server_players() {
    local response
    response="$(
        timeout 10 "$BYOND_WIRE_BIN" "$server" "$port" '?status&format=json' 2>/dev/null
    )" || return 1
    python3 -c '
import json
import sys

players = json.loads(sys.argv[1])["players"]
if type(players) is not int or players < 0:
    raise SystemExit("Invalid server player count")
print(players)
' "$response"
}

baseline="$(server_players)" || {
    echo "Could not query the configured BYOND test server" >&2
    exit 1
}

container="$(
    docker run -d --init --security-opt seccomp=examples/seccomp.json --shm-size=2g \
        --mount "type=bind,source=$key_file,target=/run/secrets/LGplayer01_key.txt,readonly" \
        -e BYOND_KEY_FILE=/run/secrets/LGplayer01_key.txt \
        -e BYOND_SERVER="$server:$port" \
        -e SELKIES_WAYLAND=false \
        "$image"
)"

ready=false
for _ in {1..60}; do
    state="$(docker inspect -f '{{.State.Status}}' "$container")"
    [ "$state" = running ] || {
        echo "Player container exited before becoming ready" >&2
        exit 1
    }
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
    if [ "$health" = healthy ] &&
        docker exec "$container" pgrep -f '/dreamseeker[.]exe([[:space:]]|$)' >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 5
done

[ "$ready" = true ] || {
    echo "Player container did not become ready with Dream Seeker running" >&2
    exit 1
}

for _ in {1..36}; do
    current="$(server_players)" || current="$baseline"
    if [ "$current" -gt "$baseline" ]; then
        echo "BYOND server player count increased after the credentialed client started"
        exit 0
    fi
    sleep 5
done

echo "BYOND server player count did not increase; login was not demonstrated" >&2
exit 1
