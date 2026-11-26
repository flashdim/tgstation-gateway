import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/fixed-slots.py"
spec = importlib.util.spec_from_file_location("fixed_slots", SCRIPT)
fixed_slots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixed_slots)


class FixedSlotsTest(unittest.TestCase):
    def environment(self, **overrides):
        return {
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            **(
                {"DOCKER_CONFIG": os.environ["DOCKER_CONFIG"]}
                if "DOCKER_CONFIG" in os.environ
                else {}
            ),
            "GATEWAY_SLOT_COUNT": "2",
            "GATEWAY_SLOT_PATH": "/{account}/",
            "GATEWAY_PORT": "18080",
            "BYOND_SERVER": "game.example.org:1337",
            **overrides,
        }

    def test_fixed_slots_have_isolated_volumes_and_loopback_ports(self):
        result = fixed_slots.compose_config(self.environment())
        self.assertEqual(set(result["services"]), {"player01", "player02"})
        first, second = result["services"].values()
        self.assertEqual(first["ports"][0]["published"], "18080")
        self.assertEqual(second["ports"][0]["published"], "18081")
        self.assertEqual(first["environment"]["SELKIES_SUBFOLDER"], "/LGplayer01/")
        self.assertEqual(second["environment"]["SELKIES_SUBFOLDER"], "/LGplayer02/")
        self.assertEqual(first["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(first["restart"], "unless-stopped")
        self.assertEqual(second["restart"], "unless-stopped")
        self.assertEqual(first["labels"]["io.tgstation-gateway.account"], "LGplayer01")
        self.assertEqual(second["labels"]["io.tgstation-gateway.account"], "LGplayer02")
        self.assertEqual(first["networks"], {"slot_01": None})
        self.assertEqual(second["networks"], {"slot_02": None})
        first_volumes = {m["source"] for m in first["volumes"] if m["type"] == "volume"}
        second_volumes = {
            m["source"] for m in second["volumes"] if m["type"] == "volume"
        }
        self.assertEqual(len(first_volumes), 2)
        self.assertTrue(first_volumes.isdisjoint(second_volumes))
        self.assertIn(
            f"seccomp={ROOT / 'examples/seccomp.json'}", first["security_opt"]
        )
        self.assertEqual(result, fixed_slots.compose_config(self.environment()))
        changed = fixed_slots.compose_config(
            self.environment(GATEWAY_ACCOUNT_PREFIX="Other")
        )
        self.assertNotEqual(set(result["volumes"]), set(changed["volumes"]))

    def test_each_slot_receives_only_its_own_password_path(self):
        with tempfile.TemporaryDirectory() as directory:
            for account in ("LGplayer01", "LGplayer02"):
                (Path(directory) / f"{account}_password.txt").write_text("private\n")
            with patch.object(
                Path,
                "lstat",
                return_value=SimpleNamespace(
                    st_mode=stat.S_IFREG | 0o400, st_size=8, st_nlink=1, st_uid=1000
                ),
            ):
                result = fixed_slots.compose_config(
                    self.environment(GATEWAY_SECRET_DIRECTORY=directory)
                )
            for index in (1, 2):
                service = result["services"][f"player{index:02}"]
                secret = next(
                    mount
                    for mount in service["volumes"]
                    if mount["target"] == "/run/secrets/byond_password.txt"
                )
                self.assertEqual(
                    secret["source"], f"{directory}/LGplayer{index:02}_password.txt"
                )
                self.assertTrue(secret["read_only"])
                self.assertFalse(secret["bind"]["create_host_path"])
                self.assertEqual(
                    service["environment"]["BYOND_ACCOUNT"], f"LGplayer{index:02}"
                )
                self.assertEqual(
                    service["environment"]["BYOND_PASSWORD_FILE"], secret["target"]
                )
            self.assertNotIn("private", json.dumps(result))

    def test_configured_capacity_and_resource_limits(self):
        for count in (1, 3, 99):
            with self.subTest(count=count):
                result = fixed_slots.compose_config(
                    self.environment(GATEWAY_SLOT_COUNT=str(count))
                )
                self.assertEqual(len(result["services"]), count)
                self.assertEqual(len(result["networks"]), count)
                self.assertEqual(len(result["volumes"]), count * 2)
                for number in range(1, count + 1):
                    service = result["services"][f"player{number:02}"]
                    self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
                    self.assertEqual(
                        service["ports"][0]["published"], str(18079 + number)
                    )
                    self.assertEqual(service["mem_limit"], "4g")
                    self.assertEqual(service["cpus"], 2)
                    self.assertEqual(service["pids_limit"], 512)
                    self.assertEqual(int(service["shm_size"]), 2 * 1024**3)

    def test_invalid_password_port_or_slot_configuration_fails(self):
        for overrides in (
            {"GATEWAY_PORT": "65535"},
            {"GATEWAY_PORT": "0"},
            {"GATEWAY_SLOT_PATH": "/"},
            {"GATEWAY_SLOT_PATH": "/{account}"},
            {"GATEWAY_SECRET_DIRECTORY": "relative"},
            {"BYOND_SERVER": ""},
            {"GATEWAY_FIXED_LANDING": "1", "GATEWAY_LANDING_PORT": "18081"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(fixed_slots.ConfigError):
                    fixed_slots.compose_config(self.environment(**overrides))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "LGplayer01_password.txt").write_text("key")
            (Path(directory) / "LGplayer02_password.txt").symlink_to(
                Path(directory) / "LGplayer01_password.txt"
            )
            with self.assertRaises(fixed_slots.ConfigError):
                fixed_slots.compose_config(
                    self.environment(GATEWAY_SECRET_DIRECTORY=directory)
                )
        with tempfile.TemporaryDirectory() as directory:
            for account in ("LGplayer01", "LGplayer02"):
                (Path(directory) / f"{account}_password.txt").write_text("key")
            owner_group_only = SimpleNamespace(
                st_mode=stat.S_IFREG | 0o604,
                st_size=3,
                st_nlink=1,
                st_uid=0,
            )
            with patch.object(Path, "lstat", return_value=owner_group_only):
                with self.assertRaises(fixed_slots.ConfigError):
                    fixed_slots.compose_config(
                        self.environment(GATEWAY_SECRET_DIRECTORY=directory)
                    )
            (Path(directory) / "LGplayer02_password.txt").unlink()
            os.link(
                Path(directory) / "LGplayer01_password.txt",
                Path(directory) / "LGplayer02_password.txt",
            )
            with self.assertRaises(fixed_slots.ConfigError):
                fixed_slots.compose_config(
                    self.environment(GATEWAY_SECRET_DIRECTORY=directory)
                )

    def test_compose_interpolation_is_escaped(self):
        value = {"environment": {"VALUE": "literal $VARIABLE"}}
        self.assertEqual(
            fixed_slots.escape_compose(value)["environment"]["VALUE"],
            "literal $$VARIABLE",
        )

    def test_gpu_override_applies_to_every_player(self):
        config = fixed_slots.compose_config(
            self.environment(GATEWAY_FIXED_GPU="1", DRI_RENDER_GID="123")
        )
        for service in config["services"].values():
            self.assertEqual(service["devices"][0]["source"], "/dev/dri")
            self.assertEqual(service["group_add"], ["123"])

    def test_generated_compose_config_is_valid(self):
        env = self.environment(GATEWAY_FIXED_LANDING="1")
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            path.write_text(result.stdout)
            resolved = subprocess.run(
                ["docker", "compose", "-f", str(path), "config", "--format", "json"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        services = json.loads(resolved.stdout)["services"]
        self.assertEqual(set(services), {"landing", "player01", "player02"})
        self.assertEqual(services["landing"]["environment"]["GATEWAY_SLOT_COUNT"], "2")


@unittest.skipUnless(
    os.environ.get("GATEWAY_DOCKER_TEST_IMAGE"),
    "Set GATEWAY_DOCKER_TEST_IMAGE to a local shell-capable fixture image",
)
class FixedSlotsDockerTest(FixedSlotsTest):
    def test_deployment_recovery_count_changes_and_explicit_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            other_path = Path(directory) / "other.json"
            deployment = uuid.uuid4().hex

            def generate(count, prefix="LGplayer", deployment_id=deployment):
                env = self.environment(
                    GATEWAY_SLOT_COUNT=str(count),
                    GATEWAY_ACCOUNT_PREFIX=prefix,
                    GATEWAY_DEPLOYMENT_ID=deployment_id,
                )
                config = fixed_slots.compose_config(env)
                for service in config["services"].values():
                    service["image"] = os.environ["GATEWAY_DOCKER_TEST_IMAGE"]
                    service["entrypoint"] = ["/bin/sh", "-c"]
                    service["command"] = ["exec tail -f /dev/null"]
                    service.pop("ports")
                    service["healthcheck"] = {
                        "test": ["CMD-SHELL", "test -e /tmp/healthy"],
                        "interval": "1s",
                        "timeout": "1s",
                        "retries": 1,
                    }
                return config

            def write(target, config):
                target.write_text(json.dumps(fixed_slots.escape_compose(config)))

            def run(target, *args):
                return subprocess.run(
                    ["docker", "compose", "-f", str(target), *args],
                    check=True,
                    capture_output=True,
                    text=True,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k != "COMPOSE_PROJECT_NAME"
                    },
                ).stdout.strip()

            def docker(*args):
                return subprocess.run(
                    ["docker", *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            config = generate(2)
            other = generate(1, deployment_id=uuid.uuid4().hex)
            write(path, config)
            write(other_path, other)
            project = config["name"]
            original_volumes = {name: f"{project}_{name}" for name in config["volumes"]}
            try:
                run(path, "up", "-d", "--remove-orphans")
                run(other_path, "up", "-d")
                other_id = run(other_path, "ps", "-q", "player01")
                run(
                    other_path,
                    "exec",
                    "-T",
                    "player01",
                    "sh",
                    "-c",
                    "echo unrelated > /home/ubuntu/.wine/marker",
                )
                for number in (1, 2):
                    run(
                        path,
                        "exec",
                        "-T",
                        f"player{number:02}",
                        "sh",
                        "-c",
                        f"echo wine{number} > /home/ubuntu/.wine/marker; "
                        f"echo data{number} > /home/ubuntu/.local/share/marker",
                    )

                first = run(path, "ps", "-q", "player01")
                second = run(path, "ps", "-q", "player02")
                for _ in range(50):
                    state = docker("inspect", "-f", "{{.State.Health.Status}}", first)
                    if state == "unhealthy":
                        break
                    time.sleep(0.2)
                self.assertEqual(state, "unhealthy")
                self.assertEqual(
                    docker("inspect", "-f", "{{.RestartCount}}", first), "0"
                )
                run(path, "stop", "player01")
                time.sleep(2)
                self.assertEqual(
                    docker("inspect", "-f", "{{.State.Running}}", first), "false"
                )
                run(path, "up", "-d", "--remove-orphans")
                self.assertEqual(run(path, "ps", "-q", "player01"), first)
                docker("rm", "-f", second)
                run(path, "up", "-d", "--remove-orphans")
                self.assertNotEqual(run(path, "ps", "-q", "player02"), second)
                run(path, "up", "-d", "--remove-orphans")
                self.assertEqual(len(run(path, "ps", "-aq").splitlines()), 2)

                broken = generate(3)
                broken["services"]["player03"]["image"] = (
                    "gateway-missing-fixture:" + uuid.uuid4().hex
                )
                write(path, broken)
                failed = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(path),
                        "up",
                        "-d",
                        "--pull",
                        "never",
                        "--no-deps",
                        "player03",
                    ],
                    capture_output=True,
                    text=True,
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k != "COMPOSE_PROJECT_NAME"
                    },
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(run(path, "ps", "-q", "player01"), first)
                self.assertEqual(len(run(path, "ps", "-aq").splitlines()), 2)

                write(path, generate(3))
                run(path, "up", "-d", "--remove-orphans")
                self.assertEqual(len(run(path, "ps", "-aq").splitlines()), 3)
                write(path, generate(1))
                run(path, "up", "-d", "--remove-orphans")
                self.assertEqual(len(run(path, "ps", "-aq").splitlines()), 1)
                for volume in original_volumes.values():
                    self.assertEqual(
                        docker("volume", "inspect", "-f", "{{.Name}}", volume), volume
                    )

                write(path, generate(2, prefix="Other"))
                run(path, "up", "-d", "--remove-orphans")
                run(
                    path,
                    "exec",
                    "-T",
                    "player02",
                    "sh",
                    "-c",
                    "test ! -e /home/ubuntu/.wine/marker && "
                    "test ! -e /home/ubuntu/.local/share/marker",
                )
                write(path, config)
                run(path, "up", "-d", "--remove-orphans")
                for number in (1, 2):
                    for target, expected in (
                        (".wine", "wine"),
                        (".local/share", "data"),
                    ):
                        self.assertEqual(
                            run(
                                path,
                                "exec",
                                "-T",
                                f"player{number:02}",
                                "cat",
                                f"/home/ubuntu/{target}/marker",
                            ),
                            f"{expected}{number}",
                        )
                self.assertEqual(run(other_path, "ps", "-q", "player01"), other_id)
                self.assertEqual(
                    run(
                        other_path,
                        "exec",
                        "-T",
                        "player01",
                        "cat",
                        "/home/ubuntu/.wine/marker",
                    ),
                    "unrelated",
                )

                write(path, generate(1))
                run(path, "up", "-d", "--remove-orphans")
                removed = set(original_volumes) - set(generate(1)["volumes"])
                for name in removed:
                    docker("volume", "rm", original_volumes[name])
                    self.assertNotEqual(
                        subprocess.run(
                            ["docker", "volume", "inspect", original_volumes[name]],
                            capture_output=True,
                        ).returncode,
                        0,
                    )
                self.assertEqual(
                    run(
                        other_path,
                        "exec",
                        "-T",
                        "player01",
                        "cat",
                        "/home/ubuntu/.wine/marker",
                    ),
                    "unrelated",
                )
            finally:
                cleanup = generate(3)
                cleanup["volumes"].update(generate(2, prefix="Other")["volumes"])
                write(path, cleanup)
                try:
                    run(path, "down", "-v", "--remove-orphans")
                finally:
                    try:
                        run(other_path, "down", "-v", "--remove-orphans")
                    finally:
                        for name in cleanup["volumes"]:
                            volume = f"{project}_{name}"
                            if (
                                subprocess.run(
                                    ["docker", "volume", "inspect", volume],
                                    capture_output=True,
                                ).returncode
                                == 0
                            ):
                                docker("volume", "rm", volume)

    def test_isolation_and_recreation_with_persistent_account_data(self):
        with tempfile.TemporaryDirectory() as directory:
            for number in (1, 2):
                key = Path(directory) / f"LGplayer{number:02}_password.txt"
                key.write_text(f"fixture-{number}")
                key.chmod(0o600)
                if os.getuid() == 0:
                    os.chown(key, 1000, -1)
                elif os.getuid() != 1000:
                    subprocess.run(
                        ["sudo", "-n", "chown", "1000", str(key)], check=True
                    )
            env = self.environment(
                GATEWAY_SECRET_DIRECTORY=directory,
                GATEWAY_DEPLOYMENT_ID=uuid.uuid4().hex,
            )
            config = fixed_slots.compose_config(env)
            for service in config["services"].values():
                service["image"] = os.environ["GATEWAY_DOCKER_TEST_IMAGE"]
                service["entrypoint"] = ["/bin/sh", "-c"]
                service["command"] = [
                    "echo $$ > /tmp/workload.pid; exec tail -f /dev/null"
                ]
                service["init"] = True
                service.pop("ports")
            path = Path(directory) / "compose.json"
            path.write_text(json.dumps(fixed_slots.escape_compose(config)))
            compose = ["docker", "compose", "-f", str(path)]

            def run(*args):
                return subprocess.run(
                    [*compose, *args], check=True, capture_output=True, text=True
                ).stdout.strip()

            try:
                run("up", "-d")
                for number in (1, 2):
                    service = f"player{number:02}"
                    self.assertEqual(
                        run(
                            "exec",
                            "-T",
                            service,
                            "cat",
                            "/run/secrets/byond_password.txt",
                        ),
                        f"fixture-{number}",
                    )
                    write_secret = subprocess.run(
                        [
                            *compose,
                            "exec",
                            "-T",
                            service,
                            "sh",
                            "-c",
                            "echo changed > /run/secrets/byond_password.txt",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(write_secret.returncode, 0)
                    container_id = run("ps", "-q", service)
                    host_config = json.loads(
                        subprocess.run(
                            [
                                "docker",
                                "inspect",
                                "-f",
                                "{{json .HostConfig}}",
                                container_id,
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                        ).stdout
                    )
                    self.assertEqual(host_config["Memory"], 4 * 1024**3)
                    self.assertEqual(host_config["NanoCpus"], 2 * 10**9)
                    self.assertEqual(host_config["PidsLimit"], 512)
                    self.assertEqual(host_config["ShmSize"], 2 * 1024**3)
                    run(
                        "exec",
                        "-T",
                        service,
                        "sh",
                        "-c",
                        f"echo slot{number} > /home/ubuntu/.wine/marker; "
                        "test ! -e /var/run/docker.sock",
                    )
                run(
                    "exec",
                    "-T",
                    "player01",
                    "sh",
                    "-c",
                    "nc -lk -p 8080 -e /bin/cat </dev/null >/dev/null 2>&1 &",
                )
                player01 = run("ps", "-q", "player01")
                address = subprocess.run(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                        player01,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                run(
                    "exec",
                    "-T",
                    "player01",
                    "sh",
                    "-c",
                    "echo ok | nc -w 1 127.0.0.1 8080 | grep ok",
                )
                blocked = subprocess.run(
                    [
                        *compose,
                        "exec",
                        "-T",
                        "player02",
                        "nc",
                        "-w",
                        "2",
                        address,
                        "8080",
                    ],
                    input="probe\n",
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertNotEqual(blocked.returncode, 0)
                container_id = run("ps", "-q", "player02")
                workload_pid = run("exec", "-T", "player02", "cat", "/tmp/workload.pid")
                self.assertNotEqual(workload_pid, "1")
                restart_count = subprocess.run(
                    ["docker", "inspect", "-f", "{{.RestartCount}}", container_id],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                subprocess.run(
                    ["docker", "exec", container_id, "kill", "-9", workload_pid],
                    check=True,
                    capture_output=True,
                )
                for _ in range(50):
                    state = subprocess.run(
                        [
                            "docker",
                            "inspect",
                            "-f",
                            "{{.RestartCount}} {{.State.Running}}",
                            container_id,
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    count, running = state.split()
                    if int(count) > int(restart_count) and running == "true":
                        break
                    time.sleep(0.2)
                self.assertGreater(int(count), int(restart_count))
                self.assertEqual(running, "true")
                run("rm", "-sf", "player01")
                run("up", "-d")
                self.assertEqual(
                    run("exec", "-T", "player01", "cat", "/home/ubuntu/.wine/marker"),
                    "slot1",
                )
                self.assertEqual(
                    run("exec", "-T", "player02", "cat", "/home/ubuntu/.wine/marker"),
                    "slot2",
                )
            finally:
                run("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    unittest.main()
