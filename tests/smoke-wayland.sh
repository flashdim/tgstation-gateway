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
        docker exec "$container" pgrep -x kwin_wayland >/dev/null &&
        docker exec "$container" pgrep -x plasmashell >/dev/null &&
        docker exec "$container" pgrep -f '/byond[.]exe([[:space:]]|$)' >/dev/null &&
        docker exec "$container" sh -c \
            'set -e
            runtime="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
            . "$runtime/container-env"
            test "$SELKIES_WAYLAND" = true
            { IFS= read -r DISPLAY && IFS= read -r XAUTHORITY; } < "$runtime/byond-xwayland"
            test -n "$DISPLAY"
            test -n "$XAUTHORITY"
            test -r "$XAUTHORITY"
            export DISPLAY XAUTHORITY
            timeout 2 xdpyinfo -display "$DISPLAY" >/dev/null'; then
        sleep 3
        if docker exec "$container" /usr/local/bin/healthcheck; then
            docker exec "$container" sh -ec '
                export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/selkies-session-bus"
                test "$(qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
                    '"'"'var p = panels()[0]; print([p.alignment,p.lengthMode,p.hiding,p.opacity,p.floating,p.height].join(",").toString());'"'"')" \
                    = "center,fit,dodgewindows,opaque,false,64"'
            docker exec "$container" sh -ec '
                export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/selkies-session-bus"
                result="$(qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
                    '"'"'var ds = desktops(); var ok = ds.length > 0; for (var i = 0; i < ds.length; i++) { var d = ds[i]; d.currentConfigGroup = ["Wallpaper", "org.kde.slideshow", "General"]; if (d.wallpaperPlugin !== "org.kde.slideshow" || Number(d.readConfig("FillMode", -1)) !== 6) ok = false; } print(ok ? "centered" : "wallpaper configuration mismatch");'"'"')"
                test "$result" = centered || { echo "$result" >&2; exit 1; }'
            echo "Plasma Wayland, XWayland and BYOND health checks passed"
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
