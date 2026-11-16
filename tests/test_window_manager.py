import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowManagerTest(unittest.TestCase):
    def run_window_manager(self, wayland=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'shift\nexec "$@"',
                "xdpyinfo": 'test "$1" = "-display" && test "$2" = ":42"',
                "openbox": 'printf "%s\\n" "$DISPLAY"',
                "sleep": 'printf "sleep %s\\n" "$1"',
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "container-env").write_text(
                "export DISPLAY=':42'\n"
                + (
                    f"export SELKIES_WAYLAND='{wayland}'\n"
                    if wayland is not None
                    else ""
                )
            )
            env = {
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "XDG_RUNTIME_DIR": str(runtime),
            }
            env.pop("SELKIES_WAYLAND", None)
            result = subprocess.run(
                ["sh", str(ROOT / "container/run-window-manager.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result

    def test_launches_on_session_display(self):
        for wayland in (None, "false"):
            with self.subTest(wayland=wayland):
                result = self.run_window_manager(wayland)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), ":42")

    def test_leaves_wayland_window_management_to_compositor(self):
        result = self.run_window_manager("true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "sleep infinity")

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
