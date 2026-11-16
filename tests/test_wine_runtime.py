import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
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
        self.log = self.root / "ldd.log"
        self.runtime = self.root / "wine-proton"
        self.libraries = self.root / "libraries"
        for architecture in ("i386", "x86_64"):
            directory = self.runtime / "lib/wine" / f"{architecture}-unix"
            directory.mkdir(parents=True)
            for name in MODULES:
                path = directory / name
                path.touch()
                path.chmod(0o755)
            if architecture == "x86_64":
                path = directory / "winegstreamer.so"
                path.touch()
                path.chmod(0o755)
            libraries = self.libraries / f"{architecture}-linux-gnu"
            libraries.mkdir(parents=True)
            for name in LIBRARIES:
                (libraries / name).touch()
        (self.runtime / "bin").mkdir()
        for name in ("wine", "wine-preloader", "wineserver"):
            path = self.runtime / "bin" / name
            path.touch()
            path.chmod(0o755)
        for name, body in {
            "dpkg-query": (
                '[ "${FAIL_DPKG:-0}" = 0 ] || exit 2\n'
                'printf "%s\\n" "${PACKAGES:-installed libc6:amd64}"'
            ),
            "ldd": (
                'printf "%s\\n" "$1" >> "$LDD_LOG"\n'
                'test -r "$1" || exit 1\n'
                '[ "${FAIL_LDD:-0}" = 0 ] || exit 2\n'
                'case "$1" in */lib/wine/*) '
                'test "$LD_LIBRARY_PATH" = "${1%/*}" || exit 3;; esac\n'
                'printf "%s\\n" "${DEPENDENCIES:-libc.so.6 => /lib/libc.so.6}"'
            ),
        }.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.check = re.search(r"RUN (set -eu;.*?)(?:\n\n)", dockerfile, re.S)[1]
        self.check = self.check.replace("\\\n", " ").replace(
            "/opt/wine-proton", str(self.runtime)
        )
        self.check = self.check.replace("/usr/lib/", f"{self.libraries}/")

    def test_pins_proton_10_0_4_amd64_archive_and_checksum(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn(
            "https://github.com/Kron4ek/Wine-Builds/releases/download/"
            "proton-10.0-4/wine-proton-10.0-4-amd64.tar.xz",
            dockerfile,
        )
        self.assertIn(
            "ffaf6e766f916a408d273254f6b9c42b1589ac1bb4b02e09ab04650c87bca290",
            dockerfile,
        )

    def test_ci_checks_proton_10_preloader_location(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("test -x /opt/wine-proton/bin/wine-preloader", workflow)
        self.assertNotIn("/opt/wine-proton/lib/wine/i386-unix/wine-preloader", workflow)

    def check_runtime(self, **extra_env):
        return subprocess.run(
            ["sh", "-c", self.check],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "LDD_LOG": str(self.log),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_checks_loaders_and_core_modules_in_both_architectures(self):
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = self.log.read_text().splitlines()
        for architecture in ("i386", "x86_64"):
            for module in MODULES:
                self.assertIn(
                    str(self.runtime / "lib/wine" / f"{architecture}-unix" / module),
                    checked,
                )
        self.assertIn(
            str(self.runtime / "lib/wine/x86_64-unix/winegstreamer.so"), checked
        )
        self.assertNotIn(
            str(self.runtime / "lib/wine/i386-unix/winegstreamer.so"), checked
        )
        for binary in ("wine", "wineserver"):
            self.assertIn(str(self.runtime / "bin" / binary), checked)
        self.assertTrue(os.access(self.runtime / "bin/wine-preloader", os.X_OK))
        for optional in ("winedmo", "wpcap"):
            self.assertFalse(any(optional in path for path in checked))

    def test_rejects_installed_distro_wine_packages(self):
        for package in (
            "wine",
            "wine32:i386",
            "wine64:amd64",
            "wine-common",
            "wine32-preloader:i386",
            "libwine:amd64",
            "libwine:i386",
        ):
            with self.subTest(package=package):
                result = self.check_runtime(PACKAGES=f"installed {package}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Distro Wine packages", result.stderr)

    def test_allows_removed_package_configuration_records(self):
        result = self.check_runtime(PACKAGES="config-files libwine:i386")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_linked_dependency(self):
        result = self.check_runtime(DEPENDENCIES="libpulse.so.0 => not found")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing dependencies", result.stderr)

    def test_rejects_failed_dependency_or_package_query(self):
        for env in ({"FAIL_DPKG": "1"}, {"FAIL_LDD": "1"}):
            with self.subTest(env=env):
                self.assertNotEqual(self.check_runtime(**env).returncode, 0)

    def test_requires_both_module_architectures(self):
        (self.runtime / "lib/wine/i386-unix/winepulse.so").unlink()
        self.assertNotEqual(self.check_runtime().returncode, 0)

    def test_allows_absent_optional_i386_gstreamer_module(self):
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_dynamically_loaded_libraries(self):
        (self.libraries / "i386-linux-gnu/libgnutls.so.30").unlink()
        self.assertNotEqual(self.check_runtime().returncode, 0)


if __name__ == "__main__":
    unittest.main()
