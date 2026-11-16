import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunClientTest(unittest.TestCase):
    def run_client(self, server=None, gpu=None, fail_registry=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'shift\nexec "$@"',
                "xdpyinfo": 'test "$1" = "-display" && test "$2" = ":42"',
                "wine": (
                    'case "$PATH" in /opt/wine/bin:*) ;; '
                    '*) echo "Wrong Wine runtime path" >&2; exit 98;; esac\n'
                    'if [ -n "${LD_PRELOAD:-}" ]; then\n'
                    '  echo "LD_PRELOAD leaked to Wine" >&2\n'
                    "  exit 97\n"
                    "fi\n"
                    'if [ "$1" = reg ]; then\n'
                    '  printf "%s\\n" "$@" > "$WINE_LOG"\n'
                    '  [ "${FAIL_REGISTRY:-0}" = 0 ]\n'
                    "  exit $?\n"
                    "fi\n"
                    'printf "%s\\n" "$DISPLAY" "$@"'
                ),
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)

            runtime = root / "runtime"
            runtime.mkdir()
            prefix = root / "wine prefix"
            (runtime / "container-env").write_text(
                f"export DISPLAY=':42'\nexport WINEPREFIX='{prefix}'\n"
                + (f"export BYOND_SERVER='{server}'\n" if server is not None else "")
                + (f"export BYOND_WEBVIEW2_GPU='{gpu}'\n" if gpu is not None else "")
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
                "WINE_LOG": str(root / "wine-log"),
                "FAIL_REGISTRY": "1" if fail_registry else "0",
                "LD_PRELOAD": "libm.so.6",
            }
            env.pop("BYOND_SERVER", None)
            env.pop("BYOND_WEBVIEW2_GPU", None)
            result = subprocess.run(
                ["bash", str(ROOT / "container/run-client.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            log = root / "wine-log"
            return result, prefix, log.read_text().splitlines() if log.exists() else []

    def test_launches_byond_after_loading_session_environment(self):
        for server in (None, ""):
            with self.subTest(server=server):
                result, prefix, registry = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(registry, [])
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
                    ],
                )

    def test_launches_dreamseeker_with_server_url(self):
        for server, url in (
            ("ss13.lazorgator.party:1337", "byond://ss13.lazorgator.party:1337"),
            ("byond://example.org:1234", "byond://example.org:1234"),
            ("[::1]:1337", "byond://[::1]:1337"),
        ):
            with self.subTest(server=server):
                result, prefix, _ = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(
                            prefix
                            / "drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe"
                        ),
                        url,
                    ],
                )

    def test_rejects_invalid_server(self):
        for server in (
            "example.org",
            "https://example.org:1337",
            "example.org:0",
            "example.org:65536",
            "example.org:1337 extra",
            ":1337",
        ):
            with self.subTest(server=server):
                result, _, _ = self.run_client(server)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid BYOND_SERVER", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_configures_webview2_gpu_before_launch(self):
        result, prefix, registry = self.run_client("example.org:1337", gpu="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            registry,
            [
                "reg",
                "add",
                r"HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
                "/v",
                "*",
                "/t",
                "REG_SZ",
                "/d",
                "--ignore-gpu-blocklist --use-gl=angle --use-angle=d3d11 "
                "--disable-direct-composition",
                "/f",
            ],
        )
        self.assertEqual(
            result.stdout.splitlines(),
            [
                ":42",
                str(prefix / "drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe"),
                "byond://example.org:1337",
            ],
        )

    def test_fails_without_launch_when_registry_update_fails(self):
        result, _, registry = self.run_client(gpu="1", fail_registry=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(registry)
        self.assertIn("Failed to configure WebView2", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rejects_invalid_webview2_gpu_setting(self):
        result, _, registry = self.run_client(gpu="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(registry, [])
        self.assertIn("Invalid BYOND_WEBVIEW2_GPU", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
