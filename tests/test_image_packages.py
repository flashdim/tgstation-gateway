from pathlib import Path
import os
import re
import subprocess
import tempfile
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
    "dolphin",
    "kdf",
    "ksystemlog",
    "kcalc",
    "gwenview",
    "vim",
    "systemsettings",
    "plasma-systemmonitor",
}


class ImagePackagesTest(unittest.TestCase):
    def test_removes_installed_unneeded_apps(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("apt-get remove -y $removable_packages", dockerfile)
        package_filter = re.search(r"\$2 ~ /\^\(([^)]*)\)\$/", dockerfile).group(1)
        self.assertEqual(set(package_filter.split("|")), APP_PACKAGES)
        self.assertIn("$2 ~ /^libreoffice/", dockerfile)
        self.assertIn('$1 == "installed"', dockerfile)

    def run_package_layer(self, installed="", fail_apt="", fail_hold=False):
        dockerfile = (ROOT / "Dockerfile").read_text()
        script = re.search(r"RUN (set -eu;.*?)(?:\n\n)", dockerfile, re.S)[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "commands"
            for name, body in {
                "selkies-privileged-files": 'printf "selkies %s\\n" "$*" >> "$LOG"',
                "dpkg": 'printf "dpkg %s\\n" "$*" >> "$LOG"',
                "dpkg-query": 'printf "%s" "$INSTALLED"',
                "apt-mark": (
                    'printf "apt-mark %s\\n" "$*" >> "$LOG"\n[ "$FAIL_HOLD" != "true" ]'
                ),
                "apt-get": (
                    'printf "apt-get %s\\n" "$*" >> "$LOG"\n[ "$1" != "$FAIL_APT" ]'
                ),
                "rm": 'printf "rm %s\\n" "$*" >> "$LOG"',
            }.items():
                command = root / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)
            result = subprocess.run(
                ["sh", "-c", script.replace("\\\n", " ")],
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "LOG": str(log),
                    "INSTALLED": installed,
                    "FAIL_APT": fail_apt,
                    "FAIL_HOLD": str(fail_hold).lower(),
                    "WINE_PACKAGE_VERSION": "test-version",
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result, log.read_text().splitlines()

    def test_upgrades_then_installs_dependencies_before_unconditional_cleanup(self):
        for installed in ("", "installed kate\n"):
            with self.subTest(installed=installed):
                result, commands = self.run_package_layer(installed)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    [
                        command.startswith("apt-get remove ") for command in commands
                    ].count(True),
                    bool(installed),
                )
                update = commands.index("apt-get update")
                remove_sources = commands.index(
                    "rm -f /etc/apt/sources.list.d/steam-stable.list"
                    " /etc/apt/sources.list.d/steam-beta.list"
                )
                hold = commands.index(
                    "apt-mark hold kwin-addons kwin-common kwin-data"
                    " kwin-wayland libkwin6"
                )
                upgrade = commands.index("apt-get dist-upgrade -y --no-remove")
                install = next(
                    i
                    for i, command in enumerate(commands)
                    if command.startswith("apt-get install ")
                )
                autoremove = commands.index("apt-get autoremove -y")
                clean = commands.index("apt-get clean")
                self.assertLess(remove_sources, update)
                self.assertLess(update, hold)
                self.assertLess(hold, upgrade)
                self.assertLess(upgrade, install)
                self.assertLess(install, autoremove)
                self.assertLess(autoremove, clean)
                self.assertIn("wine=test-version", commands[install])
                self.assertIn("wine32:i386=test-version", commands[install])
                self.assertIn("wine64=test-version", commands[install])
                self.assertEqual(commands[-1], "selkies restore")

    def test_failed_upgrade_stops_the_build(self):
        result, commands = self.run_package_layer(fail_apt="dist-upgrade")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands[-1], "apt-get dist-upgrade -y --no-remove")

    def test_failed_kwin_hold_stops_before_upgrade(self):
        result, commands = self.run_package_layer(fail_hold=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(commands[-1].startswith("apt-mark hold "))
        self.assertNotIn("apt-get dist-upgrade -y --no-remove", commands)


if __name__ == "__main__":
    unittest.main()
