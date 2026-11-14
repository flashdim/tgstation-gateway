import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallClientTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "commands"
        for name in ("wineboot", "wineserver", "winetricks"):
            command = self.bin / name
            command.write_text(
                f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$COMMAND_LOG"\n'
                + ('[ "${FAIL_WINETRICKS:-0}" != 1 ]\n' if name == "winetricks" else "")
            )
            command.chmod(0o755)
        self.prefix = self.root / "prefix"
        self.create_file("drive_c/Program Files (x86)/BYOND/bin/byond.exe")

    def create_file(self, path):
        file = self.prefix / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()

    def install(self, **extra_env):
        return subprocess.run(
            ["sh", str(ROOT / "container/install-client.sh")],
            env={
                **os.environ,
                "WINEPREFIX": str(self.prefix),
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "COMMAND_LOG": str(self.log),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_installs_all_components_with_winetricks(self):
        self.create_file(
            "drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application/"
            "123/msedgewebview2.exe"
        )
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                "wineboot --init",
                "wineserver --wait",
                "winetricks -q vcrun2022 dxtrans dxvk2071 webview2",
                "wineserver -k",
                "wineserver --wait",
            ],
        )

    def test_fails_if_winetricks_fails(self):
        result = self.install(FAIL_WINETRICKS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("wineserver -k", self.log.read_text())

    def test_fails_if_webview_runtime_is_missing(self):
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WebView2 installation did not produce", result.stderr)


if __name__ == "__main__":
    unittest.main()
