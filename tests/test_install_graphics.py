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
            "curl": (
                'printf "curl %s\\n" "$*" >> "$COMMAND_LOG"\nprintf archive > "$8"\n'
            ),
            "sha256sum": (
                "read -r digest archive\n"
                'test -s "$archive"\n'
                'printf "verify %s\\n" "$digest" >> "$COMMAND_LOG"\n'
                '[ "${BAD_CHECKSUM:-0}" = 0 ]\n'
            ),
            "tar": (
                'printf "extract\\n" >> "$COMMAND_LOG"\n'
                "for arch in x32 x64; do\n"
                '  dir="$4/dxvk-3.1.1/$arch"\n'
                '  mkdir -p "$dir"\n'
                "  for dll in dxgi d3d8 d3d9 d3d10core d3d11; do\n"
                '    printf "%s" "$arch" > "$dir/$dll.dll"\n'
                "  done\n"
                "done\n"
            ),
        }
        for name, body in commands.items():
            path = self.bin / name
            path.write_text("#!/bin/sh\nset -e\n" + body)
            path.chmod(0o755)
        self.log = self.root / "commands"
        (self.prefix / "drive_c/windows/system32").mkdir(parents=True)

    def install(self, **extra_env):
        return subprocess.run(
            ["sh", str(ROOT / "container/install-graphics.sh")],
            env={
                **os.environ,
                "WINEPREFIX": str(self.prefix),
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "COMMAND_LOG": str(self.log),
                "INSTALLER_DLL": str(self.installer_dll),
                "CAB_DLL": str(self.cab_dll),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_runs_bundled_directx_setup_then_installs_verified_dxvk(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertEqual(commands[0], "wine DXSETUP.exe /silent")
        self.assertTrue(commands[1].startswith("cabextract -q -L -F d3dx9_43.dll -d "))
        self.assertIn("/v *d3dx9_43 /t REG_SZ /d native /f", commands[2])
        self.assertIn("/v3.1.1/dxvk-3.1.1.tar.gz", commands[3])
        self.assertTrue(commands[4].startswith("verify "))
        self.assertEqual(commands[5], "extract")
        for dll in ("dxgi", "d3d8", "d3d9", "d3d10core", "d3d11"):
            self.assertEqual(
                (self.prefix / f"drive_c/windows/syswow64/{dll}.dll").read_text(),
                "x32",
            )
            self.assertEqual(
                (self.prefix / f"drive_c/windows/system32/{dll}.dll").read_text(),
                "x64",
            )
            self.assertIn(
                f"wine reg add HKCU\\Software\\Wine\\DllOverrides /v {dll} "
                "/t REG_SZ /d native /f",
                commands,
            )
        self.assertEqual(commands[-1], "wineserver --wait")

    def test_stops_before_extracting_dxvk_if_checksum_fails(self):
        result = self.install(BAD_CHECKSUM="1")
        self.assertNotEqual(result.returncode, 0)
        commands = self.log.read_text().splitlines()
        self.assertTrue(commands[-1].startswith("verify "))
        self.assertFalse((self.prefix / "drive_c/windows/syswow64/d3d9.dll").exists())

    def test_stops_on_directx_setup_failure(self):
        result = self.install(FAIL_COMPONENT="DXSETUP")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.log.read_text().splitlines(), ["wine DXSETUP.exe /silent"]
        )

    def test_rejects_mismatch_between_bundled_and_installed_d3dx9(self):
        self.cab_dll.write_bytes(b"different DLL")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not install the expected D3DX9 library", result.stderr)
        self.assertNotIn("curl ", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
