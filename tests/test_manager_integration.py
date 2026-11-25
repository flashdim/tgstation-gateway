import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import unittest

from test_manager import DockerClient, PlayerSpec, SECCOMP, make_manager


class FixtureSpec(PlayerSpec):
    def container_body(self, labels, secret_path):
        body = super().container_body(labels, secret_path)
        body["Entrypoint"] = ["/bin/sh", "-c"]
        body["Cmd"] = ["while :; do sleep 60; done"]
        body["Healthcheck"] = {
            "Test": ["CMD", "/bin/sh", "-c", "exit 0"],
            "Interval": 1000000000,
            "Timeout": 1000000000,
            "Retries": 3,
        }
        return body


@unittest.skipUnless(
    os.environ.get("GATEWAY_DOCKER_TEST_IMAGE"),
    "Set GATEWAY_DOCKER_TEST_IMAGE to a local image containing /bin/sh and sleep",
)
class DockerIsolationTest(unittest.TestCase):
    def test_two_slots_mount_and_discard_isolated_data(self):
        manager = make_manager()
        manager.docker = DockerClient()
        manager.spec = FixtureSpec(
            image=os.environ["GATEWAY_DOCKER_TEST_IMAGE"],
            seccomp_profile=SECCOMP,
            secret_directory=manager.spec.secret_directory,
            network="none",
        )
        manager.clock = time.monotonic
        manager.sleep = time.sleep
        manager.start_timeout = 30
        sessions = []
        volumes = []
        try:
            for account in ("LGplayer01", "LGplayer02"):
                sessions.append(manager.start(account))
            for session in sessions:
                inspect = manager.docker.inspect(session.container_id)
                mounts = inspect["Mounts"]
                secret = next(
                    m
                    for m in mounts
                    if m["Destination"] == "/run/secrets/byond_key.txt"
                )
                self.assertFalse(secret["RW"])
                self.assertEqual(
                    secret["Source"],
                    str(
                        Path(manager.spec.secret_directory)
                        / f"{session.account}_key.txt"
                    ),
                )
                volumes.append([m["Name"] for m in mounts if m["Type"] == "volume"])
                expected = hashlib.sha256(
                    f"test key for {session.account}".encode()
                ).hexdigest()
                digest = self.docker(
                    "exec",
                    session.container_id,
                    "sha256sum",
                    "/run/secrets/byond_key.txt",
                ).split()[0]
                self.assertEqual(digest, expected)
                self.docker(
                    "exec",
                    session.container_id,
                    "sh",
                    "-c",
                    'test ! -e /var/run/docker.sock && test "$(ls /run/secrets | wc -l)" -eq 1 && ! echo x > /run/secrets/byond_key.txt',
                )
                self.docker(
                    "exec",
                    session.container_id,
                    "sh",
                    "-c",
                    f"echo {session.account} > /home/ubuntu/.wine/marker; echo {session.account} > /home/ubuntu/.local/share/marker",
                )
                metadata = json.dumps(inspect) + json.dumps(manager.status())
                metadata += self.docker("logs", session.container_id)
                metadata += self.docker(
                    "exec",
                    session.container_id,
                    "sh",
                    "-c",
                    "for f in /proc/[0-9]*/cmdline; do tr '\\000' ' ' < \"$f\" 2>/dev/null || :; done",
                )
                metadata += self.docker("image", "inspect", manager.spec.image)
                self.assertNotIn("test key for", metadata)
            self.assertTrue(set(volumes[0]).isdisjoint(volumes[1]))
            for session in sessions:
                for path in (
                    "/home/ubuntu/.wine/marker",
                    "/home/ubuntu/.local/share/marker",
                ):
                    self.assertEqual(
                        self.docker("exec", session.container_id, "cat", path).strip(),
                        session.account,
                    )
            self.docker("rm", "-f", sessions[0].container_id)
            manager.reap()
            self.assertIsNone(manager.registry.state(sessions[0].account))
            for volume in volumes[0]:
                result = subprocess.run(
                    ["docker", "volume", "inspect", volume], capture_output=True
                )
                self.assertNotEqual(result.returncode, 0)
            sessions.pop(0)
            replacement = manager.start("LGplayer01")
            sessions.append(replacement)
            self.docker(
                "exec",
                replacement.container_id,
                "sh",
                "-c",
                "test ! -e /home/ubuntu/.wine/marker && test ! -e /home/ubuntu/.local/share/marker",
            )
        finally:
            for session in sessions:
                manager.terminate(session.account, session.session_id)
        for volume in sum(volumes, []):
            result = subprocess.run(
                ["docker", "volume", "inspect", volume], capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)

    @staticmethod
    def docker(*args):
        return subprocess.run(
            ["docker", *args], check=True, capture_output=True, text=True
        ).stdout
