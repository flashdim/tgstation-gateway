import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGER_PROCESS = r'(^|[\\/])byond[.]exe"?([[:space:]]|$)'
DREAMSEEKER_PROCESS = r'(^|[\\/])dreamseeker[.]exe"?([[:space:]]|$)'


class HealthcheckTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands"
        commands = {
            "pgrep": (
                'printf "pgrep %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'test "$1" = -f && test "$2" = "$EXPECTED_PROCESS" && '
                'test "${PAGER_RUNNING:-1}" = 1'
            ),
            "curl": (
                'printf "curl %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'case "$*" in\n'
                '  *https://*) test "${HTTPS_OK:-0}" = 1 ;;\n'
                '  *http://*) test "${HTTP_OK:-0}" = 1 ;;\n'
                "  *) exit 1 ;;\n"
                "esac"
            ),
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

    def check(self, **extra_env):
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "COMMAND_LOG": str(self.log),
            "EXPECTED_PROCESS": PAGER_PROCESS,
            **extra_env,
        }
        for key in ("SELKIES_SUBFOLDER", "SUBFOLDER", "SELKIES_PORT", "BYOND_SERVER"):
            if key not in extra_env:
                env.pop(key, None)
        return subprocess.run(
            ["sh", str(ROOT / "container/healthcheck.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_requires_pager_even_if_selkies_is_available(self):
        result = self.check(PAGER_RUNNING="0", HTTP_OK="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BYOND pager is not running", result.stderr)

    def test_requires_selkies_when_pager_is_running(self):
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Selkies health endpoint is unavailable", result.stderr)

    def test_requires_dreamseeker_in_direct_mode(self):
        env = {
            "BYOND_SERVER": "example.org:1337",
            "EXPECTED_PROCESS": DREAMSEEKER_PROCESS,
            "HTTP_OK": "1",
        }
        result = self.check(**env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines()[0],
            f"pgrep -f {DREAMSEEKER_PROCESS}",
        )

        result = self.check(**env, PAGER_RUNNING="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Dream Seeker is not running", result.stderr)

    def test_http_fallback_uses_configured_port_and_prefix(self):
        result = self.check(
            HTTP_OK="1", SELKIES_PORT="8081", SELKIES_SUBFOLDER="/player/"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                f"pgrep -f {PAGER_PROCESS}",
                "curl -fs -k --max-time 2 -o /dev/null https://localhost:8081/player/api/health",
                "curl -fsS --max-time 2 -o /dev/null http://localhost:8081/player/api/health",
            ],
        )

    def test_https_uses_legacy_prefix(self):
        result = self.check(HTTPS_OK="1", SUBFOLDER="player")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines()[-1],
            "curl -fs -k --max-time 2 -o /dev/null https://localhost:8080/player/api/health",
        )


if __name__ == "__main__":
    unittest.main()
