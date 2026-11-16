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
                "  run) echo test-container ;;\n"
                "  port) echo 127.0.0.1:12345 ;;\n"
                "  inspect)\n"
                '    if [ "$3" = "{{json .Config.Healthcheck.Test}}" ]; then\n'
                """      echo '["CMD","/usr/local/bin/healthcheck"]'\n"""
                "    else echo false; fi ;;\n"
                "  exec)\n"
                '    case "$3" in\n'
                '      pgrep) if [ "$4" = "-x" ]; then '
                'if [ "$5" = openbox ] && [ "${WAYLAND_TEST:-0}" = 1 ]; then '
                '[ "${UNEXPECTED_OPENBOX:-0}" = 1 ]; else '
                '[ "${NO_WINDOW_MANAGER:-0}" = 0 ]; '
                "fi; "
                'else test ! -f "$SERVICE_STOPPED"; fi ;;\n'
                '      stat) echo "${X11_SOCKET_MODE:-1777}" ;;\n'
                "      sh) exit 0 ;;\n"
                '      s6-svc) touch "$SERVICE_STOPPED" ;;\n'
                "      /usr/local/bin/healthcheck) "
                'test ! -f "$SERVICE_STOPPED" || [ "${BROKEN_HEALTH:-0}" = 1 ] ;;\n'
                "      *) exit 1 ;;\n"
                "    esac ;;\n"
                "  logs|rm) exit 0 ;;\n"
                "  *) exit 1 ;;\n"
                "esac"
            ),
            "curl": '[ "${FAIL_HEALTH:-0}" != 1 ]',
            "sleep": "exit 0",
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

    def smoke(self, script="smoke-container.sh", **extra_env):
        return subprocess.run(
            ["bash", str(ROOT / "tests" / script), "example:ci"],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "DOCKER_LOG": str(self.log),
                "SERVICE_STOPPED": str(self.root / "stopped"),
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
            commands[0],
            "run -d --init --security-opt seccomp=examples/seccomp.json "
            "--shm-size=2g -p 127.0.0.1::8080 example:ci",
        )
        self.assertIn("exec test-container s6-svc -d /etc/service/byond", commands)
        self.assertEqual(
            commands.count("exec test-container /usr/local/bin/healthcheck"), 2
        )
        self.assertEqual(commands[-1], "rm -f test-container")
        self.assertNotIn("logs test-container", commands)

    def test_rejects_healthy_status_without_pager(self):
        result = self.smoke(BROKEN_HEALTH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Health check passed without the BYOND pager", result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[-1], "rm -f test-container")

    def test_requires_window_manager(self):
        result = self.smoke(NO_WINDOW_MANAGER="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exited before it became ready", result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[-1], "rm -f test-container")

    def test_reports_logs_and_removes_exited_container(self):
        result = self.smoke(FAIL_HEALTH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exited before it became ready", result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines()[-2:],
            ["logs test-container", "rm -f test-container"],
        )

    def test_wayland_does_not_stop_window_manager_to_pass(self):
        result = self.smoke(script="smoke-wayland.sh", WAYLAND_TEST="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertIn("-e SELKIES_WAYLAND=true", commands[0])
        self.assertIn("exec test-container pgrep -x labwc", commands)
        self.assertIn("exec test-container pgrep -x openbox", commands)
        self.assertFalse(any("s6-svc" in command for command in commands))
        self.assertEqual(commands[-1], "rm -f test-container")

    def test_wayland_rejects_competing_openbox(self):
        result = self.smoke(
            script="smoke-wayland.sh", WAYLAND_TEST="1", UNEXPECTED_OPENBOX="1"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Openbox must not compete", result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines()[-2:],
            ["logs test-container", "rm -f test-container"],
        )

    def test_wayland_requires_compositor(self):
        result = self.smoke(
            script="smoke-wayland.sh", WAYLAND_TEST="1", NO_WINDOW_MANAGER="1"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exited before it became ready", result.stderr)

    def test_wayland_requires_sticky_x11_socket_directory(self):
        result = self.smoke(
            script="smoke-wayland.sh", WAYLAND_TEST="1", X11_SOCKET_MODE="777"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("X11 socket directory does not have mode 1777", result.stderr)


if __name__ == "__main__":
    unittest.main()
