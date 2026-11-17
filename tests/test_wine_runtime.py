import os
from pathlib import Path
import re
import shutil
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


def module_directory(runtime, architecture):
    return runtime / "lib/wine" / f"{architecture}-unix"


class WineRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "ldd.log"
        self.runtime = self.root / "wine-staging"
        self.libraries = self.root / "libraries"
        for architecture in ("i386", "x86_64"):
            directory = module_directory(self.runtime, architecture)
            directory.mkdir(parents=True)
            windows = directory.with_name(f"{architecture}-windows")
            windows.mkdir()
            (windows / "ntdll.dll").touch()
            if architecture == "x86_64":
                for module in ("wow64.dll", "wow64cpu.dll"):
                    (windows / module).touch()
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
        for name in ("wine", "wineserver"):
            path = self.runtime / "bin" / name
            path.touch()
            path.chmod(0o755)
        for name, body in {
            "dpkg-query": 'printf "%s" "${INSTALLED_WINE_PACKAGE_VERSION:-11.22~resolute-1}"',
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
        self.check = re.search(
            r"# Build-time gate.*?\nRUN (set -eu;.*?)(?:\n\n)", dockerfile, re.S
        )[1]
        self.check = self.check.replace("\\\n", " ").replace(
            "/opt/wine-staging", str(self.runtime)
        )
        self.check = self.check.replace("/usr/lib/", f"{self.libraries}/")

    def test_ci_checks_staging_loaders_in_both_library_directories(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        self.assertIn("tests/check-wine-runtime.sh", workflow)
        self.assertIn("for libdir in lib lib64", check)
        self.assertIn("for loader in wine wine-preloader", check)

    def check_runtime(self, **extra_env):
        return subprocess.run(
            ["sh", "-c", self.check],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "LDD_LOG": str(self.log),
                "WINE_PACKAGE_VERSION": "11.22~resolute-1",
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
                    str(module_directory(self.runtime, architecture) / module),
                    checked,
                )
        self.assertIn(
            str(self.runtime / "lib/wine/x86_64-unix/winegstreamer.so"), checked
        )
        self.assertNotIn(
            str(self.runtime / "lib/wine/i386-unix/winegstreamer.so"), checked
        )
        self.assertIn(str(self.runtime / "bin/wineserver"), checked)
        # WineHQ's bin/wine may be a wrapper, so ldd checks the ELF loaders.
        self.assertNotIn(str(self.runtime / "bin/wine"), checked)
        for optional in ("winedmo", "wpcap"):
            self.assertFalse(any(optional in path for path in checked))

    def test_requires_staging_elf_loaders_and_preloaders(self):
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)
        for architecture in ("i386", "x86_64"):
            directory = module_directory(self.runtime, architecture)
            self.assertIn(str(directory / "wine"), self.log.read_text().splitlines())
            loader = directory / "wine-preloader"
            loader.chmod(0o644)
            self.assertNotEqual(self.check_runtime().returncode, 0)
            loader.chmod(0o755)

    def test_requires_native_wayland_modules(self):
        for architecture in ("i386", "x86_64"):
            (module_directory(self.runtime, architecture) / "winewayland.so").unlink()
        result = self.check_runtime()
        self.assertNotEqual(result.returncode, 0)

    def test_accepts_alternate_lib64_packaging(self):
        destination = self.runtime / "lib64/wine"
        destination.mkdir(parents=True)
        for suffix in ("unix", "windows"):
            shutil.move(self.runtime / "lib/wine" / f"x86_64-{suffix}", destination)
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_lib64_alias_to_lib(self):
        (self.runtime / "lib64").symlink_to("lib", target_is_directory=True)
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_distinct_duplicate_unix_directories(self):
        duplicate = self.runtime / "lib64/wine/i386-unix"
        duplicate.mkdir(parents=True)
        result = self.check_runtime()
        self.assertNotEqual(result.returncode, 0)

    def test_accepts_new_wow64_without_i386_unix_modules(self):
        shutil.rmtree(module_directory(self.runtime, "i386"))
        result = self.check_runtime()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_requires_new_wow64_components_without_i386_unix_modules(self):
        shutil.rmtree(module_directory(self.runtime, "i386"))
        for module in ("wow64.dll", "wow64cpu.dll"):
            path = self.runtime / "lib/wine/x86_64-windows" / module
            path.unlink()
            result = self.check_runtime()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"Missing new WoW64 component {module}", result.stderr)
            path.touch()

    def test_rejects_missing_x86_64_unix_modules(self):
        shutil.rmtree(module_directory(self.runtime, "x86_64"))
        result = self.check_runtime()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing x86_64 Unix modules", result.stderr)

    def test_rejects_missing_windows_modules(self):
        for architecture in ("i386", "x86_64"):
            path = (
                module_directory(self.runtime, architecture).with_name(
                    f"{architecture}-windows"
                )
                / "ntdll.dll"
            )
            path.unlink()
            result = self.check_runtime()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"Missing {architecture} Windows modules", result.stderr)
            path.touch()

    def test_staging_is_the_only_runtime_source(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("ARG WINE_PACKAGE_VERSION=11.22~resolute-1", dockerfile)
        for obsolete in ("WINE_PACKAGE_SOURCE", "WINE_PROTON_VERSION", "wine-proton"):
            self.assertNotIn(obsolete, dockerfile)
        self.assertIn("libgstreamer-gl1.0-0:i386", dockerfile)
        self.assertIn("ENV PATH=/opt/wine-staging/bin:${PATH}", dockerfile)

    def test_rejects_mismatched_installed_package(self):
        self.assertNotEqual(
            self.check_runtime(
                INSTALLED_WINE_PACKAGE_VERSION="11.21~resolute-1"
            ).returncode,
            0,
        )

    def test_pins_signed_winehq_11_22_staging_package(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn('test "$WINE_PACKAGE_VERSION" = "11.22~resolute-1"', dockerfile)
        self.assertIn('"winehq-staging=$WINE_PACKAGE_VERSION"', dockerfile)
        self.assertIn("apt-get install -y --install-recommends", dockerfile)
        self.assertIn("gpg --batch --yes --dearmor", dockerfile)
        self.assertIn(
            "wine-builds/ubuntu/dists/resolute/winehq-resolute.sources", dockerfile
        )
        self.assertIn(
            "grep -Fx 'Signed-By: /etc/apt/keyrings/winehq-archive.gpg'", dockerfile
        )
        self.assertNotIn("winehq-devel", dockerfile)

    def test_rejects_missing_linked_dependency(self):
        result = self.check_runtime(DEPENDENCIES="libpulse.so.0 => not found")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing dependencies", result.stderr)

    def test_rejects_failed_dependency_query(self):
        self.assertNotEqual(self.check_runtime(FAIL_LDD="1").returncode, 0)

    def test_rejects_incomplete_installed_i386_unix_modules(self):
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
        (self.runtime / "lib64").symlink_to("lib", target_is_directory=True)
        check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        check = check.replace("/opt/wine-staging", str(self.runtime)).replace(
            "/usr/lib/", f"{self.libraries}/"
        )
        env = {
            **os.environ,
            "PATH": f"{self.runtime / 'bin'}:{self.bin}:{os.environ['PATH']}",
            "WINE_PACKAGE_VERSION": "11.22~resolute-1",
            "WINEPREFIX": str(self.root / "prefix"),
        }
        prefix = Path(env["WINEPREFIX"])
        prefix.mkdir()
        (prefix / ".gateway-wine-package-version").write_text(
            env["WINE_PACKAGE_VERSION"]
        )

        def run():
            return subprocess.run(
                ["sh", "-c", check], env=env, capture_output=True, text=True
            )

        self.assertEqual(run().returncode, 0)
        for path in (
            self.runtime / "bin/wine",
            self.runtime / "lib/wine/i386-unix/wine-preloader",
            self.runtime / "lib/wine/x86_64-unix/wine",
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

    def test_ci_rejects_wrong_package_or_prefix_version(self):
        check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        check = check.replace("/opt/wine-staging", str(self.runtime)).replace(
            "/usr/lib/", f"{self.libraries}/"
        )
        prefix = self.root / "prefix"
        prefix.mkdir()
        marker = prefix / ".gateway-wine-package-version"
        for installed, cached in (
            ("11.21~resolute-1", "11.22~resolute-1"),
            ("11.22~resolute-1", "11.21~resolute-1"),
        ):
            with self.subTest(installed=installed, cached=cached):
                marker.write_text(cached)
                result = subprocess.run(
                    ["sh", "-c", check],
                    env={
                        **os.environ,
                        "PATH": f"{self.runtime / 'bin'}:{self.bin}:{os.environ['PATH']}",
                        "WINE_PACKAGE_VERSION": "11.22~resolute-1",
                        "INSTALLED_WINE_PACKAGE_VERSION": installed,
                        "WINEPREFIX": str(prefix),
                    },
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("does not match WINE_PACKAGE_VERSION", result.stderr)


if __name__ == "__main__":
    unittest.main()
