from configparser import ConfigParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopSessionTest(unittest.TestCase):
    def test_wayland_is_default_and_configurable_in_compose(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        self.assertIn("ARG SELKIES_WAYLAND=true", dockerfile)
        self.assertIn("SELKIES_WAYLAND: ${SELKIES_WAYLAND:-true}", compose)

    def test_display_size_is_only_set_by_explicit_compose_overrides(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        for setting in ("SELKIES_MANUAL_WIDTH", "SELKIES_MANUAL_HEIGHT"):
            with self.subTest(setting=setting):
                self.assertNotIn(setting, dockerfile)
                self.assertIn(f"      {setting}:\n", compose)

    def test_kwin_forces_maximization_only_for_the_matching_game_window(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("container/kwinrulesrc /etc/xdg/kwinrulesrc", dockerfile)
        config = ConfigParser()
        config.read(ROOT / "container/kwinrulesrc")
        rule = config[config["General"]["rules"]]
        self.assertEqual(rule["wmclass"], "steam_proton")
        self.assertEqual(rule.getint("wmclassmatch"), 1)  # Exact match.
        self.assertFalse(rule.getboolean("wmclasscomplete"))
        self.assertEqual(rule.getint("types"), 1)  # Normal windows only.
        self.assertEqual(rule["title"], "LazorGator Party")
        self.assertEqual(rule.getint("titlematch"), 2)  # Substring match.
        for setting, enabled in (
            ("maximizehoriz", True),
            ("maximizevert", True),
            ("fullscreen", False),
        ):
            with self.subTest(setting=setting):
                self.assertEqual(rule.getboolean(setting), enabled)
                self.assertEqual(rule.getint(f"{setting}rule"), 2)  # Force.

    def test_plasma_defaults_are_installed_as_system_defaults(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        layout = (ROOT / "container/plasma-layout.js").read_text()
        self.assertIn(
            "container/plasma-layout.js "
            "/usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/"
            "contents/layouts/org.kde.plasma.desktop-layout.js",
            dockerfile,
        )
        for setting in (
            'panel.alignment = "center"',
            'panel.lengthMode = "fit"',
            'panel.hiding = "autohide"',
            'panel.opacity = "opaque"',
            "panel.floating = false",
            "panel.height = 64",
            "applications:org.kde.dolphin.desktop",
            "applications:org.kde.plasma-systemmonitor.desktop",
            "file:///usr/share/tgstation-gateway/wallpaper.jpg",
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, layout)
        self.assertIn("--key LookAndFeelPackage org.kde.breezedark.desktop", dockerfile)
        self.assertIn("--key ColorScheme BreezeDark", dockerfile)
        self.assertIn(
            "assets/glory-to-nanotrasen.jpg /usr/share/tgstation-gateway/wallpaper.jpg",
            dockerfile,
        )
        self.assertLess(
            dockerfile.index(
                "install -d -o root -g root -m 755 /usr/share/tgstation-gateway"
            ),
            dockerfile.index("COPY --chmod=644 assets/glory-to-nanotrasen.jpg"),
        )

    def test_glory_to_nanotrasen_asset_and_attribution_are_in_repository(self):
        asset = ROOT / "assets/glory-to-nanotrasen.jpg"
        attribution = (ROOT / "assets/ATTRIBUTION.md").read_text()
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 10_000)
        self.assertIn("Glory to Nanotrasen", attribution)
        self.assertIn("partheosis", attribution)
        self.assertIn("CC BY-NC 3.0", attribution)
        self.assertIn("547539107", attribution)


if __name__ == "__main__":
    unittest.main()
