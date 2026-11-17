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
            for name in (*MODULES, "wine", "wine-preloader"):
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
            "ldd": (
                'printf "%s\\n" "$1" >> "$LDD_LOG"\n'
                'test -r "$1" || exit 1\n'
                '[ "${FAIL_LDD:-0}" = 0 ] || exit 2\n'
                'case "$1" in */lib/wine/*.so) '
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
        manifest = (ROOT / "container/wine-proton.env").read_text()
        self.assertIn('WINE_PROTON_VERSION="${WINE_PROTON_VERSION:-10.0-4}"', manifest)
        self.assertIn(
            "ffaf6e766f916a408d273254f6b9c42b1589ac1bb4b02e09ab04650c87bca290",
            manifest,
        )

    def test_ci_checks_proton_10_preloader_location(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        self.assertIn("tests/check-wine-runtime.sh", workflow)
        self.assertIn('10.0-4) loaders="/opt/wine-proton/bin/wine-preloader"', check)
        self.assertIn("/opt/wine-proton/lib/wine/i386-unix/wine-preloader", check)

    def check_runtime(self, **extra_env):
        return subprocess.run(
            ["sh", "-c", self.check],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "LDD_LOG": str(self.log),
                "WINE_PROTON_VERSION": "10.0-4",
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

    def test_proton_11_requires_relocated_loaders(self):
        (self.runtime / "bin/wine-preloader").unlink()
        result = self.check_runtime(WINE_PROTON_VERSION="11.0-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        for architecture in ("i386", "x86_64"):
            directory = self.runtime / "lib/wine" / f"{architecture}-unix"
            self.assertIn(str(directory / "wine"), self.log.read_text().splitlines())
            loader = directory / "wine-preloader"
            loader.chmod(0o644)
            self.assertNotEqual(
                self.check_runtime(WINE_PROTON_VERSION="11.0-2").returncode, 0
            )
            loader.chmod(0o755)

    def test_uses_pinned_ubuntu_wine_packages_for_dependencies(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WINE_PACKAGE_VERSION=10.0~repack-12ubuntu1", dockerfile)
        for package in ("wine", "wine32:i386", "wine64"):
            self.assertIn(f'"{package}=${{WINE_PACKAGE_VERSION}}"', dockerfile)
        self.assertIn("libgstreamer-gl1.0-0:i386", dockerfile)
        self.assertNotIn("dpkg-query", self.check)
        self.assertIn("ENV PATH=/opt/wine-proton/bin:${PATH}", dockerfile)

    def test_rejects_missing_linked_dependency(self):
        result = self.check_runtime(DEPENDENCIES="libpulse.so.0 => not found")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing dependencies", result.stderr)

    def test_rejects_failed_dependency_query(self):
        self.assertNotEqual(self.check_runtime(FAIL_LDD="1").returncode, 0)

    def test_requires_both_module_architectures(self):
        (self.runtime / "lib/wine/i386-unix/winepulse.so").unlink()
        self.assertNotEqual(self.check_runtime().returncode, 0)

    def test_allows_absent_optional_i386_gstreamer_module(self):
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_dynamically_loaded_libraries(self):
        (self.libraries / "i386-linux-gnu/libgnutls.so.30").unlink()
        result = self.check_runtime()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("i386-linux-gnu/libgnutls.so.30", result.stderr)

    def test_ci_runtime_diagnostics_name_each_missing_requirement(self):
        check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        check = check.replace("/opt/wine-proton", str(self.runtime)).replace(
            "/usr/lib/", f"{self.libraries}/"
        )
        env = {
            **os.environ,
            "PATH": f"{self.runtime / 'bin'}:{os.environ['PATH']}",
            "WINE_PROTON_VERSION": "10.0-4",
        }

        def run():
            return subprocess.run(
                ["sh", "-c", check], env=env, capture_output=True, text=True
            )

        self.assertEqual(run().returncode, 0)
        for path in (
            self.runtime / "bin/wine",
            self.runtime / "bin/wine-preloader",
            *(
                self.libraries / "i386-linux-gnu" / name
                for name in ("libfreetype.so.6", "libfontconfig.so.1", "libvulkan.so.1")
            ),
        ):
            with self.subTest(path=path):
                path.rename(path.with_suffix(path.suffix + ".missing"))
                result = run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(path), result.stderr)
                path.with_suffix(path.suffix + ".missing").rename(path)


if __name__ == "__main__":
    unittest.main()
