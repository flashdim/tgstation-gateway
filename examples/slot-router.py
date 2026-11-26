#!/usr/bin/env python3
"""Generate fixed slots with an unauthenticated HTTP routing service."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fixed_slots", ROOT / "examples/fixed-slots.py"
)
fixed_slots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixed_slots)
ConfigError = fixed_slots.ConfigError

ROUTER_IMAGE = "caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0"


def caddyfile(slots):
    routes = "\n".join(
        f"""    handle {slot.path}* {{
        reverse_proxy player{slot.number:02}:8080 {{
            import backend_headers
        }}
    }}"""
        for slot in slots
    )
    return f"""(backend_headers) {{
    header_up -Cookie
    header_up -Authorization
    header_up -Cf-Access-*
}}

http://:8080 {{
    bind {{$ROUTER_BIND_IP}}
{routes}
    handle {{
        reverse_proxy landing:8000 {{
            import backend_headers
        }}
    }}
}}
"""


def compose_config(env):
    env = dict(env)
    host = env.get("GATEWAY_PLAY_HOST", "").strip()
    if not host:
        raise ConfigError("GATEWAY_PLAY_HOST is required")
    fixed_slots.SessionConfig.from_env({"GATEWAY_PLAY_HOST": host})
    if ":" in host:
        raise ConfigError("GATEWAY_PLAY_HOST must not include a port")
    if env.get("GATEWAY_PLAY_SCHEME", "https").strip().lower() not in ("", "https"):
        raise ConfigError("Traefik routing requires GATEWAY_PLAY_SCHEME=https")
    env["GATEWAY_PLAY_SCHEME"] = "https"
    network = env.get("GATEWAY_TRAEFIK_NETWORK", "").strip()
    entrypoint = env.get("GATEWAY_TRAEFIK_ENTRYPOINT", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", network):
        raise ConfigError(
            "GATEWAY_TRAEFIK_NETWORK must name the existing Docker network"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", entrypoint):
        raise ConfigError("GATEWAY_TRAEFIK_ENTRYPOINT must name the HTTPS entrypoint")
    if "GATEWAY_SLOT_PATH" not in env:
        env["GATEWAY_SLOT_PATH"] = "/{account}/"
    env["GATEWAY_FIXED_LANDING"] = "1"
    env["GATEWAY_PORT"] = "8080"
    env["GATEWAY_LANDING_PORT"] = "8000"
    if env.get("SELKIES_MODE", "websockets") != "websockets":
        raise ConfigError("The slot router supports only SELKIES_MODE=websockets")
    config = fixed_slots.SessionConfig.from_env(env)
    if any(
        slot.path == "/" or slot.path.lower().startswith("/assets/")
        for slot in config.slots
    ):
        raise ConfigError("Slot paths cannot overlap the landing page or /assets/")
    if len({slot.path.lower() for slot in config.slots}) != len(config.slots):
        raise ConfigError("Slot paths must be unique")
    result = fixed_slots.compose_config(env)
    for service in result["services"].values():
        service.pop("ports", None)
    name = result["name"]
    alias = f"{name}-front"
    result["networks"]["traefik"] = {"external": True, "name": network}
    result["configs"] = {"caddyfile": {"content": caddyfile(config.slots)}}
    result["services"]["router"] = {
        "image": ROUTER_IMAGE,
        "restart": "unless-stopped",
        "command": [
            "sh",
            "-ec",
            'ROUTER_BIND_IP="$(getent ahostsv4 "$ROUTER_ALIAS" | awk \'NR == 1 {print $1}\')"'
            '; if [ -z "$ROUTER_BIND_IP" ]; then '
            'echo "Cannot resolve the Traefik-facing router address" >&2; exit 1; fi; '
            "export ROUTER_BIND_IP; "
            "exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile",
        ],
        "environment": {"ROUTER_ALIAS": alias},
        "networks": {
            "traefik": {"aliases": [alias]},
            "landing": None,
            **{f"slot_{slot.number:02}": None for slot in config.slots},
        },
        "configs": [{"source": "caddyfile", "target": "/etc/caddy/Caddyfile"}],
        "labels": {
            "traefik.enable": "true",
            "traefik.docker.network": network,
            f"traefik.http.routers.{name}.rule": f"Host(`{host}`)",
            f"traefik.http.routers.{name}.entrypoints": entrypoint,
            f"traefik.http.routers.{name}.tls": "true",
            f"traefik.http.routers.{name}.service": name,
            f"traefik.http.services.{name}.loadbalancer.server.port": "8080",
        },
    }
    return result


def main():
    try:
        result = compose_config(os.environ)
    except (ConfigError, subprocess.CalledProcessError, ValueError, OSError) as error:
        print(f"Cannot generate slot router: {error}", file=sys.stderr)
        return 2
    print(json.dumps(fixed_slots.escape_compose(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
