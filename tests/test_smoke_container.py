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
                'case "$5" in\n'
                '  kwin_x11|plasmashell) [ "$5" != "${MISSING_PROCESS:-}" ] ;;\n'
                "  *) exit 1 ;;\n"
                "esac; "
                'else test ! -f "$SERVICE_STOPPED"; fi ;;\n'
                '      s6-svc) touch "$SERVICE_STOPPED" ;;\n'
                "      /usr/local/bin/healthcheck) "
                'test ! -f "$SERVICE_STOPPED" || [ "${BROKEN_HEALTH:-0}" = 1 ] ;;\n'
                '      sh)\n'
                '        case "$5" in\n'
                '          *\'readConfig("FillMode", -1)\'*) '
                '[ "${WRONG_WALLPAPER:-0}" = 0 ] ;;\n'
                '          *) [ "${WRONG_DISPLAY:-0}" = 0 ] ;;\n'
                '        esac ;;\n'
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

    def smoke(self, **extra_env):
        return subprocess.run(
            ["bash", str(ROOT / "tests/smoke-container.sh"), "example:ci"],
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
            "--shm-size=2g -p 127.0.0.1::8080 -e SELKIES_WAYLAND=false example:ci",
        )
        self.assertIn("exec test-container s6-svc -d /etc/service/byond", commands)
        self.assertIn(
            "exec test-container pgrep -f /byond[.]exe([[:space:]]|$)", commands
        )
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

    def test_requires_plasma_and_kwin(self):
        for process in ("kwin_x11", "plasmashell"):
            with self.subTest(process=process):
                result = self.smoke(MISSING_PROCESS=process)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exited before it became ready", result.stderr)
                self.assertEqual(
                    self.log.read_text().splitlines()[-1], "rm -f test-container"
                )

    def test_requires_x11_session(self):
        result = self.smoke(WRONG_DISPLAY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text().splitlines()[-1], "rm -f test-container")

    def test_rejects_wrong_wallpaper_configuration(self):
        result = self.smoke(WRONG_WALLPAPER="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(
            "exec test-container s6-svc -d /etc/service/byond",
            self.log.read_text().splitlines(),
        )
        self.assertEqual(self.log.read_text().splitlines()[-1], "rm -f test-container")

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
