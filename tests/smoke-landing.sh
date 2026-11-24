#!/usr/bin/env bash
set -euo pipefail

image="${1:?usage: smoke-landing.sh IMAGE}"
workdir="./.smoke-landing-$$"
mkdir -m 700 "$workdir"
container=""
cleanup() {
    if [ -n "$container" ]; then
        docker rm -f "$container" >/dev/null
    fi
    rm -rf "$workdir"
}
trap cleanup EXIT

if docker run --rm -e GATEWAY_PLAY_HOST='bad host' "$image" >/dev/null 2>&1; then
    echo "Landing image accepted an invalid play host" >&2
    exit 1
fi

container="$(docker run -d --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    -p 127.0.0.1::8000 \
    -e GATEWAY_PLAY_HOST=play.example.test \
    -e GATEWAY_SLOT_COUNT=2 \
    -e GATEWAY_SLOT_PATH='/{account}/' \
    -e GATEWAY_ACTIVE_SLOTS=LGplayer02 "$image")"
port="$(docker port "$container" 8000/tcp | head -n 1 | sed 's/.*://')"
base="http://127.0.0.1:$port"

for _ in $(seq 1 30); do
    if curl -fsS "$base/" -o "$workdir/index.html" 2>/dev/null; then
        break
    fi
    sleep 1
done

grep -q 'src="slots.js"' "$workdir/index.html"
curl -fsS "$base/status.json" -o "$workdir/status.json"
grep -q '"online": null' "$workdir/status.json"
curl -fsS "$base/status.js" -o "$workdir/status.js"
grep -q 'status.json' "$workdir/status.js"
grep -q 'server-status' "$workdir/index.html"
curl -fsS "$base/slots.js" -o "$workdir/slots.js"
grep -q '"url": "https://play.example.test/LGplayer01/"' "$workdir/slots.js"
grep -q '"url": "https://play.example.test/LGplayer02/"' "$workdir/slots.js"
grep -q '"active": true' "$workdir/slots.js"
grep -q '"active": false' "$workdir/slots.js"
curl -fsS "$base/page.js" -o "$workdir/page.js"
grep -q GATEWAY_SLOTS "$workdir/page.js"
curl -fsS "$base/wizard.js" -o "$workdir/wizard.js"
grep -q 'setTimeout' "$workdir/wizard.js"
curl -fsS "$base/narsie.js" -o /dev/null
grep -q '\*honk\*' "$workdir/index.html"
grep -q '\*hiss\*' "$workdir/index.html"
grep -q 'Guys? Where are you?' "$workdir/index.html"
curl -fsS "$base/style.css" -o /dev/null
curl -fsS "$base/assets/banners/alert.svg" -o "$workdir/station-alert.svg"
grep -q 'LazorGator Party 13' "$workdir/station-alert.svg"
grep -q 'laser-glow' "$workdir/station-alert.svg"
for asset in clown.webp alien.png operative.png wizard.png narsie.gif singularity.gif; do
    curl -fsS "$base/assets/sprites/$asset" -o "$workdir/$asset"
done
file "$workdir/alien.png" | grep -q 'PNG image data'
file "$workdir/operative.png" | grep -q 'PNG image data'
file "$workdir/wizard.png" | grep -q 'PNG image data'
file "$workdir/narsie.gif" | grep -q 'GIF image data'
file "$workdir/singularity.gif" | grep -q 'GIF image data'
curl -fsS "$base/assets/layer1.webp" -o "$workdir/layer1.webp"
file "$workdir/layer1.webp" | grep -q 'Web/P image'
curl -fsS "$base/assets/ATTRIBUTION.md" | grep -q "CC BY-SA 3.0"
if curl -fsS "$base/Dockerfile" -o /dev/null 2>/dev/null ||
    curl -fsS "$base/server.py" -o /dev/null 2>/dev/null ||
    curl -fsS "$base/assets/wallpapers/" -o /dev/null 2>/dev/null; then
    echo "Landing image serves files outside the page" >&2
    exit 1
fi
test "$(docker exec "$container" id -u)" = 65534

for _ in $(seq 1 30); do
    status="$(docker inspect --format '{{.State.Health.Status}}' "$container")"
    [ "$status" = healthy ] && break
    sleep 2
done
test "$status" = healthy
echo "Landing image smoke test passed"
