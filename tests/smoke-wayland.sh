#!/bin/bash
set -euo pipefail

image="${1:?Pass the image to test}"
container="$(docker run -d --init --security-opt seccomp=examples/seccomp.json --shm-size=2g -p 127.0.0.1::8080 -e SELKIES_WAYLAND=true "$image")"
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

if [ "$(docker exec "$container" stat -c '%a' /tmp/.X11-unix)" != 1777 ]; then
    echo "X11 socket directory does not have mode 1777" >&2
    exit 1
fi

address="$(docker port "$container" 8080/tcp)"
for _ in {1..120}; do
    if curl --silent --fail --max-time 2 "http://$address/api/health" >/dev/null &&
        docker exec "$container" pgrep -x labwc >/dev/null &&
        docker exec "$container" pgrep -f '[b]yond.exe' >/dev/null &&
        docker exec "$container" sh -c \
            '. "${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/container-env"; test "$SELKIES_WAYLAND" = true && xdpyinfo -display "$DISPLAY" >/dev/null'; then
        sleep 3
        if docker exec "$container" pgrep -x openbox >/dev/null; then
            echo "Openbox must not compete with the Wayland compositor" >&2
            exit 1
        fi
        if docker exec "$container" /usr/local/bin/healthcheck; then
            echo "Wayland compositor, XWayland and BYOND health checks passed"
            exit 0
        fi
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$container")" != "true" ]; then
        echo "Wayland comparison container exited before it became ready" >&2
        exit 1
    fi
    sleep 2
done

echo "Wayland comparison container did not become ready" >&2
exit 1
