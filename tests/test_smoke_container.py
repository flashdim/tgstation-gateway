import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SmokeContainerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "docker.log"
        commands = {
            "docker": (
                'printf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
                'case "$1" in\n'
                '  run) echo test-container ;;\n'
                '  port) echo 127.0.0.1:12345 ;;\n'
                '  inspect) echo false ;;\n'
                '  exec|logs|rm) exit 0 ;;\n'
                '  *) exit 1 ;;\n'
                "esac"
            ),
            "curl": '[ "${FAIL_HEALTH:-0}" != 1 ]',
            "sleep": "exit 0",
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

    def smoke(self, **extra_env):
        return subprocess.run(
            ["bash", str(ROOT / "tests/smoke-container.sh"), "example:ci"],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "DOCKER_LOG": str(self.log),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_waits_for_service_and_removes_container(self):
        result = self.smoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertEqual(
            commands[0], "run -d --init --shm-size=2g -p 127.0.0.1::8080 example:ci"
        )
        self.assertEqual(commands.count("exec test-container pgrep -f [b]yond.exe"), 2)
        self.assertEqual(commands[-1], "rm -f test-container")
        self.assertNotIn("logs test-container", commands)

    def test_reports_logs_and_removes_exited_container(self):
        result = self.smoke(FAIL_HEALTH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exited before it became ready", result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines()[-2:],
            ["logs test-container", "rm -f test-container"],
        )


if __name__ == "__main__":
    unittest.main()
