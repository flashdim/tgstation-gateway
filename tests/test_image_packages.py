from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGES = {
    "steam-launcher",
    "heroic",
    "lutris",
    "firefox",
    "google-chrome-stable",
    "transmission-qt",
    "kget",
    "kdeconnect",
    "kwrite",
    "kate",
    "kinfocenter",
    "kmenuedit",
    "kmouth",
    "kmag",
    "ktimer",
    "kmousetool",
    "kcharselect",
    "kde-spectacle",
    "kfind",
    "konsole",
    "ark",
    "filelight",
    "okular",
    "sweeper",
    "vlc",
    "plasma-discover",
    "xterm",
    "vim",
}


class ImagePackagesTest(unittest.TestCase):
    def test_removes_installed_unneeded_apps(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("apt-get remove -y $removable_packages", dockerfile)
        package_filter = re.search(r"\$2 ~ /\^\(([^)]*)\)\$/", dockerfile).group(1)
        self.assertEqual(set(package_filter.split("|")), APP_PACKAGES)
        self.assertIn("$2 ~ /^libreoffice/", dockerfile)
        self.assertIn('$1 == "installed"', dockerfile)


if __name__ == "__main__":
    unittest.main()
