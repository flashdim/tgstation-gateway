#!/bin/bash
set -euo pipefail

image="${1:?Pass the image to test}"
container="$(docker run -d --init --shm-size=2g -p 127.0.0.1::8080 "$image")"
cleanup() {
    result=$?
    if [ "$result" -ne 0 ]; then
        docker logs "$container" || true
    fi
    if ! docker rm -f "$container" >/dev/null; then
        echo "Failed to remove smoke-test container $container" >&2
        [ "$result" -ne 0 ] || exit 1
    fi
}
trap cleanup EXIT

address="$(docker port "$container" 8080/tcp)"
for _ in {1..120}; do
    if curl --silent --fail --max-time 2 "http://$address/api/health" >/dev/null &&
        docker exec "$container" pgrep -f '[b]yond.exe' >/dev/null; then
        sleep 3
        if docker exec "$container" pgrep -f '[b]yond.exe' >/dev/null; then
            echo "Selkies is responding and the BYOND pager is running"
            exit 0
        fi
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$container")" != "true" ]; then
        echo "Player container exited before it became ready" >&2
        exit 1
    fi
    sleep 2
done

echo "Player container did not become ready" >&2
exit 1
