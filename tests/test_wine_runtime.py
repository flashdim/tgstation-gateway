import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = "10.0~repack-12ubuntu1"
GE_PROTON_VERSION = "GE-Proton10-34"
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
    "libwayland-cursor.so.0",
)


class WineRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.runtime = self.root / "ge-proton"
        self.libraries = self.root / "libraries"
        self.log = self.root / "ldd.log"
        for architecture in ("i386", "x86_64"):
            directory = self.runtime / "files/lib/wine" / f"{architecture}-unix"
            directory.mkdir(parents=True)
            for name in (*MODULES, "wine", "wine-preloader"):
                path = directory / name
                path.touch()
                path.chmod(0o755)
            libraries = self.libraries / f"{architecture}-linux-gnu"
            libraries.mkdir(parents=True)
            for name in LIBRARIES:
                (libraries / name).touch()
        (self.runtime / "files/bin").mkdir(parents=True)
        for name in ("wine", "wine64", "wineserver"):
            path = self.runtime / "files/bin" / name
            path.touch()
            path.chmod(0o755)
        proton = self.runtime / "proton"
        proton.touch()
        proton.chmod(0o755)
        for name, body in {
            "dpkg-query": 'printf "%s" "${INSTALLED_WINE_PACKAGE_VERSION:-10.0~repack-12ubuntu1}"',
            "ldd": (
                'printf "%s\\n" "$1" >> "$LDD_LOG"\n'
                'test -r "$1" || exit 1\n'
                '[ "${FAIL_LDD:-0}" = 0 ] || exit 2\n'
                'case "$1" in */wine/*.so) '
                'case "$LD_LIBRARY_PATH" in "${1%/*}"*) ;; *) exit 3;; esac;; esac\n'
                'printf "%s\\n" "${DEPENDENCIES:-libc.so.6 => /lib/libc.so.6}"'
            ),
        }.items():
            path = self.bin / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

        dockerfile = (ROOT / "Dockerfile").read_text()
        check_block = re.search(
            r"# Build-time gate.*?\nRUN (set -eu;.*?)(?:\n\n)", dockerfile, re.S
        )[1]
        self.docker_check = check_block.replace("\\\n", " ")
        self.docker_check = self.docker_check.replace(
            "/opt/ge-proton", str(self.runtime)
        ).replace("/usr/lib/", f"{self.libraries}/")

        runtime_check = (ROOT / "tests/check-wine-runtime.sh").read_text()
        self.runtime_check = runtime_check.replace(
            "/opt/ge-proton", str(self.runtime)
        ).replace("/usr/lib/", f"{self.libraries}/")

    def run_check(self, script, **extra_env):
        return subprocess.run(
            ["sh", "-c", script],
            env={
                **os.environ,
                "PATH": f"{self.runtime / 'files/bin'}:{self.bin}:{os.environ['PATH']}",
                "LDD_LOG": str(self.log),
                "WINE_PACKAGE_VERSION": PACKAGE_VERSION,
                "GE_PROTON_VERSION": GE_PROTON_VERSION,
                "WINE": "/usr/local/bin/proton-wine",
                "STEAM_COMPAT_DATA_PATH": str(self.root / "compat"),
                "UMU_ID": "umu-default",
                "WINEPREFIX": str(self.root / "compat" / "pfx"),
                **extra_env,
            },
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_build_gate_checks_proton_modules_and_both_architectures(self):
        result = self.run_check(self.docker_check)
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = self.log.read_text().splitlines()
        for architecture in ("i386", "x86_64"):
            for module in MODULES:
                self.assertIn(
                    str(
                        self.runtime
                        / "files/lib/wine"
                        / f"{architecture}-unix"
                        / module
                    ),
                    checked,
                )
        self.assertIn(str(self.runtime / "files/bin/wine"), checked)
        self.assertIn(str(self.runtime / "files/bin/wine64"), checked)
        self.assertIn(str(self.runtime / "files/bin/wineserver"), checked)

    def test_requires_all_ubuntu_wine_packages_at_pinned_version(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn(f"ARG WINE_PACKAGE_VERSION={PACKAGE_VERSION}", dockerfile)
        self.assertIn('"wine=$WINE_PACKAGE_VERSION"', dockerfile)
        self.assertIn('"wine32:i386=$WINE_PACKAGE_VERSION"', dockerfile)
        self.assertIn('"wine64=$WINE_PACKAGE_VERSION"', dockerfile)
        self.assertIn("libwayland-cursor0:i386", dockerfile)
        result = self.run_check(
            self.docker_check,
            INSTALLED_WINE_PACKAGE_VERSION="10.0~repack-12ubuntu2",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_requires_checksum_pinned_proton_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        pin = (ROOT / "container/ge-proton.env").read_text()
        downloader = (ROOT / "container/download-ge-proton.sh").read_text()
        self.assertIn(f"GE_PROTON_VERSION={GE_PROTON_VERSION}", pin)
        self.assertRegex(pin, r"GE_PROTON_SHA512=[0-9a-f]{128}")
        self.assertIn("sha512sum -c -", downloader)
        self.assertIn("GE_PROTON_VERSION=${GE_PROTON_VERSION}", dockerfile)
        self.assertIn("/opt/ge-proton/files/bin", dockerfile)
        self.assertIn("FROM scratch AS ge-proton-download-cache", dockerfile)
        self.assertNotIn("winehq-staging", dockerfile)
        self.assertNotIn("/opt/wine-proton", dockerfile)

    def test_downloader_verifies_downloaded_and_cached_archives(self):
        content = b"pinned Proton archive"
        script_dir = self.root / "download"
        script_dir.mkdir()
        script = script_dir / "download-ge-proton.sh"
        script.write_text((ROOT / "container/download-ge-proton.sh").read_text())
        (script_dir / "ge-proton.env").write_text(
            "GE_PROTON_VERSION=test\n"
            f"GE_PROTON_SHA512={hashlib.sha512(content).hexdigest()}\n"
        )
        curl = self.bin / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            'while [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = -o ]; then output="$2"; shift 2; else shift; fi\n'
            "done\n"
            'printf "%s" "$ARCHIVE_CONTENT" > "$output"\n'
        )
        curl.chmod(0o755)
        destination = self.root / "cache"
        environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "ARCHIVE_CONTENT": content.decode(),
        }
        result = subprocess.run(
            ["sh", str(script), str(destination)],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = destination / "test.tar.gz"
        self.assertEqual(archive.read_bytes(), content)

        result = subprocess.run(
            ["sh", str(script), str(destination)],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        archive.write_bytes(b"corrupted cached archive")
        result = subprocess.run(
            ["sh", str(script), str(destination)],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_runtime_check_requires_correct_path_packages_and_prefix(self):
        prefix = self.root / "compat/pfx"
        prefix.mkdir(parents=True)
        marker = prefix / ".gateway-ge-proton-version"
        marker.write_text(GE_PROTON_VERSION)
        result = self.run_check(
            self.runtime_check,
            INSTALLED_WINE_PACKAGE_VERSION=PACKAGE_VERSION,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        marker.write_text("GE-Proton10-33")
        result = self.run_check(self.runtime_check)
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_missing_modules_and_linked_dependencies(self):
        module = self.runtime / "files/lib/wine/i386-unix/winewayland.so"
        module.unlink()
        result = self.run_check(self.docker_check)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(module), result.stderr)

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

        library = self.libraries / "i386-linux-gnu" / "libwayland-cursor.so.0"
        library.unlink()
        result = self.run_check(self.docker_check)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(library), result.stderr)


if __name__ == "__main__":
    unittest.main()
