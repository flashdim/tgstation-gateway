import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
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

    def test_each_slot_receives_only_its_own_key_path(self):
        with tempfile.TemporaryDirectory() as directory:
            for account in ("LGplayer01", "LGplayer02"):
                (Path(directory) / f"{account}_key.txt").write_text("private\n")
            result = fixed_slots.compose_config(
                self.environment(GATEWAY_SECRET_DIRECTORY=directory)
            )
            for index in (1, 2):
                service = result["services"][f"player{index:02}"]
                secret = next(
                    mount
                    for mount in service["volumes"]
                    if mount["target"] == "/run/secrets/byond_key.txt"
                )
                self.assertEqual(
                    secret["source"], f"{directory}/LGplayer{index:02}_key.txt"
                )
                self.assertTrue(secret["read_only"])
                self.assertFalse(secret["bind"]["create_host_path"])
            self.assertNotIn("private", json.dumps(result))

    def test_invalid_key_port_or_slot_configuration_fails(self):
        for overrides in (
            {"GATEWAY_PORT": "65535"},
            {"GATEWAY_PORT": "0"},
            {"GATEWAY_SLOT_PATH": "/"},
            {"GATEWAY_SECRET_DIRECTORY": "relative"},
            {"BYOND_SERVER": ""},
            {"GATEWAY_FIXED_LANDING": "1", "GATEWAY_LANDING_PORT": "18081"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(fixed_slots.ConfigError):
                    fixed_slots.compose_config(self.environment(**overrides))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "LGplayer01_key.txt").write_text("key")
            (Path(directory) / "LGplayer02_key.txt").symlink_to(
                Path(directory) / "LGplayer01_key.txt"
            )
            with self.assertRaises(fixed_slots.ConfigError):
                fixed_slots.compose_config(
                    self.environment(GATEWAY_SECRET_DIRECTORY=directory)
                )
            (Path(directory) / "LGplayer02_key.txt").unlink()
            os.link(
                Path(directory) / "LGplayer01_key.txt",
                Path(directory) / "LGplayer02_key.txt",
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
    def test_isolation_and_recreation_with_persistent_account_data(self):
        with tempfile.TemporaryDirectory() as directory:
            for number in (1, 2):
                key = Path(directory) / f"LGplayer{number:02}_key.txt"
                key.write_text(f"fixture-{number}")
                key.chmod(0o644)
            env = self.environment(
                GATEWAY_SECRET_DIRECTORY=directory,
                GATEWAY_DEPLOYMENT_ID=uuid.uuid4().hex,
            )
            config = fixed_slots.compose_config(env)
            for service in config["services"].values():
                service["image"] = os.environ["GATEWAY_DOCKER_TEST_IMAGE"]
                service["entrypoint"] = ["/bin/sh", "-c"]
                service["command"] = ["while :; do sleep 60; done"]
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
                        run("exec", "-T", service, "cat", "/run/secrets/byond_key.txt"),
                        f"fixture-{number}",
                    )
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
                subprocess.run(
                    ["docker", "exec", container_id, "kill", "-9", "1"],
                    check=True,
                    capture_output=True,
                )
                for _ in range(50):
                    state = subprocess.run(
                        ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                    if state == "true":
                        break
                    time.sleep(0.2)
                self.assertEqual(state, "true")
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
