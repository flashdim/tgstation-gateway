import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunClientTest(unittest.TestCase):
    def run_client(
        self,
        server=None,
        gpu=None,
        fail_registry=False,
        wayland=False,
        dimensions="1280x720",
        existing_layout=None,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'case "$1" in --kill-after=*) shift;; esac\nshift\nexec "$@"',
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
                    'printf "%s\\n" "$DISPLAY" "$@"'
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
                f"export SELKIES_WAYLAND={'true' if wayland else 'false'}\n"
                + (f"export BYOND_SERVER='{server}'\n" if server is not None else "")
                + (f"export BYOND_WEBVIEW2_GPU='{gpu}'\n" if gpu is not None else "")
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
                "WINE_LOG": str(root / "wine-log"),
                "EVENT_LOG": str(root / "event-log"),
                "EXPECTED_PREFIX": str(prefix),
                "FAIL_REGISTRY": "1" if fail_registry else "0",
                "LD_PRELOAD": "libm.so.6",
                "EXPECTED_DISPLAY": ":7" if wayland else ":42",
                "EXPECTED_XAUTHORITY": str(authority) if wayland else "",
                "DISPLAY_DIMENSIONS": dimensions,
            }
            env.pop("BYOND_SERVER", None)
            env.pop("BYOND_WEBVIEW2_GPU", None)
            env.pop("XAUTHORITY", None)
            layout = (
                prefix
                / "drive_c/users/steamuser/Documents/BYOND/Skins/exadv1/"
                / "spacestation13/saved.txt"
            )
            if existing_layout is not None:
                layout.parent.mkdir(parents=True)
                layout.write_text(existing_layout)
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
                layout.read_text() if layout.exists() else None,
            )

    def test_writes_display_sized_layout_over_existing_config(self):
        result, _, _, _, layout = self.run_client(
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
        result, prefix, _, _, _ = self.run_client(wayland=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [":7", str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe")],
        )

    def test_launches_byond_after_loading_session_environment(self):
        for server in (None, ""):
            with self.subTest(server=server):
                result, prefix, registry, events, _ = self.run_client(server)
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
                result, prefix, _, events, _ = self.run_client(server)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(events, ["launch"])
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
                result, _, _, _, _ = self.run_client(server)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid BYOND_SERVER", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_configures_webview2_gpu_before_launch(self):
        result, prefix, registry, events, _ = self.run_client(
            "example.org:1337", gpu="1"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["launch"])
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
        result, _, registry, events, _ = self.run_client(gpu="1", fail_registry=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(registry)
        self.assertEqual(events, [])
        self.assertIn("Failed to configure WebView2", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rejects_invalid_webview2_gpu_setting(self):
        result, _, registry, events, _ = self.run_client(gpu="yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(registry, [])
        self.assertEqual(events, [])
        self.assertIn("Invalid BYOND_WEBVIEW2_GPU", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
