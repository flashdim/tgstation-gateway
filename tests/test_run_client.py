import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunClientTest(unittest.TestCase):
    def run_client(
        self, server=None, gpu=None, fail_registry=False, wayland=False, warmup="normal"
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'case "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"',
                "pgrep": (
                    '[ "$1 $2 $3 $4" = "-ix -u $(id -u) dreamseeker[.]exe" ] || exit 2\n'
                    '[ -r "$WINE_PID_FILE" ] || exit 1\n'
                    'pid=$(cat "$WINE_PID_FILE")\n'
                    'kill -0 "$pid" 2>/dev/null || exit 1\n'
                    'printf "%s\\n" "$pid"'
                ),
                "wmctrl": (
                    'if [ "$1" = "-l" ] && [ -r "$WINE_PID_FILE" ] && '
                    '[ "$WARMUP" != "no-window" ]; then\n'
                    '  printf "0x123 0 %s Dream Seeker\\n" "$(cat "$WINE_PID_FILE")"\n'
                    'elif [ "$1" = "-ic" ]; then\n'
                    '  [ "$2" = "0x123" ] || exit 1\n'
                    '  printf "close\\n" >> "$EVENT_LOG"\n'
                    '  case "$WARMUP" in stuck|cleanup-fails) ;; '
                    '*) : > "$WINE_CLOSE_FILE";; esac\n'
                    "fi"
                ),
                "pkill": (
                    '[ "$1 $2 $3 $4" = "-KILL -ix -u $(id -u)" ] && '
                    "[ \"$5\" = 'dreamseeker[.]exe|byond[.]exe|wineserver[.]exe' ] || exit 2\n"
                    'printf "kill-clients\\n" >> "$EVENT_LOG"'
                ),
                "wineserver": (
                    '[ "$WINEPREFIX" = "$EXPECTED_PREFIX" ] || exit 2\n'
                    'case "$1" in\n'
                    '  -k9) printf "kill-server\\n" >> "$EVENT_LOG";;\n'
                    '  --wait) printf "wait-server\\n" >> "$EVENT_LOG"; '
                    'test "$WARMUP" != "cleanup-fails";;\n'
                    "  *) exit 2;;\n"
                    "esac"
                ),
                "xdpyinfo": (
                    'test "$1" = "-display" && test "$2" = "$EXPECTED_DISPLAY" && '
                    'test "${XAUTHORITY:-}" = "$EXPECTED_XAUTHORITY"'
                ),
                "wine": (
                    'case "$PATH" in /opt/wine-proton/bin:*) ;; '
                    '*) echo "Wrong Wine runtime path" >&2; exit 98;; esac\n'
                    'test "$WINELOADER" = /opt/wine-proton/bin/wine && '
                    'test "$WINESERVER" = /opt/wine-proton/bin/wineserver || exit 96\n'
                    'test "${XAUTHORITY:-}" = "$EXPECTED_XAUTHORITY" || exit 95\n'
                    'if [ -n "${LD_PRELOAD:-}" ]; then\n'
                    '  echo "LD_PRELOAD leaked to Wine" >&2\n'
                    "  exit 97\n"
                    "fi\n"
                    'if [ "$1" = reg ]; then\n'
                    '  printf "%s\\n" "$@" > "$WINE_LOG"\n'
                    '  [ "${FAIL_REGISTRY:-0}" = 0 ]\n'
                    "  exit $?\n"
                    "fi\n"
                    'printf "launch\\n" >> "$EVENT_LOG"\n'
                    'case "$1" in\n'
                    "  *dreamseeker.exe)\n"
                    '    launches=$(grep -c "^launch$" "$EVENT_LOG")\n'
                    '    if [ "$launches" = 1 ] && [ "$WARMUP" != "cleanup-pending" ]; then\n'
                    '      [ "$WARMUP" != "early-exit" ] || exit 0\n'
                    '      printf "%s\\n" "$$" > "$WINE_PID_FILE"\n'
                    '      while [ ! -e "$WINE_CLOSE_FILE" ]; do /bin/sleep 0.01; done\n'
                    "      exit 0\n"
                    "    fi\n"
                    "    ;;\n"
                    "esac\n"
                    'printf "%s\\n" "$DISPLAY" "$@"'
                ),
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)

            runtime = root / "runtime"
            runtime.mkdir()
            if warmup == "cleanup-pending":
                (runtime / "byond-dpi-warmup-complete").write_text("cleanup-pending\n")
            prefix = root / "wine prefix"
            authority = runtime / "kwin authority"
            (runtime / "container-env").write_text(
                f"export DISPLAY=':42'\nexport WINEPREFIX='{prefix}'\n"
                "export WINELOADER='/usr/bin/wine'\nexport WINESERVER='/usr/bin/wineserver'\n"
                f"export SELKIES_WAYLAND={'true' if wayland else 'false'}\n"
                "sleep() { SECONDS=$((SECONDS + $1)); /bin/sleep 0.02; }\n"
                + (f"export BYOND_SERVER='{server}'\n" if server is not None else "")
                + (f"export BYOND_WEBVIEW2_GPU='{gpu}'\n" if gpu is not None else "")
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
                "WINE_LOG": str(root / "wine-log"),
                "EVENT_LOG": str(root / "event-log"),
                "WINE_PID_FILE": str(root / "wine-pid"),
                "WINE_CLOSE_FILE": str(root / "wine-close"),
                "WARMUP": warmup,
                "EXPECTED_PREFIX": str(prefix),
                "FAIL_REGISTRY": "1" if fail_registry else "0",
                "LD_PRELOAD": "libm.so.6",
                "EXPECTED_DISPLAY": ":7" if wayland else ":42",
                "EXPECTED_XAUTHORITY": str(authority) if wayland else "",
            }
            env.pop("BYOND_SERVER", None)
            env.pop("BYOND_WEBVIEW2_GPU", None)
            env.pop("XAUTHORITY", None)
            if wayland:
                authority.write_text("test cookie")
                subprocess.run(
                    ["sh", str(ROOT / "container/publish-xwayland-env.sh")],
                    env={
                        **env,
                        "XDG_SESSION_TYPE": "wayland",
                        "DISPLAY": ":7",
                        "XAUTHORITY": str(authority),
                    },
                    check=True,
                    timeout=5,
                )
                handoff = runtime / "byond-xwayland"
                self.assertEqual(handoff.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("test cookie", handoff.read_text())
            result = subprocess.run(
                ["bash", str(ROOT / "container/run-client.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            log = root / "wine-log"
            events = root / "event-log"
            return (
                result,
                prefix,
                log.read_text().splitlines() if log.exists() else [],
                events.read_text().splitlines() if events.exists() else [],
            )

    def test_launches_wine_with_authenticated_plasma_display(self):
        result, prefix, _, _ = self.run_client(wayland=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [":7", str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe")],
        )

    def test_launches_byond_after_loading_session_environment(self):
        for server in (None, ""):
            with self.subTest(server=server):
                result, prefix, registry, events = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(registry, [])
                self.assertEqual(events, ["launch"])
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
                result, prefix, _, events = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch", "close", "launch"])
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
                result, _, _, _ = self.run_client(server)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid BYOND_SERVER", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_relaunches_if_warmup_exits_before_a_window_appears(self):
        result, _, _, events = self.run_client("example.org:1337", warmup="early-exit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch", "launch"])

    def test_forces_shutdown_before_relaunch_if_warmup_does_not_exit(self):
        for warmup, close_events in (("stuck", ["close"]), ("no-window", [])):
            with self.subTest(warmup=warmup):
                result, _, _, events = self.run_client(
                    "example.org:1337", warmup=warmup
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("timed out after 15 seconds", result.stderr)
                self.assertEqual(
                    events,
                    ["launch"]
                    + close_events
                    + ["kill-clients", "kill-server", "wait-server", "launch"],
                )

    def test_does_not_relaunch_when_wine_shutdown_fails(self):
        result, _, _, events = self.run_client(
            "example.org:1337", warmup="cleanup-fails"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Wine server did not stop", result.stderr)
        self.assertEqual(
            events, ["launch", "close", "kill-clients", "kill-server", "wait-server"]
        )

    def test_service_restart_retries_pending_cleanup_before_launch(self):
        result, _, _, events = self.run_client(
            "example.org:1337", warmup="cleanup-pending"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            events, ["kill-clients", "kill-server", "wait-server", "launch"]
        )

    def test_configures_webview2_gpu_before_launch(self):
        result, prefix, registry, events = self.run_client("example.org:1337", gpu="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch", "close", "launch"])
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
        result, _, registry, events = self.run_client(gpu="1", fail_registry=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(registry)
        self.assertEqual(events, [])
        self.assertIn("Failed to configure WebView2", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rejects_invalid_webview2_gpu_setting(self):
        result, _, registry, events = self.run_client(gpu="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(registry, [])
        self.assertEqual(events, [])
        self.assertIn("Invalid BYOND_WEBVIEW2_GPU", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
