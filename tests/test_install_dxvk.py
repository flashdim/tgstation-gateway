import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallDxvkTest(unittest.TestCase):
    def run_installer(self, setting, fail=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'shift 2\nexec "$@"',
                "xvfb-run": 'shift\nexec "$@"',
                "winetricks": (
                    'printf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                    'printf "%s\\n" "$W_CACHE" > "$CACHE_LOG"\n'
                    'test "${FAIL_INSTALL:-0}" = 0'
                ),
                "wineserver": 'printf "wineserver %s\\n" "$*" >> "$COMMAND_LOG"',
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)
            log = root / "commands"
            cache_log = root / "cache"
            result = subprocess.run(
                ["sh", str(ROOT / "container/install-dxvk.sh")],
                env={
                    **os.environ,
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "BYOND_DXVK": setting,
                    "COMMAND_LOG": str(log),
                    "CACHE_LOG": str(cache_log),
                    "FAIL_INSTALL": "1" if fail else "0",
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            return (
                result,
                log.read_text().splitlines() if log.exists() else [],
                not Path(cache_log.read_text().strip()).exists()
                if cache_log.exists()
                else None,
            )

    def test_is_disabled_by_default(self):
        result, log, _ = self.run_installer("0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, [])

    def test_installs_pinned_dxvk_and_cleans_cache(self):
        result, log, cleaned = self.run_installer("1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, ["-q dxvk2071", "wineserver -k", "wineserver --wait"])
        self.assertTrue(cleaned)

    def test_failure_stops_build_and_cleans_cache(self):
        result, log, cleaned = self.run_installer("1", fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, ["-q dxvk2071"])
        self.assertTrue(cleaned)

    def test_rejects_invalid_setting(self):
        result, log, _ = self.run_installer("yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid BYOND_DXVK", result.stderr)
        self.assertEqual(log, [])


if __name__ == "__main__":
    unittest.main()
