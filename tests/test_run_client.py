import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BYOND_REGISTRY = [
    "reg",
    "add",
    r"HKCU\Software\Dantom\BYOND",
    "/v",
    "userpath",
    "/t",
    "REG_SZ",
    "/d",
    "C:\\users\\steamuser\\Documents\\BYOND\\",
    "/f",
]


class RunClientTest(unittest.TestCase):
    def run_client(
        self,
        server=None,
        gpu=None,
        fail_registry=False,
        wayland=False,
        dimensions="1280x720",
        existing_layout=None,
        wine_exit_code=0,
        cleanup_failure=None,
        password=None,
        existing_config=None,
        bad_config_directory=False,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'case "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"',
                "wineserver": (
                    'printf "wineserver %s\\n" "$1" >> "$CLEANUP_LOG"\n'
                    'if [ "$CLEANUP_FAILURE" = -k ] && [ "$1" = -k ]; '
                    "then exit 124; fi\n"
                    'if [ "$CLEANUP_FAILURE" = no_server ] && [ "$1" = -k ]; '
                    "then exit 1; fi\n"
                    'test "$CLEANUP_FAILURE" != "$1"'
                ),
                "pkill": (
                    'printf "pkill %s\\n" "$*" >> "$CLEANUP_LOG"\n'
                    'if [ "$CLEANUP_FAILURE" = pkill ]; then exit 2; fi\n'
                    'if [ "$CLEANUP_FAILURE" = exiting ]; then exit 0; fi\n'
                    "exit 1"
                ),
                "pgrep": (
                    'printf "pgrep %s\\n" "$*" >> "$CLEANUP_LOG"\n'
                    'case "$CLEANUP_FAILURE" in pgrep) exit 2;; '
                    "survives) exit 0;; exiting) "
                    'if [ ! -f "$PGREP_SEEN" ]; then touch "$PGREP_SEEN"; '
                    "exit 0; fi;; esac\n"
                    "exit 1"
                ),
                "sleep": "exit 0",
                "xdpyinfo": (
                    'test "$1" = "-display" && test "$2" = "$EXPECTED_DISPLAY" && '
                    'test "${XAUTHORITY:-}" = "$EXPECTED_XAUTHORITY" || exit 1\n'
                    'printf "  dimensions: %s pixels\\n" "$DISPLAY_DIMENSIONS"'
                ),
                "wine": (
                    'case "$PATH" in /opt/wine-proton/bin:*) ;; '
                    '*) echo "Wrong Wine runtime path" >&2; exit 98;; esac\n'
                    'test "$WINELOADER" = /opt/wine-proton/bin/wine && '
                    'test "$WINESERVER" = /opt/wine-proton/bin/wineserver || exit 96\n'
                    'test "$WINEDEBUG" = "-all" || exit 94\n'
                    'test "${XAUTHORITY:-}" = "$EXPECTED_XAUTHORITY" || exit 95\n'
                    'if [ -n "${LD_PRELOAD:-}" ]; then\n'
                    '  echo "LD_PRELOAD leaked to Wine" >&2\n'
                    "  exit 97\n"
                    "fi\n"
                    'if [ "$1" = reg ]; then\n'
                    '  test ! -e "/proc/$$/fd/9" || exit 93\n'
                    '  if flock -n "$XDG_RUNTIME_DIR/byond-cleanup.lock" '
                    "true; then exit 92; fi\n"
                    '  printf "%s\\n" "$@" >> "$WINE_LOG"\n'
                    '  [ "${FAIL_REGISTRY:-}" != "$3" ]\n'
                    "  exit $?\n"
                    "fi\n"
                    'if [ "$1" = /usr/local/lib/byond-login.exe ]; then\n'
                    '  cmp -s - "$BYOND_PASSWORD_FILE" || exit 89\n'
                    "fi\n"
                    'printf "launch\\n" >> "$EVENT_LOG"\n'
                    'printf "%s\\n" "$DISPLAY" "$@"\n'
                    'exit "$MOCK_WINE_EXIT_CODE"'
                ),
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)

            runtime = root / "runtime"
            runtime.mkdir()
            prefix = root / "wine prefix"
            authority = runtime / "kwin authority"
            password_file = root / "password"
            (runtime / "container-env").write_text(
                f"export DISPLAY=':42'\nexport WINEPREFIX='{prefix}'\n"
                "export WINELOADER='/usr/bin/wine'\nexport WINESERVER='/usr/bin/wineserver'\n"
                "export WINEDEBUG='+all'\n"
                f"export SELKIES_WAYLAND={'true' if wayland else 'false'}\n"
                + (f"export BYOND_SERVER='{server}'\n" if server is not None else "")
                + (f"export BYOND_WEBVIEW2_GPU='{gpu}'\n" if gpu is not None else "")
                + (
                    f"export BYOND_PASSWORD_FILE={shlex.quote(str(password_file))}\n"
                    "export BYOND_ACCOUNT=LGplayer02\n"
                    if password is not None
                    else ""
                )
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
                "WINE_LOG": str(root / "wine-log"),
                "EVENT_LOG": str(root / "event-log"),
                "CLEANUP_LOG": str(root / "cleanup-log"),
                "PGREP_SEEN": str(root / "pgrep-seen"),
                "CLEANUP_FAILURE": cleanup_failure or "",
                "EXPECTED_PREFIX": str(prefix),
                "FAIL_REGISTRY": fail_registry or "",
                "LD_PRELOAD": "libm.so.6",
                "EXPECTED_DISPLAY": ":7" if wayland else ":42",
                "EXPECTED_XAUTHORITY": str(authority) if wayland else "",
                "DISPLAY_DIMENSIONS": dimensions,
                "MOCK_WINE_EXIT_CODE": str(wine_exit_code),
            }
            env.pop("BYOND_SERVER", None)
            env.pop("BYOND_PASSWORD_FILE", None)
            env.pop("BYOND_ACCOUNT", None)
            env.pop("BYOND_WEBVIEW2_GPU", None)
            env.pop("XAUTHORITY", None)
            if password:
                password_file.write_bytes(password)
            layout = (
                prefix
                / "drive_c/users/steamuser/Documents/BYOND/Skins/exadv1/"
                / "spacestation13/saved.txt"
            )
            if existing_layout is not None:
                layout.parent.mkdir(parents=True)
                layout.write_text(existing_layout)
            cfg = prefix / "drive_c/users/steamuser/Documents/BYOND/cfg"
            if existing_config is not None:
                cfg.mkdir(parents=True)
                for name, contents in existing_config.items():
                    (cfg / name).write_text(contents)
            if bad_config_directory:
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text("not a directory")
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
            if result.returncode == 0:
                for name, option in (
                    ("pager.txt", "auto-login"),
                    ("seeker.txt", "graphics-hwmode"),
                ):
                    lines = (cfg / name).read_text().splitlines()
                    self.assertEqual(
                        [
                            line
                            for line in lines
                            if line.split() and line.split()[0] == option
                        ],
                        [f"{option} on"],
                    )
                    for line in (existing_config or {}).get(name, "").splitlines():
                        if line.split() and line.split()[0] != option:
                            self.assertIn(line, lines)
            log = root / "wine-log"
            events = root / "event-log"
            cleanup = root / "cleanup-log"
            return (
                result,
                prefix,
                log.read_text().splitlines() if log.exists() else [],
                events.read_text().splitlines() if events.exists() else [],
                layout.read_text() if layout.exists() else None,
                cleanup.read_text().splitlines() if cleanup.exists() else [],
            )

    def test_preserves_wine_exit_status(self):
        result, _, _, events, _, _ = self.run_client(wine_exit_code=23)
        self.assertEqual(result.returncode, 23)
        self.assertEqual(events, ["launch"])

    def test_passes_password_through_stdin_only(self):
        password = b"synthetic $`\\'\"!\r\n"
        result, _, registry, events, _, _ = self.run_client(
            server="example.org:1337",
            password=password,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(registry, BYOND_REGISTRY)
        self.assertEqual(events, ["launch"])
        self.assertEqual(
            result.stdout.splitlines(),
            [
                ":42",
                "/usr/local/lib/byond-login.exe",
                "LGplayer02",
                "byond://example.org:1337",
            ],
        )
        self.assertNotIn(password.strip().decode(), result.stderr)

    def test_missing_password_file_falls_back_to_manual_login(self):
        result, _, _, events, _, _ = self.run_client(password=b"")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("use the pager to log in manually", result.stderr)
        self.assertTrue(result.stdout.endswith("/BYOND/bin/byond.exe\n"))
        self.assertEqual(events, ["launch"])

    def test_updates_settings_without_discarding_other_preferences(self):
        config = {
            "pager.txt": "other-setting yes\nauto-login off\n  auto-login on\n",
            "seeker.txt": "graphics-hwmode off\nother-setting no\n",
        }
        result, _, _, events, _, _ = self.run_client(existing_config=config)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])

    def test_config_creation_failure_prevents_launch(self):
        result, _, _, events, _, _ = self.run_client(bad_config_directory=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_writes_display_sized_layout_over_existing_config(self):
        result, _, _, _, layout, _ = self.run_client(
            dimensions="1279x719", existing_layout="outdated layout"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = dict(line.split(" = ", 1) for line in layout.splitlines())
        self.assertEqual(
            {
                name: settings[name]
                for name in (
                    "mainwindow.size",
                    "mapwindow.size",
                    "lobby_screen.size",
                    "info_and_buttons.size",
                    "infobuttons.size",
                    "infowindow.size",
                    "statwindow.size",
                    "outputwindow.size",
                    "output_selector.size",
                    "output_browser.size",
                    "preferences_window.size",
                )
            },
            {
                "mainwindow.size": '"1215x591"',
                "mapwindow.size": '"853x591"',
                "lobby_screen.size": '"853x591"',
                "info_and_buttons.size": '"426x591"',
                "infobuttons.size": '"426x19"',
                "infowindow.size": '"426x559"',
                "statwindow.size": '"426x240"',
                "outputwindow.size": '"426x360"',
                "output_selector.size": '"426x360"',
                "output_browser.size": '"426x360"',
                "preferences_window.size": '"853x591"',
            },
        )
        self.assertEqual(settings["map_screen.map.zoom-mode"], '"distort"')
        self.assertEqual(settings["mainwindow.split.splitter"], '"66.666667"')
        self.assertNotIn("outdated layout", layout)

    def test_launches_wine_with_authenticated_plasma_display(self):
        result, prefix, _, _, _, _ = self.run_client(wayland=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [":7", str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe")],
        )

    def test_launches_byond_after_loading_session_environment(self):
        for server in (None, ""):
            with self.subTest(server=server):
                result, prefix, registry, events, _, _ = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(registry, BYOND_REGISTRY)
                self.assertEqual(events, ["launch"])
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
                    ],
                )

    def test_launches_pager_with_server_url(self):
        for server, url in (
            ("ss13.lazorgator.party:1337", "byond://ss13.lazorgator.party:1337"),
            ("byond://example.org:1234", "byond://example.org:1234"),
            ("[::1]:1337", "byond://[::1]:1337"),
        ):
            with self.subTest(server=server):
                result, prefix, _, events, _, _ = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch"])
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
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
                result, _, _, _, _, _ = self.run_client(server)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid BYOND_SERVER", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_configures_webview2_gpu_before_launch(self):
        result, prefix, registry, events, _, _ = self.run_client(
            "example.org:1337", gpu="1"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])
        self.assertEqual(
            registry,
            BYOND_REGISTRY
            + [
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
                str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
                "byond://example.org:1337",
            ],
        )

    def test_fails_without_launch_when_registry_update_fails(self):
        for key, message in (
            (r"HKCU\Software\Dantom\BYOND", "Failed to configure BYOND userpath"),
            (
                r"HKLM\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
                "Failed to configure WebView2",
            ),
        ):
            with self.subTest(key=key):
                result, _, registry, events, _, _ = self.run_client(
                    gpu="1", fail_registry=key
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(registry)
                self.assertEqual(events, [])
                self.assertIn(message, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_rejects_invalid_webview2_gpu_setting(self):
        result, _, registry, events, _, _ = self.run_client(gpu="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(registry, BYOND_REGISTRY)
        self.assertEqual(events, [])
        self.assertIn("Invalid BYOND_WEBVIEW2_GPU", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cleans_wine_and_webview_before_launch(self):
        for server in (None, "example.org:1337"):
            with self.subTest(server=server):
                result, _, _, events, _, cleanup = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch"])
                self.assertEqual(cleanup[:2], ["wineserver -k", "wineserver --wait"])
                self.assertEqual(len(cleanup), 4)
                pattern = r'(^|[\\/])(dreamseeker|byond|msedgewebview2)[.]exe"?([[:space:]]|$)'
                self.assertEqual(
                    cleanup[2], f"pkill -KILL -i -f -u {os.geteuid()} {pattern}"
                )
                self.assertEqual(cleanup[3], f"pgrep -i -f -u {os.geteuid()} {pattern}")

    def test_refuses_to_launch_when_cleanup_fails(self):
        for failure in ("-k", "--wait", "pkill", "pgrep", "survives"):
            with self.subTest(failure=failure):
                result, _, _, events, _, _ = self.run_client(cleanup_failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, [])
                self.assertIn("refusing to launch BYOND", result.stderr)

    def test_waits_for_signaled_webview_to_exit(self):
        result, _, _, events, _, cleanup = self.run_client(cleanup_failure="exiting")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])
        self.assertEqual(len([line for line in cleanup if line.startswith("pgrep")]), 2)

    def test_launches_when_no_wine_server_exists(self):
        result, _, _, events, _, cleanup = self.run_client(cleanup_failure="no_server")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(cleanup[:2], ["wineserver -k", "wineserver --wait"])
        self.assertEqual(events, ["launch"])

    def test_process_match_handles_windows_paths_and_long_names(self):
        pattern = r'(^|[\\/])(dreamseeker|byond|msedgewebview2)[.]exe"?([[:space:]]|$)'
        for executable in (
            r"C:\Program Files (x86)\Microsoft\EdgeWebView\msedgewebview2.exe",
            "/path with spaces/dreamseeker.exe",
            "/path/byond.exe",
        ):
            with self.subTest(executable=executable):
                process = subprocess.Popen(
                    ["bash", "-c", 'exec -a "$1" sleep 30', "bash", executable]
                )
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        first_arg = Path(f"/proc/{process.pid}/cmdline").read_bytes()
                        if first_arg.split(b"\0", 1)[0] == os.fsencode(executable):
                            break
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    result = subprocess.run(
                        ["pgrep", "-i", "-f", "-u", str(os.geteuid()), pattern],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertIn(str(process.pid), result.stdout.splitlines())
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
