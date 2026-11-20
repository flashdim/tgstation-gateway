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


if __name__ == "__main__":
    unittest.main()
