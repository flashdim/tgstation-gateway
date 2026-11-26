#!/bin/sh
set -eu

deployment="${GATEWAY_DEPLOYMENT_ID:-tgportals}"
count="${GATEWAY_SLOT_COUNT:-4}"
network="${GATEWAY_TRAEFIK_NETWORK:-public}"
image="${GATEWAY_IMAGE:-ghcr.io/flashdim/tgstation-gateway:latest}"
server="${BYOND_SERVER:?BYOND_SERVER is required}"
wayland="${SELKIES_WAYLAND:-true}"

if ! printf '%s' "$deployment" | grep -Eq '^[a-z0-9][a-z0-9_-]{0,47}$'; then
    echo "GATEWAY_DEPLOYMENT_ID must be 1-48 lowercase letters, digits, _ or -" >&2
    exit 1
fi
if ! printf '%s' "$count" | grep -Eq '^[1-9][0-9]?$'; then
    echo "GATEWAY_SLOT_COUNT must be between 1 and 99" >&2
    exit 1
fi
if ! printf '%s' "$server" | grep -Eq '^([a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):[0-9]{1,5}$'; then
    echo "BYOND_SERVER must specify the operator's host and port" >&2
    exit 1
fi
port="${server##*:}"
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
    echo "BYOND_SERVER port must be between 1 and 65535" >&2
    exit 1
fi
case "$wayland" in
    true | false) ;;
    *)
        echo "SELKIES_WAYLAND must be true or false" >&2
        exit 1
        ;;
esac

exec 9>/run/gateway-lock/manager.lock
if ! flock -n 9; then
    echo "Another manager already owns deployment $deployment" >&2
    exit 1
fi
docker info >/dev/null
docker network inspect "$network" >/dev/null
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker pull "$image"
fi
image_id="$(docker image inspect --format '{{.Id}}' "$image")"
profile_hash="$(sha256sum /opt/gateway/seccomp.json | cut -d ' ' -f 1)"
settings="$(printf '%s\n' v1 "$image_id" "$server" "$network" "$wayland" "$profile_hash" | sha256sum | cut -d ' ' -f 1)"

owner_label="io.tgstation-gateway.deployment"
role_label="io.tgstation-gateway.role"
slot_label="io.tgstation-gateway.slot"

ensure_volume() {
    volume="$1"
    if docker volume inspect "$volume" >/dev/null 2>&1; then
        owner="$(docker volume inspect --format '{{index .Labels "io.tgstation-gateway.deployment"}}' "$volume")"
        volume_slot="$(docker volume inspect --format '{{index .Labels "io.tgstation-gateway.slot"}}' "$volume")"
        volume_role="$(docker volume inspect --format '{{index .Labels "io.tgstation-gateway.role"}}' "$volume")"
        if [ "$owner" != "$deployment" ] || [ "$volume_slot" != "$slot" ] || [ "$volume_role" != "$2" ]; then
            echo "Refusing to use unowned volume $volume" >&2
            exit 1
        fi
    else
        docker volume create --label "$owner_label=$deployment" --label "$slot_label=$slot" \
            --label "$role_label=$2" "$volume" >/dev/null
    fi
}

reconcile() {
    docker info >/dev/null
    existing="$(docker container ls -a --filter "label=io.tgstation-gateway.project=tgstation-gateway" \
        --filter "label=$owner_label=$deployment" \
        --filter "label=$role_label=player" --format '{{.Names}}')"
    for name in $existing; do
        case "$name" in
            "$deployment"-player[0-9][0-9])
                number="${name#"$deployment"-player}"
                case "$number" in
                    0[1-9] | [1-9][0-9]) ;;
                    *) continue ;;
                esac
                slot="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.slot"}}' "$name")"
                if [ "$slot" != "$number" ]; then
                    echo "Refusing to modify $name with mismatched ownership labels" >&2
                    exit 1
                fi
                numeric="${number#0}"
                if [ "$numeric" -gt "$count" ]; then
                    echo "Removing extra player $name; retaining its volumes"
                    docker rm -f "$name" >/dev/null
                fi
                ;;
        esac
    done
    number=1
    while [ "$number" -le "$count" ]; do
        slot="$(printf '%02d' "$number")"
        name="$deployment-player$slot"
        id="$(docker container ls -a --no-trunc --filter "name=^/$name\$" --format '{{.ID}}')"
        if [ -n "$id" ]; then
            project="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.project"}}' "$id")"
            owner="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.deployment"}}' "$id")"
            role="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.role"}}' "$id")"
            owned_slot="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.slot"}}' "$id")"
            if [ "$project" != tgstation-gateway ] || [ "$owner" != "$deployment" ] || [ "$role" != player ] || [ "$owned_slot" != "$slot" ]; then
                echo "Refusing to modify unowned container $name" >&2
                exit 1
            fi
            old_settings="$(docker inspect --format '{{index .Config.Labels "io.tgstation-gateway.settings"}}' "$id")"
            if [ "$old_settings" != "$settings" ]; then
                echo "Recreating player $name with updated settings"
                docker rm -f "$id" >/dev/null
                id=""
            else
                running="$(docker inspect --format '{{.State.Running}}' "$id")"
                if [ "$running" != true ]; then
                    docker start "$id" >/dev/null
                fi
            fi
        fi
        if [ -z "$id" ]; then
            wine="$deployment-player$slot-wine"
            data="$deployment-player$slot-data"
            ensure_volume "$wine" wine
            ensure_volume "$data" data
            echo "Starting player $name"
            docker run -d --name "$name" --platform linux/amd64 --init \
                --restart unless-stopped --network "$network" \
                --memory 4g --cpus 2 --pids-limit 512 --shm-size 2g \
                --security-opt seccomp=/opt/gateway/seccomp.json \
                --label "io.tgstation-gateway.project=tgstation-gateway" \
                --label "$owner_label=$deployment" --label "$role_label=player" \
                --label "$slot_label=$slot" \
                --label "io.tgstation-gateway.account=LGplayer$slot" \
                --label "io.tgstation-gateway.settings=$settings" \
                -e "BYOND_SERVER=$server" -e "SELKIES_SUBFOLDER=/LGplayer$slot/" \
                -e "SELKIES_MODE=websockets" -e "SELKIES_WAYLAND=$wayland" \
                -e SELKIES_GAMEPAD_ENABLED=false -e SELKIES_MICROPHONE_ENABLED=false \
                -e SELKIES_WEBCAM_ENABLED=false -e SELKIES_FILE_TRANSFERS=none \
                -e SELKIES_PRINTING_ENABLED=false \
                -v "$wine:/home/ubuntu/.wine" -v "$data:/home/ubuntu/.local/share" \
                "$image_id" >/dev/null
        fi
        number=$((number + 1))
    done
}

while :; do
    reconcile
    sleep 10
done
