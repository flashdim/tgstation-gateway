import ctypes
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopSessionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("Xvfb"), "Xvfb is unavailable")
    def test_x11_tray_readiness_requires_a_live_selection_owner(self):
        read_fd, write_fd = os.pipe()
        server = subprocess.Popen(
            ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "800x600x24"],
            pass_fds=(write_fd,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.close(write_fd)
        try:
            self.assertTrue(
                select.select([read_fd], [], [], 5)[0], "Xvfb did not start"
            )
            display_name = f":{os.read(read_fd, 32).decode().strip()}"
            env = {**os.environ, "DISPLAY": display_name}
            env.pop("XAUTHORITY", None)
            script = ROOT / "container/x11-tray-ready.py"

            def readiness():
                return subprocess.run(
                    ["python3", str(script)], env=env, capture_output=True, timeout=5
                ).returncode

            self.assertNotEqual(readiness(), 0)
            x11 = ctypes.CDLL("libX11.so.6")
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XCreateSimpleWindow.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_ulong,
                ctypes.c_ulong,
            ]
            x11.XCreateSimpleWindow.restype = ctypes.c_ulong
            x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            x11.XInternAtom.restype = ctypes.c_ulong
            x11.XSetSelectionOwner.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_ulong,
            ]
            x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
            display = x11.XOpenDisplay(display_name.encode())
            self.assertTrue(display)
            try:
                root = x11.XDefaultRootWindow(display)
                window = x11.XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0)
                atom = x11.XInternAtom(display, b"_NET_SYSTEM_TRAY_S0", 0)
                x11.XSetSelectionOwner(display, atom, window, 0)
                x11.XSync(display, 0)
                self.assertEqual(readiness(), 0)
            finally:
                x11.XCloseDisplay(display)
            self.assertNotEqual(readiness(), 0)
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=5)

    def test_plasma_readiness_marker_requires_stable_session(self):
        for failure in (False, True):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                commands = root / "bin"
                commands.mkdir()
                for name, body in {
                    "cat": 'echo "fixture script"',
                    "sleep": "exec /bin/sleep 0.02",
                    "qdbus6": (
                        'case "$3" in\n'
                        "  org.freedesktop.DBus.GetId) echo bus-id ;;\n"
                        "  org.freedesktop.DBus.GetNameOwner)\n"
                        '    if [ "$FAIL_CONFIG" = 1 ]; then echo :1.9; '
                        'elif [ -f "$NEW_OWNER" ]; then echo :1.10; '
                        'elif [ ! -f "$SEEN_OWNER" ]; then touch "$SEEN_OWNER"; echo :1.8; '
                        "else echo :1.9; fi ;;\n"
                        "  org.kde.PlasmaShell.evaluateScript)\n"
                        '    echo evaluation >> "$EVAL_LOG"\n'
                        '    if [ "$FAIL_CONFIG" = 1 ]; then echo waiting; else echo configured; fi ;;\n'
                        "  *) exit 1 ;;\n"
                        "esac"
                    ),
                }.items():
                    path = commands / name
                    path.write_text(f"#!/bin/sh\n{body}\n")
                    path.chmod(0o755)
                marker = root / "byond-plasma-ready"
                marker.write_text("old-bus\n:1.2\n")
                args = {
                    "env": {
                        **os.environ,
                        "PATH": f"{commands}:{os.environ['PATH']}",
                        "XDG_RUNTIME_DIR": str(root),
                        "FAIL_CONFIG": "1" if failure else "0",
                        "SEEN_OWNER": str(root / "seen-owner"),
                        "NEW_OWNER": str(root / "new-owner"),
                        "EVAL_LOG": str(root / "evaluations"),
                    },
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }

                process = subprocess.Popen(
                    ["sh", str(ROOT / "container/configure-plasma.sh")], **args
                )
                try:

                    def wait_until(predicate):
                        deadline = time.monotonic() + 10
                        while not predicate():
                            self.assertIsNone(process.poll(), "Plasma monitor exited")
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(0.02)

                    evaluations = root / "evaluations"
                    if failure:
                        wait_until(
                            lambda: (
                                evaluations.exists()
                                and evaluations.read_text().count("\n") >= 2
                            )
                        )
                        self.assertEqual(marker.read_text(), "old-bus\n:1.2\n")
                        continue

                    wait_until(lambda: marker.read_text() == "bus-id\n:1.9\n")
                    self.assertEqual(marker.read_text(), "bus-id\n:1.9\n")
                    self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(evaluations.read_text().count("\n"), 2)
                    self.assertIsNone(process.poll())
                    (root / "new-owner").touch()
                    wait_until(lambda: marker.read_text() == "bus-id\n:1.10\n")
                    self.assertEqual(evaluations.read_text().count("\n"), 3)
                finally:
                    process.terminate()
                    process.wait(timeout=5)

    def test_plasma_task_manager_and_tray_are_configured_at_login(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        layout = (ROOT / "container/plasma-layout.js").read_text()
        autostart = (ROOT / "container/configure-plasma.desktop").read_text()
        self.assertIn(
            "container/configure-plasma.desktop /etc/xdg/autostart/configure-plasma.desktop",
            dockerfile,
        )
        self.assertIn('widget.type === "org.kde.plasma.taskmanager"', layout)
        self.assertIn('widget.type === "org.kde.plasma.icontasks"', layout)
        self.assertIn(
            'widget.writeConfig("launchers", "applications:reset-session.desktop")',
            layout,
        )
        self.assertIn('"org.kde.plasma.volume"', layout)
        self.assertIn(
            'systray.writeConfig("scaleIconsToFit", true)',
            layout,
        )
        self.assertIn(
            'systray.writeConfig("shownItems", ["org.kde.plasma.volume"])',
            layout,
        )
        self.assertIn("var systray = widget;", layout)
        self.assertNotIn("SystrayContainmentId", layout)
        self.assertIn(
            'var alwaysEnabledItems = ["org.kde.plasma.volume"]',
            layout,
        )
        for item in (
            "org.kde.plasma.clipboard",
            "org.kde.plasma.cameraindicator",
            "org.kde.plasma.devicenotifier",
            "org.kde.plasma.keyboardlayout",
            "org.kde.plasma.keyboardindicator",
            "org.kde.plasma.diskquota",
            "org.kde.plasma.inputmethod",
            "org.kde.plasma.mediacontroller",
            "org.kde.plasma.notifications",
            "org.kde.plasma.trash",
            "org.kde.plasma.weather",
        ):
            with self.subTest(item=item):
                self.assertIn(f'"{item}"', layout)
        self.assertIn("alwaysEnabledItems.indexOf(item) === -1", layout)
        self.assertIn("disabledItems.indexOf(item) === -1", layout)
        self.assertIn('systray.writeConfig("hiddenItems", hiddenItems)', layout)
        self.assertIn('systray.writeConfig("extraItems", alwaysEnabledItems)', layout)
        self.assertIn('widget.type === "org.kde.plasma.digitalclock"', layout)
        self.assertIn(
            'systemTrayPanel.addWidget("org.kde.plasma.digitalclock")', layout
        )
        self.assertIn("Exec=/usr/local/bin/configure-plasma", autostart)

    def test_reset_session_shortcut_restarts_supervised_client(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        desktop = (ROOT / "container/reset-session.desktop").read_text()
        script = (ROOT / "container/reset-session.sh").read_text()
        self.assertIn(
            "container/reset-session.desktop /usr/share/applications/reset-session.desktop",
            dockerfile,
        )
        self.assertIn("Name=Reset Session", desktop)
        self.assertIn("Exec=/usr/local/bin/reset-session", desktop)
        self.assertIn("exec s6-svc -k /etc/service/byond", script)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertNotIn("SELKIES_RUN_AFTER_CONNECT=", dockerfile)
        self.assertNotIn("SELKIES_RUN_AFTER_CONTROLLER_", dockerfile)

    def test_reset_requests_restart_and_propagates_supervisor_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "s6-svc"
            command.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$@" > "$RESET_LOG"\nexit 23\n'
            )
            command.chmod(0o755)
            result = subprocess.run(
                ["bash", str(ROOT / "container/reset-session.sh")],
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "RESET_LOG": str(root / "reset-log"),
                    "XDG_RUNTIME_DIR": str(root),
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 23)
            self.assertFalse((root / "byond-reset-requested").exists())
            self.assertEqual(
                (root / "reset-log").read_text().splitlines(),
                ["-k", "/etc/service/byond"],
            )

    def test_wayland_is_default_and_configurable_in_compose(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        self.assertIn("ARG SELKIES_WAYLAND=true", dockerfile)
        self.assertIn("SELKIES_WAYLAND: ${SELKIES_WAYLAND:-true}", compose)

    def test_compose_sets_selkies_streaming_defaults_and_exposes_overrides(self):
        compose = (ROOT / "examples/compose.yaml").read_text()
        defaults = {
            "SELKIES_MODE": "websockets",
            "SELKIES_AUTO_GPU": "true",
            "SELKIES_USE_CPU": "false",
            "SELKIES_ENCODER": "h264enc",
            "SELKIES_GAMEPAD_ENABLED": "false",
            "SELKIES_MICROPHONE_ENABLED": "false",
            "SELKIES_WEBCAM_ENABLED": "false",
            "SELKIES_ENABLE_RESIZE": "true",
            "SELKIES_FRAMERATE": "60",
            "SELKIES_VIDEO_BITRATE": "8000",
            "SELKIES_AUDIO_BITRATE": "128000",
            "SELKIES_SCALING_DPI": "96",
            "SELKIES_UI_SIDEBAR_SHOW_SCREEN_SETTINGS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_AUDIO_SETTINGS": "false",
            "SELKIES_FILE_TRANSFERS": "none",
            "SELKIES_PRINTING_ENABLED": "false",
            "SELKIES_UI_TITLE": "LazorGator Party",
            "SELKIES_UI_SHOW_LOGO": "false",
            "SELKIES_UI_SHOW_CORE_BUTTONS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_FILES": "false",
            "SELKIES_UI_SIDEBAR_SHOW_APPS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_GAMEPADS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_WEBCAM": "false",
            "SELKIES_UI_SIDEBAR_SHOW_GAMING_MODE": "false",
            "SELKIES_UI_SIDEBAR_SHOW_TRACKPAD": "false",
            "SELKIES_UI_SIDEBAR_SHOW_SOFT_BUTTONS": "false",
        }
        for setting, default in defaults.items():
            with self.subTest(setting=setting):
                self.assertIn(f"{setting}: ${{{setting}:-{default}}}", compose)

    def test_docker_image_sets_selkies_defaults(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        defaults = {
            "SELKIES_MODE": "websockets",
            "SELKIES_FRAMERATE": "60",
            "SELKIES_UI_SIDEBAR_SHOW_SCREEN_SETTINGS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_AUDIO_SETTINGS": "false",
            "SELKIES_FILE_TRANSFERS": "none",
            "SELKIES_PRINTING_ENABLED": "false",
            "SELKIES_UI_TITLE": "LazorGator Party",
            "SELKIES_UI_SHOW_LOGO": "false",
            "SELKIES_UI_SHOW_CORE_BUTTONS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_FILES": "false",
            "SELKIES_UI_SIDEBAR_SHOW_APPS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_GAMEPADS": "false",
            "SELKIES_UI_SIDEBAR_SHOW_WEBCAM": "false",
            "SELKIES_UI_SIDEBAR_SHOW_GAMING_MODE": "false",
            "SELKIES_UI_SIDEBAR_SHOW_TRACKPAD": "false",
            "SELKIES_UI_SIDEBAR_SHOW_SOFT_BUTTONS": "false",
        }
        for setting, default in defaults.items():
            with self.subTest(setting=setting):
                rendered_default = (
                    f'"{default}"' if setting == "SELKIES_UI_TITLE" else default
                )
                self.assertIn(f"{setting}={rendered_default}", dockerfile)

    def test_selkies_uses_stock_presence_without_reset_hook(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        self.assertIn(
            "container/run-game-connection.sh /etc/service/byond-connect/run",
            dockerfile,
        )
        self.assertIn(
            "container/connect-on-selkies.py /usr/local/bin/connect-on-selkies.py",
            dockerfile,
        )
        self.assertIn(
            "container/byond-key-check.py /usr/local/bin/byond-key-check.py",
            dockerfile,
        )
        self.assertIn(
            "container/byond-game.sh /usr/local/bin/byond-game.sh", dockerfile
        )
        self.assertNotIn("SELKIES_RUN_AFTER_CONNECT", dockerfile)
        self.assertNotIn("SELKIES_RUN_AFTER_CONTROLLER_", dockerfile)
        self.assertNotIn("selkies-controller-presence.patch", dockerfile)
        self.assertNotIn("SELKIES_RUN_AFTER_CONNECT", compose)

    def test_display_size_is_only_set_by_explicit_compose_overrides(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        for setting in ("SELKIES_MANUAL_WIDTH", "SELKIES_MANUAL_HEIGHT"):
            with self.subTest(setting=setting):
                self.assertNotIn(setting, dockerfile)
                self.assertIn(f"      {setting}:\n", compose)

    def test_plasma_defaults_are_installed_as_system_defaults(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        layout = (ROOT / "container/plasma-default-layout.js").read_text()
        self.assertIn(
            "container/plasma-default-layout.js "
            "/usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/"
            "contents/layouts/org.kde.plasma.desktop-layout.js",
            dockerfile,
        )
        for setting in (
            'panel.alignment = "center"',
            'panel.lengthMode = "fit"',
            'panel.hiding = "dodgewindows"',
            'panel.opacity = "opaque"',
            "panel.floating = false",
            "panel.height = 64",
            'panel.addWidget("org.kde.plasma.taskmanager")',
            'tasks.writeConfig("maxTextLines", 1)',
            "applications:reset-session.desktop",
            'panel.addWidget("org.kde.plasma.systemtray")',
            'panel.addWidget("org.kde.plasma.digitalclock")',
            'wallpaperPlugin = "org.kde.slideshow"',
            '["Wallpaper", "org.kde.slideshow", "General"]',
            'writeConfig("SlidePaths", "/usr/share/tgstation-gateway/wallpapers")',
            'writeConfig("FillMode", 6)',
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, layout)
        self.assertIn("--key LookAndFeelPackage org.kde.breezedark.desktop", dockerfile)
        self.assertIn("--key ColorScheme BreezeDark", dockerfile)
        self.assertIn(
            "landing/assets/wallpapers/ /usr/share/tgstation-gateway/wallpapers/",
            dockerfile,
        )
        self.assertIn(
            "landing/assets/ATTRIBUTION.md /usr/share/tgstation-gateway/wallpaper-attribution.md",
            dockerfile,
        )
        self.assertLess(
            dockerfile.index(
                "install -d -o root -g root -m 755 /usr/share/tgstation-gateway/wallpapers"
            ),
            dockerfile.index("COPY --chmod=644 landing/assets/wallpapers/"),
        )
        smoke = (ROOT / "tests/smoke-container.sh").read_text()
        self.assertIn(
            "test -r /usr/share/tgstation-gateway/wallpaper-attribution.md", smoke
        )

    def test_wallpaper_assets_and_attribution_are_in_repository(self):
        assets = ROOT / "landing/assets"
        asset = assets / "wallpapers/glory-to-nanotrasen.jpg"
        logo = assets / "wallpapers/space-station-13-logo.svg"
        nanotrasen = assets / "wallpapers/nanotrasen-logo.png"
        paradise = assets / "wallpapers/ss13-paradise-ian-shuttle.png"
        attribution = (assets / "ATTRIBUTION.md").read_text()
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 10_000)
        self.assertTrue(logo.is_file())
        self.assertIn("<svg", logo.read_text())
        self.assertTrue(nanotrasen.is_file())
        self.assertGreater(nanotrasen.stat().st_size, 1_000)
        self.assertTrue(paradise.is_file())
        self.assertGreater(paradise.stat().st_size, 1_000)
        self.assertIn("Glory to Nanotrasen", attribution)
        self.assertIn("partheosis", attribution)
        self.assertIn("CC BY-NC 3.0", attribution)
        self.assertIn("547539107", attribution)
        self.assertIn("Wirewraith", attribution)
        self.assertIn("MIT License", attribution)
        self.assertIn("Copyright (c) 2022 Space Station 13", attribution)
        self.assertIn("LiamLime", attribution)
        self.assertIn("Public domain", attribution)
        self.assertIn("Nanotrasen_Logo.png", attribution)
        self.assertIn("Wakafanykai123", attribution)
        self.assertIn("CC BY-SA 4.0", attribution)
        self.assertIn("SS13-Paradise-IanShuttle.png", attribution)

    def test_smoke_tests_expect_configured_panel_hiding_mode(self):
        layout = (ROOT / "container/plasma-default-layout.js").read_text()
        self.assertIn('panel.hiding = "dodgewindows"', layout)
        for script in ("smoke-container.sh", "smoke-wayland.sh"):
            with self.subTest(script=script):
                smoke = (ROOT / "tests" / script).read_text()
                self.assertIn("p.hiding", smoke)
                self.assertIn("center,fit,dodgewindows,opaque,false,64", smoke)
                self.assertIn('readConfig("FillMode", -1)', smoke)
                self.assertIn('wallpaperPlugin !== "org.kde.slideshow"', smoke)


if __name__ == "__main__":
    unittest.main()
