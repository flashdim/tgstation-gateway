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
        self.directx = self.prefix / "drive_c/Program Files (x86)/BYOND/directx"
        self.directx.mkdir(parents=True)
        (self.directx / "DXSETUP.exe").touch()
        (self.directx / "Jun2010_d3dx9_43_x86.cab").touch()
        for directory in ("syswow64", "system32"):
            (self.prefix / "drive_c/windows" / directory).mkdir(parents=True)

        commands = {
            "wine": (
                'printf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                'if [ "$1" = DXSETUP.exe ]; then\n'
                '  [ "${FAIL_SETUP:-0}" = 0 ] || exit 17\n'
                '  printf native > "$WINEPREFIX/drive_c/windows/syswow64/d3dx9_43.dll"\n'
                "fi\n"
            ),
            "wineserver": "exit 0\n",
            "cabextract": 'printf native > "$6/d3dx9_43.dll"\n',
            "winetricks": (
                'printf "winetricks %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'printf "%s\\n" "$W_CACHE" >> "$CACHE_LOG"\n'
                'printf archive > "$W_CACHE/dxvk.tar.gz"\n'
                '[ "${FAIL_DXVK:-0}" = 0 ]\n'
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

    def test_installs_bundled_directx_then_winetricks_dxvk(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "winetricks -q dxvk",
            self.log.read_text(),
        )
        self.assertLess(
            self.log.read_text().index("DXSETUP.exe /silent"),
            self.log.read_text().index("winetricks -q dxvk"),
        )
        self.assertIn("*d3dx9_43 /t REG_SZ /d native", self.log.read_text())
        cache_path = Path((self.root / "cache-path").read_text().strip())
        self.assertEqual(cache_path.name, "winetricks-cache")
        self.assertFalse(cache_path.exists())

    def test_stops_on_directx_or_dxvk_install_failure(self):
        for env in ({"FAIL_SETUP": "1"}, {"FAIL_DXVK": "1"}):
            with self.subTest(env=env):
                result = self.install(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    (self.prefix / "drive_c/windows/syswow64/d3d9.dll").exists()
                )


if __name__ == "__main__":
    unittest.main()
