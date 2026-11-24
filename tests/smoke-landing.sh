#!/usr/bin/env bash
set -euo pipefail

image="${1:?usage: smoke-landing.sh IMAGE}"
workdir="./.smoke-landing-$$"
mkdir -m 700 "$workdir"
container=""
configured_container=""
fake=""
network=""
cleanup() {
    if [ -n "$container" ]; then
        docker rm -f "$container" >/dev/null
    fi
    if [ -n "$configured_container" ]; then
        docker rm -f "$configured_container" >/dev/null
    fi
    if [ -n "$fake" ]; then
        docker rm -f "$fake" >/dev/null
    fi
    if [ -n "$network" ]; then
        docker network rm "$network" >/dev/null
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
    -e GATEWAY_SLOT_PATH='/{account}/' "$image")"
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

network="gateway-landing-test-$$"
docker network create "$network" >/dev/null
fake="$(docker run -d --network "$network" --network-alias game \
    --entrypoint python3 "$image" -c '
import json, socketserver, time
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        request = self.request.recv(1024)
        if b"?status&format=json" not in request:
            return
        data = json.dumps({"map_name": "MetaStation", "players": 12,
                           "round_duration": 3661, "gamestate": 3,
                           "popcap": 100}).encode()
        frame = bytes.fromhex("0083") + (len(data) + 2).to_bytes(2, "big") + b"\x06" + data + b"\x00"
        for part in (frame[:2], frame[2:5], frame[5:]):
            self.request.sendall(part)
            time.sleep(.02)
class Server(socketserver.TCPServer):
    allow_reuse_address = True
Server(("0.0.0.0", 1337), Handler).serve_forever()
')"

configured_container="$(docker run -d --read-only --cap-drop ALL \
    --network "$network" \
    --security-opt no-new-privileges \
    -p 127.0.0.1::8000 \
    -e GATEWAY_PLAY_HOST=play.example.test \
    -e GATEWAY_SLOT_COUNT=2 \
    -e GATEWAY_SLOT_PATH='/{account}/' \
    -e GATEWAY_QUERY_HOST=game -e GATEWAY_QUERY_PORT=1337 "$image")"
configured_port="$(docker port "$configured_container" 8000/tcp | head -n 1 | sed 's/.*://')"
configured_base="http://127.0.0.1:$configured_port"

status=""
for _ in $(seq 1 25); do
    if status="$(curl -fsS --max-time 4 "$configured_base/status.json" 2>/dev/null)" &&
        echo "$status" | grep -q '"map": "MetaStation"'; then
        break
    fi
    sleep 1
done
echo "$status" | grep -q '"map": "MetaStation"'
echo "$status" | grep -q '"online": true'
echo "$status" | grep -q '"round_seconds": 3661'
echo "$status" | grep -q '"players": 12'
echo "$status" | grep -q '"popcap": 100'

docker stop "$fake" >/dev/null
for _ in $(seq 1 25); do
    status="$(curl -fsS "$configured_base/status.json")"
    echo "$status" | grep -q '"online": null' && break
    sleep 1
done
echo "$status" | grep -q '"online": null'

docker start "$fake" >/dev/null
for _ in $(seq 1 25); do
    status="$(curl -fsS "$configured_base/status.json")"
    echo "$status" | grep -q '"map": "MetaStation"' && break
    sleep 1
done
echo "$status" | grep -q '"online": true'

grep -q 'server-status' "$workdir/index.html"
curl -fsS "$base/slots.js" -o "$workdir/slots.js"
grep -q '"url": "https://play.example.test/LGplayer01/"' "$workdir/slots.js"
grep -q '"url": "https://play.example.test/LGplayer02/"' "$workdir/slots.js"
grep -q '"state": null' "$workdir/slots.js"
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
