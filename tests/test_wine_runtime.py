import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = "11.22~resolute-1"
MODULES = (
    "ntdll.so",
    "win32u.so",
    "winex11.so",
    "winewayland.so",
    "winealsa.so",
    "winepulse.so",
    "winevulkan.so",
)
LIBRARIES = (
    "libfreetype.so.6",
    "libfontconfig.so.1",
    "libgnutls.so.30",
    "libgssapi_krb5.so.2",
    "libGL.so.1",
    "libEGL.so.1",
    "libvulkan.so.1",
)


class WineRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.runtime = self.root / "wine-staging"
        self.libraries = self.root / "libraries"
        self.log = self.root / "ldd.log"
        for architecture in ("i386", "x86_64"):
            directory = self.runtime / "lib/wine" / f"{architecture}-unix"
            directory.mkdir(parents=True)
            for name in (*MODULES, "wine", "wine-preloader"):
                path = directory / name
                path.touch()
                path.chmod(0o755)
            windows = directory.with_name(f"{architecture}-windows")
            windows.mkdir()
            (windows / "ntdll.dll").touch()
            if architecture == "x86_64":
                for module in ("wow64.dll", "wow64cpu.dll"):
                    (windows / module).touch()
            libraries = self.libraries / f"{architecture}-linux-gnu"
            libraries.mkdir(parents=True)
            for name in LIBRARIES:
                (libraries / name).touch()
        (self.runtime / "bin").mkdir()
        for name in ("wine", "wineserver"):
            path = self.runtime / "bin" / name
            path.touch()
            path.chmod(0o755)
        for name, body in {
            "dpkg-query": (
                'printf "%s" "${INSTALLED_WINE_PACKAGE_VERSION:-11.22~resolute-1}"'
            ),
            "ldd": (
                'printf "%s\\n" "$1" >> "$LDD_LOG"\n'
                'test -r "$1" || exit 1\n'
                '[ "${FAIL_LDD:-0}" = 0 ] || exit 2\n'
                'case "$1" in */wine/*.so) '
                'test "$LD_LIBRARY_PATH" = "${1%/*}" || exit 3;; esac\n'
                'printf "%s\\n" "${DEPENDENCIES:-libc.so.6 => /lib/libc.so.6}"'
            ),
        }.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

        dockerfile = (ROOT / "Dockerfile").read_text()
        self.docker_check = re.search(
            r"# Build-time gate.*?\nRUN (set -eu;.*?)(?:\n\n)", dockerfile, re.S
        )[1].replace("\\\n", " ")
        self.docker_check = self.docker_check.replace(
            "/opt/wine-staging", str(self.runtime)
        ).replace("/usr/lib/", f"{self.libraries}/")
        self.runtime_check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        self.runtime_check = self.runtime_check.replace(
            "/opt/wine-staging", str(self.runtime)
        ).replace("/usr/lib/", f"{self.libraries}/")

    def run_check(self, script, **extra_env):
        return subprocess.run(
            ["sh", "-c", script],
            env={
                **os.environ,
                "PATH": f"{self.runtime / 'bin'}:{self.bin}:{os.environ['PATH']}",
                "LDD_LOG": str(self.log),
                "WINE_PACKAGE_VERSION": PACKAGE_VERSION,
                "WINEPREFIX": str(self.root / "prefix"),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_build_gate_checks_staging_loaders_and_modules(self):
        result = self.run_check(self.docker_check)
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = self.log.read_text().splitlines()
        for architecture in ("i386", "x86_64"):
            for module in MODULES:
                self.assertIn(
                    str(self.runtime / "lib/wine" / f"{architecture}-unix" / module),
                    checked,
                )
        self.assertIn(str(self.runtime / "bin/wineserver"), checked)

    def test_requires_pinned_winehq_staging_package(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn(f"ARG WINE_PACKAGE_VERSION={PACKAGE_VERSION}", dockerfile)
        self.assertIn('"winehq-staging=$WINE_PACKAGE_VERSION"', dockerfile)
        self.assertIn(
            "wine-builds/ubuntu/dists/resolute/winehq-resolute.sources", dockerfile
        )
        self.assertIn("ENV PATH=/opt/wine-staging/bin:${PATH}", dockerfile)
        result = self.run_check(
            self.docker_check,
            INSTALLED_WINE_PACKAGE_VERSION="11.21~resolute-1",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_runtime_check_requires_package_marker_and_path(self):
        prefix = self.root / "prefix"
        prefix.mkdir()
        (prefix / ".gateway-wine-package-version").write_text(PACKAGE_VERSION)
        result = self.run_check(self.runtime_check, WINEPREFIX=str(prefix))
        self.assertEqual(result.returncode, 0, result.stderr)
        (prefix / ".gateway-wine-package-version").write_text("11.21~resolute-1")
        self.assertNotEqual(
            self.run_check(self.runtime_check, WINEPREFIX=str(prefix)).returncode, 0
        )

    def test_accepts_alternate_lib64_packaging(self):
        destination = self.runtime / "lib64/wine"
        destination.mkdir(parents=True)
        for suffix in ("i386-unix", "i386-windows", "x86_64-unix", "x86_64-windows"):
            shutil.move(self.runtime / "lib/wine" / suffix, destination)
        result = self.run_check(self.docker_check)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_new_wow64_without_i386_unix_modules(self):
        shutil.rmtree(self.runtime / "lib/wine/i386-unix")
        result = self.run_check(self.docker_check)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_modules_and_dependencies(self):
        module = self.runtime / "lib/wine/i386-unix/winewayland.so"
        module.unlink()
        result = self.run_check(self.docker_check)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing or unreadable", result.stderr)
        module.touch()
        result = self.run_check(
            self.docker_check, DEPENDENCIES="libpulse.so.0 => not found"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing dependencies", result.stderr)

    def test_rejects_missing_supplemental_library(self):
        library = self.libraries / "i386-linux-gnu" / "libgnutls.so.30"
        library.unlink()
        result = self.run_check(self.docker_check)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(library), result.stderr)


if __name__ == "__main__":
    unittest.main()
