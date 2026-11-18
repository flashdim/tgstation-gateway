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
        directx = self.prefix / "drive_c/Program Files (x86)/BYOND/directx"
        directx.mkdir(parents=True)
        (directx / "DXSETUP.exe").touch()
        (directx / "Jun2010_d3dx9_43_x86.cab").touch()
        self.installer_dll = self.root / "installer-d3dx9_43.dll"
        self.cab_dll = self.root / "cab-d3dx9_43.dll"
        self.installer_dll.write_bytes(b"bundled d3dx9_43")
        self.cab_dll.write_bytes(b"bundled d3dx9_43")

        commands = {
            "timeout": 'shift 2\nexec "$@"\n',
            "wine": (
                'printf "wine %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'if [ "$1" = DXSETUP.exe ]; then\n'
                '  [ "${FAIL_COMPONENT:-}" != DXSETUP ] || exit 17\n'
                '  destination="$WINEPREFIX/drive_c/windows/syswow64"\n'
                '  mkdir -p "$destination"\n'
                '  cp "$INSTALLER_DLL" "$destination/d3dx9_43.dll"\n'
                "fi\n"
            ),
            "cabextract": (
                'printf "cabextract %s\\n" "$*" >> "$COMMAND_LOG"\n'
                'while [ "$#" -gt 0 ]; do\n'
                '  if [ "$1" = -d ]; then destination="$2"; shift 2; else shift; fi\n'
                "done\n"
                'cp "$CAB_DLL" "$destination/d3dx9_43.dll"\n'
            ),
            "wineserver": 'printf "wineserver %s\\n" "$*" >> "$COMMAND_LOG"\n',
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
                "INSTALLER_DLL": str(self.installer_dll),
                "CAB_DLL": str(self.cab_dll),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_runs_bundled_directx_setup_then_winetricks_dxvk(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertEqual(commands[0], "wine DXSETUP.exe /silent")
        self.assertTrue(commands[1].startswith("cabextract -q -L -F d3dx9_43.dll -d "))
        self.assertEqual(
            commands[2:],
            [
                "wine reg add HKCU\\Software\\Wine\\DllOverrides /v *d3dx9_43 "
                "/t REG_SZ /d native /f",
                "winetricks -q dxvk",
                "wineserver --wait",
            ],
        )
        self.assertTrue(
            (self.prefix / "drive_c/windows/syswow64/d3dx9_43.dll").exists()
        )
        cache_paths = (self.root / "cache-path").read_text().splitlines()
        self.assertEqual(len(cache_paths), 1)
        self.assertEqual(Path(cache_paths[0]).name, "winetricks-cache")
        self.assertFalse(Path(cache_paths[0]).exists())

    def test_stops_on_directx_setup_or_dxvk_failure(self):
        for environment, expected in (
            ({"FAIL_COMPONENT": "DXSETUP"}, "wine DXSETUP.exe /silent"),
            ({"FAIL_VERB": "dxvk"}, "winetricks -q dxvk"),
        ):
            with self.subTest(environment=environment):
                result = self.install(**environment)
                self.assertNotEqual(result.returncode, 0)
                commands = self.log.read_text().splitlines()
                self.assertIn(expected, commands)
                self.assertNotIn("wineserver --wait", commands)
                self.log.unlink(missing_ok=True)

    def test_rejects_mismatch_between_bundled_and_installed_d3dx9(self):
        self.cab_dll.write_bytes(b"different DLL")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not install the expected D3DX9 library", result.stderr)
        self.assertNotIn("winetricks -q dxvk", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
