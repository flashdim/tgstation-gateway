import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class WindowManagerTest(unittest.TestCase):
    def test_maximizes_only_normal_steam_proton_windows(self):
        config = ET.parse(ROOT / "container/openbox/rc.xml").getroot()
        applications = config.findall("./applications/application")

        self.assertEqual(len(applications), 1)
        application = applications[0]
        self.assertEqual(
            application.attrib, {"class": "steam_proton", "type": "normal"}
        )
        self.assertEqual(application.findtext("maximized"), "true")
        self.assertIsNone(application.find("fullscreen"))

    def test_launches_on_session_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'shift\nexec "$@"',
                "xdpyinfo": 'test "$1" = "-display" && test "$2" = ":42"',
                "openbox": 'printf "%s\\n" "$DISPLAY"',
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "container-env").write_text("export DISPLAY=':42'\n")
            result = subprocess.run(
                ["sh", str(ROOT / "container/run-window-manager.sh")],
                env={
                    **os.environ,
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), ":42")

    def test_tray_only_starts_for_pager(self):
        for server, expected in (
            ("", "tray :42"),
            ("example.org:1337", "sleep infinity"),
        ):
            with (
                self.subTest(server=server),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                commands = root / "bin"
                commands.mkdir()
                for name, body in {
                    "timeout": 'shift\nexec "$@"',
                    "xdpyinfo": 'test "$1" = "-display" && test "$2" = ":42"',
                    "trayer": 'printf "tray %s\\n" "$DISPLAY"',
                    "sleep": 'printf "sleep %s\\n" "$1"',
                }.items():
                    command = commands / name
                    command.write_text(f"#!/bin/sh\n{body}\n")
                    command.chmod(0o755)
                runtime = root / "runtime"
                runtime.mkdir()
                (runtime / "container-env").write_text(
                    f"export DISPLAY=':42'\nexport BYOND_SERVER='{server}'\n"
                )
                result = subprocess.run(
                    ["sh", str(ROOT / "container/run-tray.sh")],
                    env={
                        **os.environ,
                        "PATH": f"{commands}:{os.environ['PATH']}",
                        "XDG_RUNTIME_DIR": str(runtime),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
