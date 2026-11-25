import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopSessionTest(unittest.TestCase):
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
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 23)
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

    def test_selkies_runs_reset_session_after_client_connects(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        self.assertIn(
            "SELKIES_RUN_AFTER_CONNECT=/usr/local/bin/reset-session",
            dockerfile,
        )
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
