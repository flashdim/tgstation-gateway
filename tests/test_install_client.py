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
        for name in ("proton-wine", "wineserver", "winetricks"):
            command = self.bin / name
            command.write_text(
                f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$COMMAND_LOG"\n'
                'printf "%s|%s\\n" "${WINELOADER-unset}" "${WINESERVER-unset}" '
                '>> "$RUNTIME_LOG"\n'
                'printf "%s\\n" "${LD_PRELOAD-unset}" >> "$PRELOAD_LOG"\n'
                + (
                    'printf "%s\\n" "${WINEDLLOVERRIDES-unset}" >> "$OVERRIDE_LOG"\n'
                    if name in ("proton-wine", "winetricks")
                    else ""
                )
                + (
                    'printf "%s\\n" "$W_CACHE" >> "$CACHE_LOG"\n'
                    'printf "installer" > "$W_CACHE/installer.exe"\n'
                    '[ "${FAIL_COMPONENT:-}" != "$2" ] || exit 17\n'
                    if name == "winetricks"
                    else ""
                )
            )
            command.chmod(0o755)
        timeout = self.bin / "timeout"
        timeout.write_text(
            "#!/bin/sh\n"
            "shift 2\n"
            'if [ -n "${TIMEOUT_COMPONENT:-}" ] && '
            '[ "$TIMEOUT_COMPONENT" = "${3:-}" ]; then exit 124; fi\n'
            'exec "$@"\n'
        )
        timeout.chmod(0o755)
        self.prefix = self.root / "prefix"

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
                "RUNTIME_LOG": str(self.root / "runtime"),
                "PRELOAD_LOG": str(self.root / "preload"),
                "OVERRIDE_LOG": str(self.root / "overrides"),
                "CACHE_LOG": str(self.root / "cache-paths"),
                "LD_PRELOAD": "selkies-interposer.so",
                "WINEDLLOVERRIDES": "example=b",
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
        result = self.install(
            WINELOADER="/usr/bin/wine",
            WINESERVER="/usr/bin/wineserver",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                "proton-wine wineboot --update",
                "wineserver --wait",
                "winetricks -q vcrun2022",
                "winetricks -q dxtrans",
                "winetricks -q corefonts",
                "winetricks -q webview2",
                "wineserver --wait",
            ],
        )
        self.assertEqual(
            (self.root / "runtime").read_text().splitlines(),
            ["/opt/ge-proton/files/bin/wine|/opt/ge-proton/files/bin/wineserver"]
            * 7,
        )
        self.assertIn(
            "Starting Wine prefix initialization (timeout: 300s)", result.stdout
        )
        self.assertIn("Starting Winetricks webview2 (timeout: 240s)", result.stdout)
        self.assertIn("Completed Winetricks webview2", result.stdout)
        self.assertEqual(
            (self.root / "preload").read_text().splitlines(), ["unset"] * 7
        )
        self.assertEqual(
            (self.root / "overrides").read_text().splitlines(),
            ["mscoree,mshtml=d"] + ["example=b"] * 4,
        )
        cache_paths = (self.root / "cache-paths").read_text().splitlines()
        self.assertEqual(len(set(cache_paths)), 1)
        self.assertFalse(Path(cache_paths[0]).exists())

    def test_fails_if_winetricks_fails(self):
        result = self.install(FAIL_COMPONENT="dxtrans")
        self.assertEqual(result.returncode, 17)
        self.assertIn("Winetricks dxtrans failed with exit code 17", result.stderr)
        self.assertNotIn("winetricks -q webview2", self.log.read_text())
        self.assertEqual(self.log.read_text().count("wineserver --wait"), 1)
        cache_path = (self.root / "cache-paths").read_text().splitlines()[0]
        self.assertFalse(Path(cache_path).exists())

    def test_reports_component_timeout(self):
        result = self.install(TIMEOUT_COMPONENT="webview2")
        self.assertEqual(result.returncode, 124)
        self.assertIn("Winetricks webview2 timed out after 240s", result.stderr)
        self.assertEqual(self.log.read_text().count("wineserver --wait"), 1)

    def test_fails_if_corefonts_fails(self):
        result = self.install(FAIL_COMPONENT="corefonts")
        self.assertEqual(result.returncode, 17)
        self.assertIn("Winetricks corefonts failed", result.stderr)
        self.assertNotIn("winetricks -q webview2", self.log.read_text())

    def test_fails_if_webview_runtime_is_missing(self):
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WebView2 installation did not produce", result.stderr)


if __name__ == "__main__":
    unittest.main()
