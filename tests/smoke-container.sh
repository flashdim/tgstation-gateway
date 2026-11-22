#!/bin/bash
set -euo pipefail

image="${1:?Pass the image to test}"
container="$(docker run -d --init --security-opt seccomp=examples/seccomp.json --shm-size=2g -p 127.0.0.1::8080 -e SELKIES_WAYLAND=false "$image")"
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

docker exec "$container" sh -ec '
    test "$(stat -c "%u:%g %a" /usr/share/tgstation-gateway)" = "0:0 755"
    test "$(stat -c "%u:%g %a" /usr/share/tgstation-gateway/wallpapers)" = "0:0 755"
    test -r /usr/share/tgstation-gateway/wallpapers/glory-to-nanotrasen.jpg
    for file in /etc/xdg/kdeglobals /etc/xdg/plasmarc /etc/xdg/kcminputrc \
        /usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/contents/layouts/org.kde.plasma.desktop-layout.js \
        /usr/share/doc/tgstation-gateway/wallpaper-attribution.md \
        /usr/share/tgstation-gateway/wallpapers/*; do
        test "$(stat -c "%u:%g %a" "$file")" = "0:0 644"
    done'

address="$(docker port "$container" 8080/tcp)"
for _ in {1..120}; do
    if curl --silent --fail --max-time 2 "http://$address/api/health" >/dev/null &&
        docker exec "$container" pgrep -f '/byond[.]exe([[:space:]]|$)' >/dev/null &&
        docker exec "$container" pgrep -x kwin_x11 >/dev/null &&
        docker exec "$container" pgrep -x plasmashell >/dev/null &&
        docker exec "$container" sh -c \
            '. "${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/container-env"; test "$SELKIES_WAYLAND" = false && xdpyinfo -display "$DISPLAY" >/dev/null'; then
        sleep 3
        if docker exec "$container" pgrep -f '/byond[.]exe([[:space:]]|$)' >/dev/null; then
            health_command="$(docker inspect -f '{{json .Config.Healthcheck.Test}}' "$container")"
            if [ "$health_command" != '["CMD","/usr/local/bin/healthcheck"]' ]; then
                echo "Player image has an unexpected health check: $health_command" >&2
                exit 1
            fi
            docker exec "$container" /usr/local/bin/healthcheck
            docker exec "$container" sh -ec '
                export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/selkies-session-bus"
                test "$(qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
                    '"'"'var p = panels()[0]; print([p.alignment,p.lengthMode,p.hiding,p.opacity,p.floating,p.height].join(",").toString());'"'"')" \
                    = "center,fit,dodgewindows,opaque,false,64"'
            docker exec "$container" s6-svc -d /etc/service/byond
            for _ in {1..20}; do
                if ! docker exec "$container" pgrep -f '/byond[.]exe([[:space:]]|$)' >/dev/null; then
                    break
                fi
                sleep 1
            done
            if docker exec "$container" pgrep -f '/byond[.]exe([[:space:]]|$)' >/dev/null; then
                echo "BYOND pager did not stop" >&2
                exit 1
            fi
            curl --silent --fail --max-time 2 "http://$address/api/health" >/dev/null
            if docker exec "$container" /usr/local/bin/healthcheck >/dev/null 2>&1; then
                echo "Health check passed without the BYOND pager" >&2
                exit 1
            fi
            echo "Plasma X11, Selkies and BYOND health checks passed"
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
