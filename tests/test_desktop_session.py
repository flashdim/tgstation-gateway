from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopSessionTest(unittest.TestCase):
    def test_wayland_is_default_and_configurable_in_compose(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        self.assertIn("ARG SELKIES_WAYLAND=true", dockerfile)
        self.assertIn("SELKIES_WAYLAND: ${SELKIES_WAYLAND:-true}", compose)

    def test_default_display_size_matches_compose(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        compose = (ROOT / "examples/compose.yaml").read_text()
        for setting, value in (
            ("SELKIES_MANUAL_WIDTH", "1920"),
            ("SELKIES_MANUAL_HEIGHT", "1080"),
        ):
            with self.subTest(setting=setting):
                self.assertIn(f"{setting}={value}", dockerfile)
                self.assertIn(f"{setting}: ${{{setting}:-{value}}}", compose)


if __name__ == "__main__":
    unittest.main()
