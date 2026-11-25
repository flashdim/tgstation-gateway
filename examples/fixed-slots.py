#!/usr/bin/env python3
"""Generate a Compose configuration with one persistent player per account."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "landing"))
from sessions import ConfigError, SessionConfig  # noqa: E402


def compose_config(env):
    config = SessionConfig.from_env(env)
    server = env.get("BYOND_SERVER", "").removeprefix("byond://")
    match = re.fullmatch(r"(?:[a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):([0-9]{1,5})", server)
    if not match or not 1 <= int(match.group(1)) <= 65535:
        raise ConfigError("BYOND_SERVER must specify the operator's host and port")
    port_text = env.get("GATEWAY_PORT", "8080")
    if not re.fullmatch(r"[0-9]{1,5}", port_text):
        raise ConfigError("GATEWAY_PORT must be a valid TCP port")
    first_port = int(port_text)
    if first_port < 1 or first_port + len(config.slots) - 1 > 65535:
        raise ConfigError("Player ports exceed the TCP port range")
    secret_dir = env.get("GATEWAY_SECRET_DIRECTORY", "")
    if secret_dir and not os.path.isabs(secret_dir):
        raise ConfigError("GATEWAY_SECRET_DIRECTORY must be an absolute path")
    command = [
        "docker",
        "compose",
        "-f",
        str(ROOT / "examples/compose.yaml"),
    ]
    if env.get("GATEWAY_FIXED_GPU") == "1":
        command.extend(["-f", str(ROOT / "examples/compose.gpu.yaml")])
    command.extend(
        [
            "--profile",
            "landing",
            "config",
            "--format",
            "json",
        ]
    )
    base = json.loads(
        subprocess.run(
            command, env=env, check=True, capture_output=True, text=True
        ).stdout
    )
    player = base["services"]["player"]
    player["security_opt"] = [f"seccomp={ROOT / 'examples/seccomp.json'}"]
    player["restart"] = "unless-stopped"
    player["mem_limit"] = "4g"
    player["cpus"] = 2
    player["pids_limit"] = 512
    services = {}
    volumes = {}
    networks = {}
    for slot in config.slots:
        service = copy.deepcopy(player)
        network = f"slot_{slot.number:02}"
        networks[network] = {}
        service["networks"] = {network: None}
        service["ports"][0]["published"] = str(first_port + slot.number - 1)
        service["labels"] = {
            "io.tgstation-gateway.project": "tgstation-gateway",
            "io.tgstation-gateway.deployment": config.deployment_id,
            "io.tgstation-gateway.account": slot.account,
            "io.tgstation-gateway.role": "player",
            "io.tgstation-gateway.slot": f"{slot.number:02}",
        }
        account_hash = hashlib.sha256(slot.account.encode()).hexdigest()[:16]
        for suffix, target in (
            ("wine", "/home/ubuntu/.wine"),
            ("data", "/home/ubuntu/.local/share"),
        ):
            name = f"slot_{account_hash}_{suffix}"
            volumes[name] = {}
            service["volumes"].append(
                {"type": "volume", "source": name, "target": target}
            )
        if secret_dir:
            path = Path(secret_dir) / f"{slot.account}_key.txt"
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(fd)
                    valid = (
                        stat.S_ISREG(info.st_mode)
                        and info.st_size > 0
                        and info.st_nlink == 1
                        and (
                            (info.st_uid == 1000 and info.st_mode & stat.S_IRUSR)
                            or (
                                info.st_uid != 1000
                                and info.st_mode & stat.S_IRGRP
                                and info.st_mode & stat.S_IROTH
                            )
                        )
                    )
                finally:
                    os.close(fd)
            except OSError:
                valid = False
            if not valid:
                raise ConfigError(f"Missing or invalid key file for {slot.account}")
            service["volumes"].append(
                {
                    "type": "bind",
                    "source": str(path),
                    "target": "/run/secrets/byond_key.txt",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                }
            )
            service["environment"]["BYOND_KEY_FILE"] = "/run/secrets/byond_key.txt"
        services[f"player{slot.number:02}"] = service
    if env.get("GATEWAY_FIXED_LANDING") == "1":
        landing = base["services"]["landing"]
        landing.pop("profiles", None)
        landing["networks"] = {"landing": None}
        networks["landing"] = {}
        landing["restart"] = "unless-stopped"
        landing_port = int(landing["ports"][0]["published"])
        if first_port <= landing_port < first_port + len(config.slots):
            raise ConfigError("Landing and player ports overlap")
        services["landing"] = landing
    project_hash = hashlib.sha256(config.deployment_id.encode()).hexdigest()[:16]
    return {
        "name": f"tgstation-gateway-{project_hash}",
        "services": services,
        "volumes": volumes,
        "networks": networks,
    }


def escape_compose(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_compose(item) for key, item in value.items()}
    return value


def main():
    try:
        result = compose_config(dict(os.environ))
    except (ConfigError, subprocess.CalledProcessError, ValueError, OSError) as error:
        print(f"Cannot generate fixed slots: {error}", file=sys.stderr)
        return 2
    print(json.dumps(escape_compose(result), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
