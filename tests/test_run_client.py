import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunClientTest(unittest.TestCase):
    def test_launches_byond_after_loading_session_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name, body in {
                "timeout": 'shift\nexec "$@"',
                "xdpyinfo": 'test "$1" = "-display" && test "$2" = ":42"',
                "wine": 'printf "%s\\n" "$DISPLAY" "$1"',
            }.items():
                command = commands / name
                command.write_text(f"#!/bin/sh\n{body}\n")
                command.chmod(0o755)

            runtime = root / "runtime"
            runtime.mkdir()
            prefix = root / "wine prefix"
            (runtime / "container-env").write_text(
                f"export DISPLAY=':42'\nexport WINEPREFIX='{prefix}'\n"
            )
            result = subprocess.run(
                ["bash", str(ROOT / "container/run-client.sh")],
                env={
                    **os.environ,
                    "PATH": f"{commands}:{os.environ['PATH']}",
                    "XDG_RUNTIME_DIR": str(runtime),
                },
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            self.assertEqual(
                result.stdout.splitlines(),
                [
                    ":42",
                    str(prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
