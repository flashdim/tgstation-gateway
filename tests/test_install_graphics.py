import os
from pathlib import Path
import subprocess
import tarfile
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

        payload = self.root / "payload/dxvk-2.7.1"
        for arch in ("x32", "x64"):
            (payload / arch).mkdir(parents=True)
            for dll in ("d3d9", "d3d10core", "d3d11", "dxgi"):
                (payload / arch / f"{dll}.dll").write_text(f"{arch}-{dll}")
        self.archive = self.root / "dxvk.tar.gz"
        with tarfile.open(self.archive, "w:gz") as archive:
            archive.add(payload, arcname="dxvk-2.7.1")

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
            "curl": 'cp "$FIXTURE" "$6"\n',
            "sha256sum": 'cat >/dev/null\n[ "${FAIL_CHECKSUM:-0}" = 0 ]\n',
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
                "FIXTURE": str(self.archive),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_installs_bundled_directx_and_both_dxvk_architectures(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for arch, directory in (("x32", "syswow64"), ("x64", "system32")):
            for dll in ("d3d9", "d3d10core", "d3d11", "dxgi"):
                file = self.prefix / "drive_c/windows" / directory / f"{dll}.dll"
                self.assertEqual(file.read_text(), f"{arch}-{dll}")
                self.assertIn(f"*{dll} /t REG_SZ /d native", self.log.read_text())
        self.assertIn("*d3dx9_43 /t REG_SZ /d native", self.log.read_text())

    def test_stops_on_setup_or_checksum_failure(self):
        for env in ({"FAIL_SETUP": "1"}, {"FAIL_CHECKSUM": "1"}):
            with self.subTest(env=env):
                result = self.install(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(
                    (self.prefix / "drive_c/windows/syswow64/d3d9.dll").exists()
                )


if __name__ == "__main__":
    unittest.main()
