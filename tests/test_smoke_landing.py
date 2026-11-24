import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SmokeLandingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        commands = {
            "docker": """
echo "$*" >> "$COMMAND_LOG"
case "$1" in
    run)
        case " $* " in
            *" --rm "*) exit 1 ;;
            *" --entrypoint "*) echo fake ;;
            *" GATEWAY_QUERY_HOST=game "*) echo configured ;;
            *) echo landing ;;
        esac ;;
    port)
        if [ "$2" = configured ]; then echo 127.0.0.1:2222
        else echo 127.0.0.1:1111; fi ;;
    stop) exit 1 ;;
esac
""",
            "curl": """
case "$*" in
    *127.0.0.1:2222/status.json*)
        echo request >> "$REQUEST_LOG"
        if [ "$ALWAYS_FAIL" = 1 ] || [ "$(wc -l < "$REQUEST_LOG")" -eq 1 ]; then
            exit 56
        fi
        echo '{"online": true, "map": "MetaStation", "round_seconds": 3661, "players": 12, "popcap": 100}' ;;
    *127.0.0.1:1111/status.json*) echo '{"online": null}' > "$4" ;;
    *127.0.0.1:1111/status.js*) echo 'status.json' > "$4" ;;
    *) echo '<script src="slots.js"></script>' > "$4" ;;
esac
""",
            "sleep": "exit 0",
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

    def run_smoke(self, always_fail):
        result = subprocess.run(
            ["bash", str(ROOT / "tests/smoke-landing.sh"), "example:ci"],
            cwd=self.root,
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "COMMAND_LOG": str(self.root / "commands"),
                "REQUEST_LOG": str(self.root / "requests"),
                "ALWAYS_FAIL": str(int(always_fail)),
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result

    def test_configured_status_retries_startup_reset(self):
        result = self.run_smoke(always_fail=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len((self.root / "requests").read_text().splitlines()), 2)
        self.assertIn("stop fake", (self.root / "commands").read_text())

    def test_configured_status_fails_after_bounded_wait(self):
        result = self.run_smoke(always_fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len((self.root / "requests").read_text().splitlines()), 25)
        self.assertNotIn("stop fake", (self.root / "commands").read_text())


if __name__ == "__main__":
    unittest.main()
