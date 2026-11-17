import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallGraphicsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.prefix = self.root / "prefix"

        commands = {
            "wineserver": "exit 0\n",
            "winetricks": (
                'printf "winetricks %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'printf "%s\\n" "$W_CACHE" >> "$CACHE_LOG"\n'
                'printf archive > "$W_CACHE/$2.archive"\n'
                '[ "${FAIL_VERB:-}" != "$2" ] || exit 17\n'
            ),
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text("#!/bin/sh\nset -e\n" + body)
            path.chmod(0o755)
        self.log = self.root / "commands"

    def install(self, **extra_env):
        return subprocess.run(
            ["sh", str(ROOT / "container/install-graphics.sh")],
            env={
                **os.environ,
                "WINEPREFIX": str(self.prefix),
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "COMMAND_LOG": str(self.log),
                "CACHE_LOG": str(self.root / "cache-path"),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_installs_directx_and_dxvk_with_winetricks_in_order(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                "winetricks -q d3dx9",
                "winetricks -q d3dx9_43",
                "winetricks -q dxvk",
            ],
        )
        self.assertNotIn("DXSETUP.exe", self.log.read_text())
        cache_paths = (self.root / "cache-path").read_text().splitlines()
        self.assertEqual(len(set(cache_paths)), 1)
        self.assertEqual(Path(cache_paths[0]).name, "winetricks-cache")
        self.assertFalse(Path(cache_paths[0]).exists())

    def test_stops_on_directx_or_dxvk_verb_failure(self):
        for verb in ("d3dx9", "d3dx9_43", "dxvk"):
            env = {"FAIL_VERB": verb}
            with self.subTest(env=env):
                result = self.install(**env)
                self.assertNotEqual(result.returncode, 0)
                commands = self.log.read_text().splitlines()
                self.assertIn(f"winetricks -q {verb}", commands)
                self.assertNotIn("wineserver --wait", commands)
                self.log.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
