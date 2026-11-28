import os
import importlib.util
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


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
        account=None,
        key=None,
        reset=False,
        gpu=None,
        fail_registry=False,
        wayland=False,
        dimensions="1280x720",
        existing_layout=None,
        wine_exit_code=0,
        cleanup_failure=None,
        existing_config=None,
        bad_config_directory=False,
        desktop_failure=None,
        desktop_delay=False,
        pager_ready_probe=False,
        pager_missing=False,
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
                    'if [ "$1" = -i ] && [ "$2" = -x ]; then '
                    'if [ "$5" = byond.exe ]; then test "$PAGER_MISSING" != 1; exit $?; fi; '
                    'test -f "$GAME_STARTED"; exit $?; fi\n'
                    'case "$CLEANUP_FAILURE" in pgrep) exit 2;; '
                    "survives) exit 0;; exiting) "
                    'if [ ! -f "$PGREP_SEEN" ]; then touch "$PGREP_SEEN"; '
                    "exit 0; fi;; esac\n"
                    "exit 1"
                ),
                "sleep": "exit 0",
                "s6-svc": 'exec bash "$RUN_CLIENT_SCRIPT"',
                "xdpyinfo": (
                    'test "$1" = "-display" && test "$2" = "$EXPECTED_DISPLAY" && '
                    'test "${XAUTHORITY:-}" = "$EXPECTED_XAUTHORITY" || exit 1\n'
                    'printf "  dimensions: %s pixels\\n" "$DISPLAY_DIMENSIONS"'
                ),
                "qdbus6": (
                    'test "$DBUS_SESSION_BUS_ADDRESS" = "unix:path=$XDG_RUNTIME_DIR/selkies-session-bus" || exit 1\n'
                    'case "$3" in\n'
                    "  org.freedesktop.DBus.GetId) echo current-bus ;;\n"
                    "  org.freedesktop.DBus.GetNameOwner) echo :1.23 ;;\n"
                    "  org.kde.StatusNotifierWatcher.IsStatusNotifierHostRegistered)\n"
                    '    if [ "$DESKTOP_DELAY" = 1 ] && [ ! -f "$DESKTOP_SEEN" ]; '
                    'then touch "$DESKTOP_SEEN"; echo false; else echo true; fi ;;\n'
                    "  *) exit 1 ;;\n"
                    "esac"
                ),
                "python3": (
                    'if [ "$1" != /usr/local/bin/x11-tray-ready.py ]; then\n'
                    f'  exec {sys.executable} "$@"\n'
                    "fi\n"
                    'if [ "$DESKTOP_FAILURE" = tray ]; then exit 1; fi\n'
                    'if [ "$DESKTOP_DELAY" = 1 ]; then test -f "$DESKTOP_SEEN" || exit 1; fi\n'
                    'touch "$DESKTOP_READY"'
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
                    '  test -f "$DESKTOP_READY" || exit 91\n'
                    '  test ! -e "/proc/$$/fd/9" || exit 93\n'
                    '  if flock -n "$XDG_RUNTIME_DIR/byond-cleanup.lock" '
                    "true; then exit 92; fi\n"
                    '  printf "%s\\n" "$@" >> "$WINE_LOG"\n'
                    '  [ "${FAIL_REGISTRY:-}" != "$3" ]\n'
                    "  exit $?\n"
                    "fi\n"
                    'printf "launch\\n" >> "$EVENT_LOG"\n'
                    'case "$1" in */dreamseeker.exe) touch "$GAME_STARTED";; esac\n'
                    'printf "%s\\n" "$DISPLAY" "$@"\n'
                    'if [ "$PAGER_READY_PROBE" = 1 ]; then\n'
                    "  for i in $(seq 1 50); do\n"
                    '    if [ -f "$XDG_RUNTIME_DIR/byond-pager-ready" ]; then '
                    'echo ready >> "$EVENT_LOG"; break; fi\n'
                    "    /bin/sleep 0.02\n"
                    "  done\n"
                    "fi\n"
                    "/bin/sleep 0.1\n"
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
            (runtime / "container-env").write_text(
                f"export DISPLAY=':42'\nexport WINEPREFIX='{prefix}'\n"
                "export WINELOADER='/usr/bin/wine'\nexport WINESERVER='/usr/bin/wineserver'\n"
                "export WINEDEBUG='+all'\n"
                f"export SELKIES_WAYLAND={'true' if wayland else 'false'}\n"
                + (f"export BYOND_SERVER='{server}'\n" if server is not None else "")
                + (f"export BYOND_ACCOUNT='{account}'\n" if account is not None else "")
                + (f"export BYOND_WEBVIEW2_GPU='{gpu}'\n" if gpu is not None else "")
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
                "BYOND_GAME_CONTROL": str(ROOT / "container/byond-game.sh"),
                "BYOND_KEY_CHECK": str(ROOT / "container/byond-key-check.py"),
                "RUN_CLIENT_SCRIPT": str(ROOT / "container/run-client.sh"),
                "WINE_LOG": str(root / "wine-log"),
                "EVENT_LOG": str(root / "event-log"),
                "CLEANUP_LOG": str(root / "cleanup-log"),
                "PGREP_SEEN": str(root / "pgrep-seen"),
                "GAME_STARTED": str(root / "game-started"),
                "CLEANUP_FAILURE": cleanup_failure or "",
                "EXPECTED_PREFIX": str(prefix),
                "FAIL_REGISTRY": fail_registry or "",
                "LD_PRELOAD": "libm.so.6",
                "EXPECTED_DISPLAY": ":7" if wayland else ":42",
                "EXPECTED_XAUTHORITY": str(authority) if wayland else "",
                "DISPLAY_DIMENSIONS": dimensions,
                "MOCK_WINE_EXIT_CODE": str(wine_exit_code),
                "DESKTOP_FAILURE": desktop_failure or "",
                "DESKTOP_DELAY": "1" if desktop_delay else "0",
                "DESKTOP_SEEN": str(root / "desktop-seen"),
                "DESKTOP_READY": str(root / "desktop-ready"),
                "PAGER_READY_PROBE": "1" if pager_ready_probe else "0",
                "PAGER_MISSING": "1" if pager_missing else "0",
            }
            env.pop("BYOND_SERVER", None)
            env.pop("BYOND_PASSWORD_FILE", None)
            env.pop("BYOND_ACCOUNT", None)
            env.pop("BYOND_WEBVIEW2_GPU", None)
            env.pop("XAUTHORITY", None)
            (runtime / "byond-plasma-ready").write_text(
                f"{'old-bus' if desktop_failure == 'stale-bus' else 'current-bus'}\n"
                f"{':1.99' if desktop_failure == 'stale-owner' else ':1.23'}\n"
            )
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
            if key is not None:
                key_path = prefix / "drive_c/users/steamuser/Documents/BYOND/key.txt"
                key_path.parent.mkdir(parents=True, exist_ok=True)
                key_path.write_text(key)
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
            script = "reset-session.sh" if reset else "run-client.sh"
            result = subprocess.run(
                ["bash", str(ROOT / "container" / script)],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertFalse((runtime / "byond-pager-ready").exists())
            if result.returncode == 0:
                for name, options in (
                    ("pager.txt", {"auto-login": "on"}),
                    ("seeker.txt", {"graphics-hwmode": "on", "guest-login": "off"}),
                ):
                    lines = (cfg / name).read_text().splitlines()
                    for option, value in options.items():
                        self.assertEqual(
                            [
                                line
                                for line in lines
                                if line.split() and line.split()[0] == option
                            ],
                            [f"{option} {value}"],
                        )
                    for line in (existing_config or {}).get(name, "").splitlines():
                        if line.split() and line.split()[0] not in options:
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

    def test_pager_readiness_is_published_and_cleared(self):
        result, _, _, events, _, _ = self.run_client(pager_ready_probe=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch", "ready"])

    def test_unobserved_pager_never_becomes_ready(self):
        result, _, _, events, _, _ = self.run_client(
            pager_ready_probe=True, pager_missing=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ["launch"])
        self.assertIn("Timed out waiting for the BYOND pager", result.stderr)

    def test_updates_settings_without_discarding_other_preferences(self):
        config = {
            "pager.txt": "other-setting yes\nauto-login off\n  auto-login on\n",
            "seeker.txt": (
                "graphics-hwmode off\nguest-login on\n  guest-login off\n"
                "other-setting no\n"
            ),
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

    def test_waits_until_plasma_tray_host_is_registered(self):
        for wayland in (False, True):
            with self.subTest(wayland=wayland):
                result, _, registry, events, _, _ = self.run_client(
                    wayland=wayland, desktop_delay=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(registry, BYOND_REGISTRY)
                self.assertEqual(events, ["launch"])
                self.assertIn("Waiting for Plasma panel", result.stderr)

    def test_rejects_stale_plasma_session_or_missing_x11_tray(self):
        for failure in ("stale-bus", "stale-owner", "tray"):
            with self.subTest(failure=failure):
                result, _, registry, events, _, _ = self.run_client(
                    desktop_failure=failure
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(registry, [])
                self.assertEqual(events, [])
                self.assertIn("Timed out waiting for Plasma", result.stderr)

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

    def test_container_start_launches_only_pager_even_with_key(self):
        result, prefix, _, events, _, _ = self.run_client(
            "example.org:1337",
            account="LGplayer01",
            key="BEGIN KEY LGplayer01\nsecret\nEND KEY\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])
        self.assertEqual(
            result.stdout.splitlines(),
            [":42", str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe")],
        )

    def test_reset_launches_only_pager_without_matching_key(self):
        for key in (
            None,
            "BEGIN KEY Other\nsecret\nEND KEY\n",
            "BEGIN KEY LGplayer01\nEND KEY\n",
        ):
            with self.subTest(key=key):
                result, prefix, _, events, _, _ = self.run_client(
                    "example.org:1337", account="LGplayer01", key=key, reset=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch"])
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
                    ],
                )

    def test_reset_launches_only_pager_even_with_matching_key(self):
        for server in (
            "ss13.lazorgator.party:1337",
            "byond://example.org:1234",
            "[::1]:1337",
        ):
            with self.subTest(server=server):
                result, prefix, _, events, _, _ = self.run_client(
                    server,
                    account="LGplayer01",
                    key="BEGIN KEY lgplayer01\nsecret\nEND KEY\n",
                    reset=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch"])
                bin_dir = prefix / "drive_c/Program Files (x86)/BYOND/bin"
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        ":42",
                        str(bin_dir / "byond.exe"),
                    ],
                )

    def test_reset_with_invalid_server_keeps_pager(self):
        result, _, _, events, _, _ = self.run_client(
            "example.org", account="LGplayer01", reset=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])

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
                self.assertEqual(len(cleanup), 5)
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
        self.assertEqual(
            len([line for line in cleanup if line.startswith("pgrep -i -f")]), 2
        )

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


class GameStartTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        commands = self.root / "bin"
        commands.mkdir()
        runtime = self.root / "runtime"
        runtime.mkdir()
        prefix = self.root / "prefix"
        key = prefix / "drive_c/users/steamuser/Documents/BYOND/key.txt"
        key.parent.mkdir(parents=True)
        key.write_text("BEGIN KEY LGplayer01\nsecret\nEND KEY\n")
        (runtime / "container-env").write_text(
            f"export WINEPREFIX='{prefix}'\n"
            "export BYOND_SERVER='example.org:1337'\n"
            "export BYOND_ACCOUNT='LGplayer01'\n"
        )
        for name, body in {
            "pgrep": (
                'if [ -f "$TEST_ROOT/pgrep-error" ]; then exit 2; fi\n'
                'test "$1" = -i && test "$2" = -x && test "$3" = -u && '
                'case "$5" in byond.exe) test -f "$TEST_ROOT/pager"; exit $?;; '
                "dreamseeker.exe) ;; *) exit 2;; esac\n"
                'test -f "$TEST_ROOT/observed"'
            ),
            "sleep": "exec /bin/sleep 0.05",
            "pkill": 'rm -f "$TEST_ROOT/observed"; exit 0',
            "wine": (
                'test ! -e "/proc/$$/fd/9" || exit 99\n'
                'echo "$$" >> "$TEST_ROOT/pids"\n'
                'echo launch >> "$TEST_ROOT/launches"\n'
                'if [ -f "$TEST_ROOT/fail" ]; then exit 42; fi\n'
                'while [ ! -f "$TEST_ROOT/ready" ]; do /bin/sleep 0.05; done\n'
                'touch "$TEST_ROOT/observed"\n'
                "exec /bin/sleep 30"
            ),
        }.items():
            path = commands / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "XDG_RUNTIME_DIR": str(runtime),
            "TEST_ROOT": str(self.root),
            "BYOND_KEY_CHECK": str(ROOT / "container/byond-key-check.py"),
            "BYOND_VIEWER_CHECK": str(self.root / "viewer-check.py"),
        }
        (self.root / "viewer-check.py").write_text("import sys\nsys.exit(0)\n")
        (self.root / "pager").touch()
        start_time = Path(f"/proc/{os.getpid()}/stat").read_text().split()[21]
        (runtime / "byond-pager-ready").write_text(f"{os.getpid()} {start_time}\n")
        self.addCleanup(self.stop_games)

    def stop_games(self):
        pids = self.root / "pids"
        if pids.exists():
            for pid in pids.read_text().splitlines():
                subprocess.run(
                    ["kill", "-KILL", pid],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

    def start(self):
        return subprocess.Popen(
            ["bash", str(ROOT / "container/byond-game.sh"), "start"],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def wait_for(self, path):
        deadline = time.monotonic() + 5
        while not path.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def test_failed_launch_is_retryable(self):
        (self.root / "fail").touch()
        failed = self.start()
        self.assertEqual(failed.wait(timeout=5), 75)
        (self.root / "fail").unlink()
        (self.root / "ready").touch()
        retry = self.start()
        self.assertEqual(retry.wait(timeout=5), 0)
        self.assertEqual((self.root / "launches").read_text().count("launch"), 2)

    def test_timeout_cancels_pending_launch(self):
        failed = self.start()
        self.assertEqual(failed.wait(timeout=5), 75)
        (self.root / "ready").touch()
        time.sleep(0.2)
        self.assertFalse((self.root / "observed").exists())
        retry = self.start()
        self.assertEqual(retry.wait(timeout=5), 0)

    def test_process_lookup_error_does_not_launch(self):
        (self.root / "pgrep-error").touch()
        self.assertEqual(self.start().wait(timeout=5), 75)
        self.assertFalse((self.root / "launches").exists())

    def test_start_requires_pager(self):
        (self.root / "pager").unlink()
        (self.root / "ready").touch()
        self.assertEqual(self.start().wait(timeout=5), 75)
        self.assertFalse((self.root / "launches").exists())
        (self.root / "pager").touch()
        self.assertEqual(self.start().wait(timeout=5), 0)

    def test_start_requires_live_pager_supervisor(self):
        marker = self.root / "runtime/byond-pager-ready"
        marker.unlink()
        self.assertEqual(self.start().wait(timeout=5), 75)
        marker.write_text("invalid")
        self.assertEqual(self.start().wait(timeout=5), 75)
        marker.write_text(f"{os.getpid()} 0\n")
        self.assertEqual(self.start().wait(timeout=5), 75)
        self.assertFalse((self.root / "launches").exists())

    def test_concurrent_start_waits_for_interrupted_callers_monitor(self):
        first = self.start()
        self.wait_for(self.root / "launches")
        first.kill()
        first.wait(timeout=5)
        second = self.start()
        time.sleep(0.15)
        self.assertIsNone(second.poll())
        self.assertEqual((self.root / "launches").read_text().count("launch"), 1)
        (self.root / "ready").touch()
        self.assertEqual(second.wait(timeout=5), 0)
        self.assertEqual((self.root / "launches").read_text().count("launch"), 1)

    def test_watcher_reconciles_using_game_control(self):
        spec = importlib.util.spec_from_file_location(
            "connector", ROOT / "container/connect-on-selkies.py"
        )
        connector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(connector)

        def control(action):
            subprocess.run(
                ["bash", str(ROOT / "container/byond-game.sh"), action],
                env=self.env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

        (self.root / "ready").touch()
        watcher = connector.SessionWatcher({}, control=control)
        with patch.object(connector, "sessions_present", return_value=True):
            watcher.step()
            self.assertTrue((self.root / "observed").exists())
            (self.root / "observed").unlink()
            watcher.step()
            self.assertEqual((self.root / "launches").read_text().count("launch"), 2)
        with patch.object(connector, "sessions_present", return_value=False):
            connector.SessionWatcher({}, control=control).step()
            self.assertFalse((self.root / "observed").exists())

    def test_viewer_rechecked_after_waiting_for_reset_lock(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = self.server.body
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
                self.server.requested.set()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.body = b'{"sessions": [{}]}'
        server.requested = threading.Event()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.env["BYOND_VIEWER_CHECK"] = str(ROOT / "container/connect-on-selkies.py")
        self.env["SELKIES_PORT"] = str(server.server_address[1])
        (self.root / "ready").touch()
        spec = importlib.util.spec_from_file_location(
            "connector_race", ROOT / "container/connect-on-selkies.py"
        )
        connector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(connector)

        def control(action):
            subprocess.run(
                ["bash", str(ROOT / "container/byond-game.sh"), action],
                env=self.env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )

        watcher = connector.SessionWatcher(self.env, control=control)
        lock_path = self.root / "runtime/byond-cleanup.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending = threading.Thread(target=watcher.step)
            pending.start()
            self.assertTrue(server.requested.wait(timeout=5))
            server.body = b'{"sessions": []}'
            server.requested.clear()
            fcntl.flock(lock, fcntl.LOCK_UN)
            pending.join(timeout=5)
            self.assertFalse(pending.is_alive())
        self.assertTrue(server.requested.is_set())
        self.assertFalse((self.root / "launches").exists())

        server.body = b"invalid"
        self.assertEqual(self.start().wait(timeout=5), 75)
        self.assertFalse((self.root / "launches").exists())

        server.body = b'{"sessions": [{}]}'
        self.assertEqual(self.start().wait(timeout=5), 0)
        self.assertTrue((self.root / "observed").exists())


if __name__ == "__main__":
    unittest.main()
